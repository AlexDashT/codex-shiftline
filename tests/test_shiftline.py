"""Offline tests for Codex Shiftline account handoff and resume picker."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location(
    'shiftline', Path(__file__).resolve().parents[1] / 'shiftline.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.shared = self.root / '.codex'
        self.shared.mkdir()
        self.profiles = self.root / 'profiles'
        self.profiles.mkdir()
        old = (mod.SHARED, mod.ROOT, mod.PROFILES)
        mod.SHARED, mod.ROOT, mod.PROFILES = self.shared, self.root, self.profiles
        self.addCleanup(lambda: setattr(mod, 'SHARED', old[0]))
        self.addCleanup(lambda: setattr(mod, 'ROOT', old[1]))
        self.addCleanup(lambda: setattr(mod, 'PROFILES', old[2]))
        (self.shared / 'auth.json').write_text('{}')
        (self.shared / 'thread-writer-locks').mkdir()
        primary = self.profiles / 'main'
        primary.mkdir()
        (primary / mod.PRIMARY_MARKER).write_text(str(self.shared))
        second = self.profiles / 'second'
        second.mkdir()
        (second / 'auth.json').write_text('{}')
        (second / 'thread-writer-locks').symlink_to(self.shared / 'thread-writer-locks')

    def launch(self, alias='main', **flags):
        args = types.SimpleNamespace(alias=alias, dry_run=False, yes=False, **flags)
        with mock.patch.object(mod.shutil, 'which', return_value='/usr/bin/codex'), \
             mock.patch.object(mod, 'get_lock_owners', return_value=[]), \
             mock.patch.object(mod.os, 'execvpe', side_effect=RuntimeError('started')) as ex:
            with self.assertRaisesRegex(RuntimeError, 'started'):
                mod.command_switch(args)
            return ex.call_args.args

    def test_switch_opens_picker_by_default(self):
        binary, argv, env = self.launch()
        self.assertEqual(argv, ['/usr/bin/codex', '--no-daemon', 'resume'])
        self.assertEqual(env['CODEX_HOME'], str(self.shared))

    def test_second_account_uses_shared_session_picker(self):
        _, argv, env = self.launch('second')
        self.assertEqual(argv[-1], 'resume')
        self.assertEqual(env['CODEX_HOME'], str(self.profiles / 'second'))

    def test_all_shows_sessions_across_directories(self):
        _, argv, _ = self.launch(all=True)
        self.assertEqual(argv, ['/usr/bin/codex', '--no-daemon', 'resume', '--all'])

    def test_last_is_explicit_opt_in(self):
        _, argv, _ = self.launch(last=True)
        self.assertEqual(argv, ['/usr/bin/codex', '--no-daemon', 'resume', '--last'])

    def test_original_root_flags_are_forwarded(self):
        _, argv, _ = self.launch('second', codex_args=[
            '--sandbox', 'danger-full-access', '--ask-for-approval', 'on-request'])
        self.assertEqual(argv, ['/usr/bin/codex', '--no-daemon',
            '--sandbox', 'danger-full-access', '--ask-for-approval', 'on-request', 'resume'])

    def test_cli_process_lock_cannot_be_overridden(self):
        args = types.SimpleNamespace(alias='main', yes=True, dry_run=False)
        path = str(self.shared / 'thread-writer-locks' / 'current.lock')
        with mock.patch.object(mod.shutil, 'which', return_value='/usr/bin/codex'), \
             mock.patch.object(mod, 'get_lock_owners', return_value=[(123, path)]), \
             mock.patch.object(mod, 'managed_daemon_owner', return_value=False), \
             mock.patch.object(mod, 'proc_cmdline', return_value='codex resume'):
            with self.assertRaisesRegex(RuntimeError, 'Exit that Codex CLI'):
                mod.command_switch(args)

    def test_managed_daemon_requires_confirmation(self):
        args = types.SimpleNamespace(alias='main', yes=False, dry_run=False)
        path = str(self.shared / 'thread-writer-locks' / 'current.lock')
        with mock.patch.object(mod.shutil, 'which', return_value='/usr/bin/codex'), \
             mock.patch.object(mod, 'get_lock_owners', return_value=[(123, path)]), \
             mock.patch.object(mod, 'managed_daemon_owner', return_value=True), \
             mock.patch.object(mod, 'owning_codex_home', return_value=self.shared), \
             mock.patch.object(mod.sys.stdin, 'isatty', return_value=True), \
             mock.patch('builtins.input', return_value='n'), \
             mock.patch.object(mod.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'Switch cancelled'):
                mod.command_switch(args)
            run.assert_not_called()

    def test_managed_daemon_stop_releases_lock(self):
        args = types.SimpleNamespace(alias='main', yes=True, dry_run=False)
        path = str(self.shared / 'thread-writer-locks' / 'current.lock')
        lock_calls = [[(123, path)], []]
        with mock.patch.object(mod.shutil, 'which', return_value='/usr/bin/codex'), \
             mock.patch.object(mod, 'get_lock_owners', side_effect=lambda: lock_calls.pop(0) if lock_calls else []), \
             mock.patch.object(mod, 'managed_daemon_owner', return_value=True), \
             mock.patch.object(mod, 'owning_codex_home', return_value=self.shared), \
             mock.patch.object(mod.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run, \
             mock.patch.object(mod.os, 'execvpe', side_effect=RuntimeError('started')):
            with self.assertRaisesRegex(RuntimeError, 'started'):
                mod.command_switch(args)
            self.assertEqual(run.call_args.args[0], ['/usr/bin/codex', 'app-server', 'daemon', 'stop'])

    def test_private_writer_lock_dir_is_rejected(self):
        target = self.profiles / 'second' / 'thread-writer-locks'
        target.unlink()
        target.mkdir()
        with mock.patch.object(mod.shutil, 'which', return_value='/usr/bin/codex'):
            with self.assertRaisesRegex(RuntimeError, 'private or unexpected'):
                mod.command_switch(types.SimpleNamespace(alias='second', yes=False, dry_run=False))

    def test_missing_profile_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Unknown profile'):
            mod.command_switch(types.SimpleNamespace(alias='missing', yes=False, dry_run=False))

    def test_cli_parser_all_and_last(self):
        values = []
        with mock.patch.object(mod, 'command_switch', side_effect=lambda args: values.append(args) or 0):
            self.assertEqual(mod.main(['switch', 'second', '--all', '--yes', '--',
                '--sandbox', 'danger-full-access']), 0)
            self.assertEqual(mod.main(['switch', 'main', '--last']), 0)
        self.assertTrue(values[0].all)
        self.assertTrue(values[0].yes)
        self.assertEqual(values[0].codex_args, ['--sandbox', 'danger-full-access'])
        self.assertTrue(values[1].last)

    def test_lock_detection_ignores_unrelated_directories(self):
        lock = str(self.shared / 'thread-writer-locks' / 'current.lock')
        other = str(self.root / 'other' / 'thread-writer-locks' / 'foreign.lock')
        with mock.patch.object(mod.shutil, 'which', return_value='/usr/bin/lslocks'), \
             mock.patch.object(mod.subprocess, 'run', return_value=subprocess.CompletedProcess(
                 [], 0, f'123 {lock}\n456 {other}\n', '')):
            self.assertEqual(mod.get_lock_owners(), [(123, lock)])

    def test_lock_inspection_failures_are_not_ignored(self):
        with mock.patch.object(mod.shutil, 'which', return_value='/usr/bin/lslocks'), \
             mock.patch.object(mod.subprocess, 'run', return_value=subprocess.CompletedProcess(
                 [], 1, '', 'permission denied')):
            with self.assertRaisesRegex(RuntimeError, 'Cannot inspect writer locks'):
                mod.get_lock_owners()


class ProfileMigrationTests(unittest.TestCase):
    def test_existing_legacy_profile_root_is_reused(self):
        with tempfile.TemporaryDirectory() as home:
            old = Path(home) / '.codex-profiles-lite'
            old.mkdir()
            env = dict(os.environ, HOME=home)
            env.pop('CODEX_PROFILES_HOME', None)
            result = subprocess.run(['python3', '-c',
                'import runpy; print(runpy.run_path("shiftline.py", run_name="check")["ROOT"])'],
                cwd=Path(__file__).resolve().parents[1], env=env,
                capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), str(old))


if __name__ == '__main__':
    unittest.main()
