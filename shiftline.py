#!/usr/bin/env python3
"""Codex Shiftline: a standalone Codex account-profile and session handoff utility.

Inspired by the profile-based `run` architecture of PavloPopravkin/codex-swap
(MIT). This is an independently maintained reduced rewrite, not the full cxswap.

The primary account runs directly in ~/.codex; additional logins use isolated
CODEX_HOME profiles. Existing history, configuration, sessions, skills and
memories are linked to ~/.codex. Codex manages refresh tokens in each home.
No token swapping,
usage API polling, automatic rate-limit rotation, or live-process switching.

Resumes use --no-daemon by default to avoid a daemon retaining a writer lock.
The switch command can offer a managed-daemon stop to release a writer lock.
Never kills arbitrary processes or deletes session locks.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

VERSION = "1.1.0"
HOME = Path.home()
SHARED = Path(os.environ.get("CODEX_SHARED_HOME", HOME / ".codex")).expanduser().resolve()
# Use the legacy standalone cxswap profile storage when upgrading so
# credentials and saved profiles are preserved. Fresh installs use a new name.
LEGACY_ROOT = HOME / ".codex-profiles-lite"
NEW_ROOT = HOME / ".codex-shiftline"
DEFAULT_ROOT = LEGACY_ROOT if LEGACY_ROOT.is_dir() and not NEW_ROOT.exists() else NEW_ROOT
ROOT = Path(os.environ.get("CODEX_PROFILES_HOME", DEFAULT_ROOT)).expanduser().resolve()
PROFILES = ROOT / "profiles"
ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
REQUIRED_DIRS = ("sessions", "memories", "skills", "prompts", "rules", "thread-writer-locks")
# Existing entries are symlinked too, including history.jsonl, config.toml,
# sqlite state and caches. Credentials and daemon state remain profile-local.
# Credential files and per-profile daemon runtime must NEVER be shared.
# Codex >=0.160 uses writable daemon state, PID records and Unix sockets
# under these CODEX_HOME directories; symlinking them breaks startup and can
# cross-connect accounts to a daemon authenticated as another account.
EXCLUDED = {"auth.json", "app-server-daemon", "app-server-control"}
DAEMON_DIRS = ("app-server-daemon", "app-server-control")
PRIMARY_MARKER = ".primary-shared-home"


def abort(msg):
    raise RuntimeError(msg)


def safe_alias(name):
    if not ALIAS_PATTERN.fullmatch(name):
        abort("Account alias must be 1–40 chars: letters, numbers, _ or -; start with a letter or number.")
    return name


def path_for(name):
    return PROFILES / safe_alias(name)


def ensure_secure_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        abort(f"Sensitive directory must not be a symlink: {path}")
    path.chmod(0o700)


@contextmanager
def lock():
    ensure_secure_directory(ROOT)
    ensure_secure_directory(PROFILES)
    lockfile = ROOT / ".lock"
    fd = os.open(lockfile, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def read_auth(path):
    try:
        if path.is_symlink():
            abort(f"Refusing symlinked credential file: {path}")
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            abort(f"Invalid JSON object in {path}")
        return data
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        abort(f"Invalid authentication JSON in {path}: {exc}")


def write_auth(path, data):
    if path.is_symlink():
        abort(f"Refusing symlinked credential file: {path}")
    descriptor, tmp_name = tempfile.mkstemp(prefix=".auth-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as fp:
            json.dump(data, fp)
            fp.write("\n")
            fp.flush()
            os.fsync(fp.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def identity(auth):
    if not auth:
        return "(not logged in)", None
    tokens = auth.get("tokens") or {}
    if tokens.get("id_token"):
        try:
            encoded = tokens["id_token"].split(".")[1]
            encoded += "=" * (-len(encoded) % 4)
            claims = json.loads(base64.urlsafe_b64decode(encoded))
            openai_claims = claims.get("https://api.openai.com/auth") or {}
            account_id = tokens.get("account_id") or openai_claims.get("chatgpt_account_id") or claims.get("sub")
            display = claims.get("email") or "ChatGPT account"
            plan = openai_claims.get("chatgpt_plan_type") or "unknown plan"
            return f"{display} ({plan})", str(account_id) if account_id else None
        except (IndexError, ValueError, TypeError):
            return "ChatGPT account (unreadable ID token)", None
    if auth.get("OPENAI_API_KEY"):
        return "API key authentication", "api-key"
    return "(unrecognized authentication)", None


def prepare_profile(name):
    if not SHARED.is_dir():
        abort(f"Shared Codex home not found: {SHARED}. Start Codex normally once first.")
    if SHARED == ROOT or SHARED in ROOT.parents:
        abort("Invalid profile root nested in shared home")
    profile = path_for(name)
    ensure_secure_directory(profile)

    # Seed likely-to-be-created shared directories so future runs under either
    # account don't create private history/memory folders.
    for entry in REQUIRED_DIRS:
        where = SHARED / entry
        if not where.exists() and not where.is_symlink():
            where.mkdir(mode=0o700)
    history = SHARED / "history.jsonl"
    if not history.exists() and not history.is_symlink():
        fd = os.open(history, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)

    # Repair profiles created by v1.0.0, which linked the daemon's runtime
    # state into the shared Codex home. Only remove links to those exact shared
    # paths; never delete real directories, sockets or unexpected symlinks.
    # The primary profile runs directly from SHARED and is not changed here.
    for entry in DAEMON_DIRS:
        dest = profile / entry
        if dest.is_symlink():
            expected = (SHARED / entry).resolve(strict=False)
            if dest.resolve(strict=False) != expected:
                abort(f"Unexpected symlink at {dest}; inspect it manually before continuing.")
            dest.unlink()
        if dest.exists():
            if not dest.is_dir():
                abort(f"Expected a directory at {dest}; inspect it manually before continuing.")
        else:
            dest.mkdir(mode=0o700)

    for entry in SHARED.iterdir():
        if entry.name in EXCLUDED:
            continue
        dest = profile / entry.name
        if dest.is_symlink():
            if dest.resolve(strict=False) == entry.resolve(strict=False):
                continue
            abort(f"Unexpected symlink in profile: {dest}. Check manually.")
        if dest.exists():
            # Do not delete profile-local files created by a prior Codex run.
            # They are not shared; flag so users can reconcile safely.
            print(f"Warning: {dest} is not shared (real file or directory already exists).", file=sys.stderr)
            continue
        dest.symlink_to(entry)
    return profile


def existing_profiles():
    if not PROFILES.is_dir():
        return []
    return sorted(p for p in PROFILES.iterdir() if p.is_dir() and not p.is_symlink())


def command_add(args):
    if args.login:
        return command_login(args)
    with lock():
        data = read_auth(SHARED / "auth.json")
        if data is None:
            abort("No existing ~/.codex/auth.json. First run `codex login` for your current account.")
        profile = path_for(args.alias)
        if profile.exists():
            abort(f"Profile '{args.alias}' already exists. Choose a new alias.")
        for other in existing_profiles():
            if (other / PRIMARY_MARKER).exists():
                abort(f"Primary Codex home already registered as '{other.name}'.")
        ensure_secure_directory(profile)
        marker = profile / PRIMARY_MARKER
        marker.write_text(str(SHARED) + "\n", encoding="utf-8")
        marker.chmod(0o600)
        label, _ = identity(data)
    print(f"Registered primary account {args.alias}: {label}")
    print("Uses your ORIGINAL ~/.codex/auth.json directly: no duplicate refresh tokens.")
    return 0


def command_login(args):
    binary = shutil.which("codex")
    if not binary:
        abort("Codex CLI not found on PATH")
    with lock():
        profile_path = path_for(args.alias)
        if (profile_path / PRIMARY_MARKER).exists():
            abort("Primary profile uses your original ~/.codex. Re-login with `codex login` directly.")
        profile = prepare_profile(args.alias)
        if (profile / "auth.json").exists() and not args.replace:
            abort(f"'{args.alias}' already has credentials. Use --replace to reauthenticate intentionally.")
        prior = read_auth(profile / "auth.json")
        if prior is not None:
            # Logging in with existing credentials can revoke those credentials.
            # Remove only this profile's credentials before running login.
            (profile / "auth.json").unlink()
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(profile)
        command = [binary, "login"]
        if args.device_auth:
            command.append("--device-auth")
        print(f"Starting isolated Codex login for '{args.alias}'...")
        try:
            rc = subprocess.call(command, env=environment)
        except BaseException:
            if prior is not None and not (profile / "auth.json").exists():
                write_auth(profile / "auth.json", prior)
            raise
        auth = read_auth(profile / "auth.json")
        if rc != 0 or auth is None:
            if prior is not None and auth is None:
                write_auth(profile / "auth.json", prior)
            abort(f"Codex login failed or produced no auth.json (exit {rc})")
        label, account_id = identity(auth)
        for other in existing_profiles():
            if other != profile:
                _, other_id = identity(read_auth(other / "auth.json"))
                if account_id and other_id == account_id:
                    print(f"Warning: same ChatGPT account as profile '{other.name}'.", file=sys.stderr)
    print(f"Authenticated {args.alias}: {label}")
    return 0


def command_list(args):
    profiles = existing_profiles()
    if not profiles:
        print("No profiles. First: shiftline add --alias main")
        print("Then: shiftline add --login --alias second --device-auth")
        return 0
    for profile in profiles:
        if (profile / PRIMARY_MARKER).exists():
            label, _ = identity(read_auth(SHARED / "auth.json"))
            print(f"{profile.name:12s} {label} [original shared home]")
        else:
            label, _ = identity(read_auth(profile / "auth.json"))
            print(f"{profile.name:12s} {label}")
    print(f"Shared data: {SHARED}")
    return 0


def command_doctor(args):
    """Read-only inspection: list Codex processes and Linux writer locks."""
    print(f"Shared Codex home: {SHARED}")
    print(f"Codex profiles root: {ROOT}")
    print("\nCodex-related running processes:")
    try:
        result = subprocess.run(["ps", "-eo", "pid,ppid,stat,etime,args"],
                                capture_output=True, text=True, check=True)
        lines = result.stdout.splitlines()
        matches = [x for x in lines[1:] if
                   re.search(r"(?:^|[/\s])codex(?:\s|$)|app-server", x, re.IGNORECASE)
                   and "shiftline.py" not in x]
        print(lines[0] if lines else "PID PPID STAT ELAPSED COMMAND")
        for line in matches:
            print(line)
        if not matches:
            print("(no obvious Codex processes)")
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Could not inspect processes: {exc}")
    print("\nActive OS locks in thread-writer-locks:")
    try:
        result = subprocess.run(["lslocks", "-o", "PID,COMMAND,PATH"],
                                capture_output=True, text=True, check=True)
        matches = [x for x in result.stdout.splitlines()
                   if "thread-writer-locks" in x]
        if matches:
            for line in matches:
                print(line)
            print("\nIf a PID is listed, verify its work is finished before stopping it.")
        else:
            print("(none reported by lslocks)")
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Could not inspect OS locks: {exc}")
    print("\nThis command is read-only; it does not terminate processes or remove locks.")
    return 0


def get_lock_owners():
    """Return (pid, path) pairs for live Linux advisory locks under shared home.

    Use `lslocks`, not presence of *.lock files: empty lock files are benign.
    Failure to inspect is fatal, rather than assuming no writers exist.
    """
    if not shutil.which("lslocks"):
        abort("lslocks is required for safe switching (Ubuntu: sudo apt install util-linux)")
    result = subprocess.run(["lslocks", "-n", "-o", "PID,PATH"],
                            capture_output=True, text=True, timeout=12)
    if result.returncode != 0:
        abort(f"Cannot inspect writer locks: {result.stderr.strip() or 'lslocks failed'}")
    lockdir = SHARED / "thread-writer-locks"
    found = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        pid, path = parts
        if not pid.isdigit():
            continue
        # Only act on the exact shared lock directory, not similarly named paths.
        if Path(path).parent == lockdir:
            found.append((int(pid), path))
    return found


def proc_cmdline(pid):
    try:
        # Linux cmdline is nul-separated and preserves argv boundaries.
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except (OSError, PermissionError):
        return ""


def owning_codex_home(pid):
    """Resolve the managed daemon's CODEX_HOME; no guessing on read errors."""
    try:
        env = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        abort(f"Cannot read environment for daemon PID {pid}; stop it manually and retry")
    items = env.split(b"\0")
    keys = [x.partition(b"=")[2] for x in items if x.startswith(b"CODEX_HOME=")]
    raw = os.fsdecode(keys[-1]) if keys else str(HOME / ".codex")
    home = Path(raw).expanduser().resolve()
    known = {SHARED, *(p.resolve() for p in existing_profiles())}
    if home not in known:
        abort(f"Daemon PID {pid} uses unexpected CODEX_HOME={home}; refusing to stop it")
    return home


