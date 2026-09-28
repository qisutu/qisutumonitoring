"""Exercise removal on isolated roots; never stop real services or remove users."""
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import uninstall


class UninstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'stage'
        self.root.mkdir()

    def file(self, path, contents='owned'):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
        return target

    def test_removes_complete_installation_and_registrations_only(self):
        paths = ('opt/netzmonitor/run.py', 'opt/netzmonitor/vendor/code.py',
                 'var/lib/netzmonitor/monitoring.sqlite3', 'var/lib/netzmonitor/server.key',
                 'var/lib/netzmonitor/config.json', 'var/lib/netzmonitor/startup.log',
                 'usr/local/bin/netzmonitor', 'etc/systemd/system/netzmonitor.service',
                 'etc/systemd/system/netzmonitor.service.d/override.conf',
                 'etc/init.d/netzmonitor', 'etc/conf.d/netzmonitor', 'etc/default/netzmonitor')
        for path in paths:
            self.file(path)
        for path in ('etc/rc2.d/S90netzmonitor', 'etc/rc.d/rc0.d/K10netzmonitor',
                     'etc/runlevels/default/netzmonitor',
                     'etc/systemd/system/multi-user.target.wants/netzmonitor.service'):
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to('/etc/init.d/netzmonitor')
        keep = self.file('etc/rc2.d/S90othernetzmonitor', 'unrelated')
        other = self.file('opt/other-app/keep', 'keep')
        with patch.object(uninstall, 'stop_service') as stop, patch.object(uninstall, 'remove_account') as account:
            uninstall.uninstall(self.root, staged=True)
            uninstall.uninstall(self.root, staged=True)
            stop.assert_not_called(); account.assert_not_called()
        for path in paths:
            self.assertFalse((self.root / path).exists(), path)
        self.assertEqual(keep.read_text(), 'unrelated')
        self.assertEqual(other.read_text(), 'keep')
        self.assertFalse(list(self.root.glob('etc/**/*.service')))
        self.assertFalse(list(self.root.glob('etc/**/S90netzmonitor')))

    def test_child_and_top_level_symlinks_do_not_delete_external_data(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir(); (outside / 'keep').write_text('safe')
        self.file('opt/netzmonitor/run.py')
        (self.root / 'opt/netzmonitor/external').symlink_to(outside, target_is_directory=True)
        (self.root / 'var/lib').mkdir(parents=True)
        (self.root / 'var/lib/netzmonitor').symlink_to(outside, target_is_directory=True)
        uninstall.uninstall(self.root, staged=True)
        self.assertEqual((outside / 'keep').read_text(), 'safe')
        self.assertFalse((self.root / 'var/lib/netzmonitor').is_symlink())

    def test_parent_symlink_escape_aborts_before_any_deletion(self):
        outside = Path(self.temp.name) / 'outside'; outside.mkdir()
        (self.root / 'etc').symlink_to(outside, target_is_directory=True)
        keep = self.file('opt/netzmonitor/run.py', 'keep')
        with self.assertRaises(ValueError):
            uninstall.uninstall(self.root, staged=True)
        self.assertEqual(keep.read_text(), 'keep')

    def test_staging_root_and_confirmation(self):
        for invalid in ('/', 'relative', str(self.root / '..')):
            with self.assertRaises(ValueError):
                uninstall.destination(invalid)
        keep = self.file('var/lib/netzmonitor/monitoring.sqlite3', 'data')
        with patch('builtins.input', return_value='NEIN'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(uninstall.main(['--destdir', str(self.root)]), 1)
        self.assertEqual(keep.read_text(), 'data')

    def test_failed_stop_keeps_program_data_and_user(self):
        keep = self.file('var/lib/netzmonitor/monitoring.sqlite3', 'data')
        with patch.object(uninstall, 'account_removal', return_value=None), \
             patch.object(uninstall, 'stop_service', side_effect=RuntimeError('stop failed')), \
             patch.object(uninstall, 'remove_account') as account:
            with self.assertRaisesRegex(RuntimeError, 'stop failed'):
                uninstall.uninstall(self.root)
            account.assert_not_called()
        self.assertEqual(keep.read_text(), 'data')

    def test_service_stop_and_reload_order_before_removal(self):
        keep = self.file('var/lib/netzmonitor/monitoring.sqlite3', 'data')
        events = []
        def stop():
            self.assertTrue(keep.exists()); events.append('stop'); return True
        def account(plan):
            self.assertTrue(keep.exists()); events.append('account')
        def reload(args):
            self.assertFalse(keep.exists()); events.append(args)
        with patch.object(uninstall, 'account_removal', return_value='plan'), \
             patch.object(uninstall, 'stop_service', side_effect=stop), \
             patch.object(uninstall, 'remove_account', side_effect=account), \
             patch.object(uninstall, 'command', side_effect=reload):
            uninstall.uninstall(self.root)
        self.assertEqual(events, ['stop', 'account', ['systemctl', 'daemon-reload']])

    def test_foreign_service_account_is_rejected(self):
        foreign = SimpleNamespace(pw_uid=1000, pw_dir='/home/other', pw_shell='/bin/bash')
        with patch.object(uninstall.pwd, 'getpwnam', return_value=foreign):
            with self.assertRaisesRegex(RuntimeError, 'kein passendes Dienstkonto'):
                uninstall.account_removal()

    def test_group_with_other_members_is_rejected(self):
        group = SimpleNamespace(gr_gid=900, gr_mem=['other-user'])
        with patch.object(uninstall.pwd, 'getpwnam', side_effect=KeyError), \
             patch.object(uninstall.grp, 'getgrnam', return_value=group):
            with self.assertRaisesRegex(RuntimeError, 'anderweitig'):
                uninstall.account_removal()

    def test_standalone_shell_works_from_path_with_spaces(self):
        keep = self.file('var/lib/netzmonitor/monitoring.sqlite3', 'data')
        source = Path(self.temp.name) / 'source with spaces'; source.mkdir()
        for name in ('uninstall.sh', 'uninstall.py'):
            (source / name).write_bytes((ROOT / name).read_bytes())
        result = subprocess.run(['sh', str(source / 'uninstall.sh'), '--destdir', str(self.root), '--yes'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(keep.exists())


if __name__ == '__main__':
    unittest.main()
