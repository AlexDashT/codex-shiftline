# Codex Shiftline

**One command to hand a local Codex CLI conversation between separately authenticated profiles.**

![CI](https://img.shields.io/badge/Python-3.9%2B-blue) ![License](https://img.shields.io/badge/License-MIT-green) ![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Ubuntu-informational)

Shiftline is a small, zero-third-party-dependency Python tool for managing authenticated Codex CLI profiles on Linux. It keeps each profile's `auth.json` and daemon runtime separate while reusing the original `~/.codex` sessions, history, configuration, rules, skills and memories. Its `switch` command inspects Linux writer locks, optionally stops a lock-holding *managed* daemon with your approval, then opens Codex's interactive session picker, so you choose which conversation to continue.

**Not affiliated with or endorsed by OpenAI.** Built as an independent rewrite inspired by [PavloPopravkin/codex-swap](https://github.com/PavloPopravkin/codex-swap). See [NOTICE.md](NOTICE.md) for attribution and distinctions.

> **Scope:** manual profile selection and session handoff. No automatic quota routing, limit monitoring or usage-limit circumvention. Observe your Codex plan's usage rules.

## Quick start (Ubuntu)

Requirements: Python **3.9+**, `codex` CLI installed and accessible, Linux utilities `lslocks` and `ps` (`util-linux` and `procps`). No `uv`, `pip`, `pipx`, container or background service needed.

```bash
# Clone after publishing the repository:
git clone https://github.com/AlexDashT/codex-shiftline.git
cd codex-shiftline
./install.sh
export PATH="$HOME/.local/bin:$PATH"

# First time only: register the account already logged into ~/.codex
shiftline add --alias main

# First time only: sign into a separate profile
shiftline add --login --alias second --device-auth
shiftline list
```

For device authorization, enable the relevant Codex device-login capability in your account if required. Never share login tokens with another user. Do not run the installer as root.

**Normal switching:** Finish work and fully exit the previous Codex TUI (`/exit`, including inside `tmux`). Then, from the same working directory:

```bash
shiftline switch second
shiftline switch main

# Browse conversations from every working directory
shiftline switch main --all

# Optional legacy shortcut: resume latest without picker
shiftline switch main --last
```

Shiftline will:

1. Resolve and authenticate the selected profile.
2. Ensure additional profiles share the original writer-lock directory.
3. Inspect **live** Linux kernel locks, not just the existence of `.lock` files.
4. If an idle **managed** Codex daemon owns locks, ask your permission to stop it using `codex app-server daemon stop`.
5. Confirm the locks are gone; otherwise refuse to launch.
6. Start `codex --no-daemon resume` in the current working directory, using that profile. Codex shows its session picker; select a conversation with the arrow keys and Enter.

By default the picker shows conversations for the current working directory. Use `--all` to include other directories, or `--last` to skip the picker.

The CLI cannot take over a still-running conversation. **Exit the previous TUI first**. Daemon shutdown can interrupt background work; never approve it unless work has stopped.

### Preserve your preferred Codex flags

Forward flags to the root Codex command after `--`:

```bash
shiftline switch second -- \
  --sandbox danger-full-access \
  --ask-for-approval on-request

# Inspect without stopping or launching anything
shiftline switch main --dry-run -- \
  --sandbox danger-full-access \
  --ask-for-approval on-request
```

`danger-full-access` permits broad filesystem and command access on your host. `on-request` controls approvals; it does **not** restore filesystem isolation. Consider `workspace-write` where practical.

Optional shell shortcuts (add to `~/.zshrc` or `~/.bashrc`):

```bash
cmain() { shiftline switch main -- --sandbox danger-full-access --ask-for-approval on-request; }
csecond() { shiftline switch second -- --sandbox danger-full-access --ask-for-approval on-request; }
```

You can pass `--yes` before the `--` separator *after you personally confirm no background work is running*. It suppresses only the confirmation prompt, **not** the session lock checks.

## All commands

| Command | Description |
| --- | --- |
| `shiftline add --alias main` | Register the login in the original `~/.codex` home |
| `shiftline add --login --alias alt --device-auth` | Create and authenticate an additional isolated profile |
| `shiftline login alt --device-auth --replace` | Reauthenticate a named profile |
| `shiftline list` | List configured logins (reads identity from local token, no network) |
| `shiftline switch alt` | Safe daemon check + native session picker |
| `shiftline switch alt --all` | Show sessions across all project directories |
| `shiftline switch alt --last` | Skip picker and resume the most recent session |
| `shiftline switch alt --dry-run` | Show intended actions without changing state |
| `shiftline switch alt --yes` | Suppress daemon-stop confirmation, only after verifying tasks finished |
| `shiftline resume alt` | Resume with no daemon-stop check |
| `shiftline run alt -- exec 'prompt'` | Run a Codex command under a profile |
| `shiftline doctor` | Read-only process and lock diagnostics |

## Upgrade from the earlier standalone cxswap scripts

**Existing profiles are preserved automatically.** If `~/.codex-profiles-lite/` exists and `~/.codex-shiftline/` does not, Shiftline reuses the **existing** profile root. It leaves the old `cxswap` binary untouched; avoid using both launchers at the same time. It does not move or rewrite existing auth files, sessions or history.

Fresh installations store profiles under `~/.codex-shiftline/` and preserve your normal primary `~/.codex/` data. To override the location:

```bash
export CODEX_PROFILES_HOME="$HOME/.codex-profiles-lite"
```

## Security model

- Per-profile `auth.json` and daemon state remain isolated. Protect the entire profile home (`0700`) and credentials (`0600`).
- Never commit `~/.codex`, profile directories, JWTs, authentication JSON or Codex logs to GitHub. No credentials are packaged in this repository.
- The main `~/.codex` home is *shared writable state*, not a security boundary. Do not run two agents against the same conversation concurrently.
- The `switch` operation uses `lslocks` to check OS locks; it refuses to forcibly kill arbitrary Codex processes or remove locks. A lock-free snapshot cannot guarantee that another client will not immediately reconnect.
- It can stop an identified managed daemon **only** after approval (`--yes` is explicit approval). Checking that daemon-managed work is finished is your responsibility.
- Local JWT claims are used only for optional account labels; they are not verified identity assertions. Only Codex authenticates with OpenAI.
- Behavior depends on Codex's internal storage and daemon conventions, which may change. Cross-account conversation reuse is **not guaranteed** by OpenAI.
- `--no-daemon` affects the launched CLI. Other Codex apps or integrations may independently start daemons.

See [SECURITY.md](SECURITY.md) to report a vulnerability.

## Troubleshooting

**Conversation open in another app / read-only:** Run `shiftline doctor`, fully exit the other Codex TUI, and retry. If only a managed daemon owns a writer lock, `switch` can ask to stop it. Do not delete `.lock` files or session SQLite files.

**`shiftline switch` refuses an unexpected private writer-locks directory:** Do not delete it. Inspect both paths and reconcile cautiously:

```bash
ls -ld ~/.codex/thread-writer-locks ~/.codex-profiles-lite/profiles/second/thread-writer-locks
```

**Session missing from the picker:** Run `shiftline switch main --all` to include conversations from all directories. To resume a known thread directly, use `shiftline run main -- --no-daemon resume THREAD_ID`; exit the previous Codex process first.

**Inspect current version:** `shiftline --version` and `codex --version`.

## Test

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile shiftline.py
```

The automated tests simulate locks, process calls, handoffs and resume picker flags. **Live compatibility with your Codex CLI build and real accounts must be checked separately** before publishing a release.

## License

MIT. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md). The original `codex-swap`'s MIT license and copyright notice are retained.