def managed_daemon_owner(pid):
    """Recognize only the managed app-server process, never CLI/TUI/updaters."""
    cmd = proc_cmdline(pid)
    # Be conservative: option matching is deliberately strict.
    if re.search(r"(?:^|\s)app-server(?:\s|$)", cmd) and "--managed-daemon" in cmd:
        return True
    return False


def release_daemon_locks(binary, *, confirmed):
    """Stop a lock-owning managed daemon after approval; never kill or unlink."""
    owners = get_lock_owners()
    if not owners:
        print("Writer locks: clear")
        return
    grouped = {}
    for pid, path in owners:
        grouped.setdefault(pid, []).append(path)
    for pid, paths in grouped.items():
        cmd = proc_cmdline(pid)
        if not managed_daemon_owner(pid):
            abort(f"Conversation writer lock held by PID {pid}: {cmd or '(unknown process)'}\n"
                  "Exit that Codex CLI/app first (including tmux sessions), then run switch again.\n"
                  "No process was stopped and no lock was deleted.")
    homes = set()
    for pid in grouped:
        homes.add(owning_codex_home(pid))
    print("Managed Codex daemon holds conversation lock(s):")
    for pid, paths in grouped.items():
        print(f"  PID {pid}: {len(paths)} conversation(s)")
    if not confirmed:
        if not sys.stdin.isatty():
            abort("Cannot ask permission without a terminal. If all tasks are finished, rerun with --yes")
        reply = input("Have all Codex tasks finished? Stop the managed daemon(s) to release locks? [y/N] ")
        if reply.strip().lower() not in {"y", "yes"}:
            abort("Switch cancelled; no daemon was stopped")
    for home in sorted(homes):
        env = os.environ.copy()
        env["CODEX_HOME"] = str(home)
        print(f"Stopping managed Codex daemon for {home} ...", flush=True)
        result = subprocess.run([binary, "app-server", "daemon", "stop"],
                                env=env, capture_output=True, text=True, timeout=25)
        if result.returncode != 0:
            abort(f"Daemon stop failed ({result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
    # Verify kernel locks actually released; do not treat status:stopped as proof.
    deadline = time.monotonic() + 8
    while True:
        remaining = get_lock_owners()
        if not remaining:
            print("Writer locks: released")
            return
        if time.monotonic() > deadline:
            abort("A writer lock remains after daemon stop. Run `shiftline doctor` and investigate; "
                  "no process was force-killed")
        time.sleep(0.25)


def command_switch(args):
    """Select a profile, safely release daemon locks, and open the resume picker."""
    with lock():
        registered = path_for(args.alias)
        if not registered.is_dir():
            abort(f"Unknown profile: '{args.alias}'. Use `shiftline list`.")
        primary = (registered / PRIMARY_MARKER).exists()
        profile = SHARED if primary else prepare_profile(args.alias)
        if not (profile / "auth.json").is_file():
            abort(f"Unauthenticated profile: '{args.alias}'. Use `shiftline list`.")
        # Prevent a profile-local writer-lock directory from bypassing shared locks.
        if profile != SHARED:
            writer_path = profile / "thread-writer-locks"
            if not writer_path.is_symlink() or writer_path.resolve() != (SHARED / "thread-writer-locks").resolve():
                abort(f"Profile has private or unexpected writer locks at {writer_path}. "
                      "Do not switch until this is reconciled; no files were changed.")
    binary = shutil.which("codex")
    if not binary:
        abort("Codex CLI not found on PATH")
    # Everything after `--` belongs to Codex, not shiftline. Pass these root-level
    # flags before `resume` so they work across versions that only accept
    # --sandbox/--ask-for-approval at the root of the CLI.
    codex_cmd = [binary, "--no-daemon", *getattr(args, "codex_args", []), "resume"]
    # `codex resume` (without --last) opens Codex's built-in session picker.
    # Limit to the current directory by default; --all shows other projects.
    if getattr(args, "all", False):
        codex_cmd.append("--all")
    if getattr(args, "last", False):
        codex_cmd.append("--last")
    print(f"Switch target: {args.alias} (shared conversation history)")
    if args.dry_run:
        owners = get_lock_owners()
        if owners:
            for pid, path in owners:
                print(f"Lock: PID {pid}: {path}  daemon={managed_daemon_owner(pid)}")
        else:
            print("Writer locks: clear")
        print(f"Would launch: CODEX_HOME={shlex.quote(str(profile))} {shlex.join(codex_cmd)}")
        return 0
    release_daemon_locks(binary, confirmed=args.yes)
    env = os.environ.copy()
    env["CODEX_HOME"] = str(profile)
    print(f"Opening sessions for '{args.alias}' from {os.getcwd()} ...", flush=True)
    os.execvpe(binary, codex_cmd, env)
    return 0


def command_run(args):
    with lock():
        registered = path_for(args.alias)
        if not registered.is_dir():
            abort(f"Unknown profile: '{args.alias}'. Use `shiftline list`.")
        if (registered / PRIMARY_MARKER).exists():
            profile = SHARED
        else:
            profile = registered
            prepare_profile(args.alias)
        if not (profile / "auth.json").exists():
            abort(f"Unauthenticated profile: '{args.alias}'. Use `shiftline list`.")
    binary = shutil.which("codex")
    if not binary:
        abort("Codex CLI not found on PATH")
    codex_args = list(args.args)
    if codex_args and codex_args[0] == "--":
        codex_args.pop(0)
    if args.command == "resume":
        # Root-level flag MUST precede the resume subcommand.
        # An embedded CLI avoids the managed daemon retaining the thread lock
        # across session changes. An independent live TUI can still hold it.
        codex_args = ["--no-daemon", "resume", "--last", *codex_args]
    env = os.environ.copy()
    env["CODEX_HOME"] = str(profile)
    print(f"Launching Codex with profile '{args.alias}' (shared sessions under {SHARED})", flush=True)
    os.execvpe(binary, [binary, *codex_args], env)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="shiftline",
        description="Standalone, dependency-free Codex profile runner (manual selection only)",
    )
    parser.add_argument("--version", action="version", version=f"shiftline {VERSION}")
    subs = parser.add_subparsers(dest="command", required=True)
    add = subs.add_parser("add", help="Save current login, or log into an isolated new profile")
    add.add_argument("--alias", required=True)
    add.add_argument("--login", action="store_true")
    add.add_argument("--device-auth", action="store_true")
    add.add_argument("--replace", action="store_true", help="Allow reauthentication of an existing named profile")
    add.set_defaults(func=command_add)
    log = subs.add_parser("login", help="Authenticate a named profile without disturbing other accounts")
    log.add_argument("alias")
    log.add_argument("--device-auth", action="store_true")
    log.add_argument("--replace", action="store_true")
    log.set_defaults(func=command_login)
    subs.add_parser("list", help="List locally authenticated accounts").set_defaults(func=command_list)
    subs.add_parser("doctor", help="Read-only listing of Codex processes and session writer locks").set_defaults(func=command_doctor)
    sw = subs.add_parser("switch", help="Safe handoff: release daemon locks and pick a saved Codex session")
    sw.add_argument("alias", help="Registered account name (e.g. main / second)")
    sw.add_argument("--all", action="store_true",
                    help="Show sessions from all working directories in Codex picker")
    sw.add_argument("--last", action="store_true",
                    help="Skip the picker and resume the latest session (legacy behavior)")
    sw.add_argument("--yes", "-y", action="store_true",
                    help="Confirm all tasks finished and permit stopping managed daemon without prompting")
    sw.add_argument("--dry-run", action="store_true", help="Inspect what switch would do, without stopping or launching")
    sw.epilog = ("Pass Codex root flags after --, e.g. "
                 "shiftline switch main -- --sandbox danger-full-access "
                 "--ask-for-approval on-request")
    sw.set_defaults(func=command_switch)
    for command in ("run", "resume"):
        item = subs.add_parser(command, help="Run Codex under an account; resume defaults to --last")
        item.add_argument("alias")
        item.add_argument("args", nargs=argparse.REMAINDER)
        item.set_defaults(func=command_run)
    # Parse shiftline switch options independently of passthrough Codex arguments.
    # A REMAINDER positional would swallow `--yes` / `--dry-run` when those
    # options follow the alias, breaking 1.0.3 compatibility.
    argv = list(sys.argv[1:] if argv is None else argv)
    codex_args = []
    if argv and argv[0] == "switch" and "--" in argv:
        marker = argv.index("--")
        codex_args = argv[marker + 1:]
        argv = argv[:marker]
    args = parser.parse_args(argv)
    if args.command == "switch":
        args.codex_args = codex_args
    if args.command == "add" and not args.login and (args.device_auth or args.replace):
        parser.error("--device-auth and --replace require --login")
    try:
        return args.func(args)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"shiftline: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())