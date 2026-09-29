"""Exercise installer dependency decisions without touching host packages/services."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InstallerPackagesTest(unittest.TestCase):
    def run_installer(self, clients=(), missing=(), conflict='', update_fail=False,
                      args=(), source=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binaries = root / 'bin'
            binaries.mkdir()
            log = root / 'apt.jsonl'
            server = root / 'existing-mariadb-server'
            server.write_text('installed and running')

            def executable(name, content):
                path = binaries / name
                path.write_text(content)
                path.chmod(0o755)

            (binaries / 'dirname').symlink_to(shutil.which('dirname'))
            executable('uname', '#!/bin/sh\necho Linux\n')
            executable('id', '#!/bin/sh\necho 0\n')
            executable('sha256sum', '#!/bin/sh\nexit 0\n')
            for name in ('python3', 'ping', 'openssl', 'ssh', 'ssh-keyscan',
                         'snmpwalk', 'snmpbulkwalk', *clients):
                if name not in missing:
                    executable(name, '#!/bin/sh\nexit 0\n')
            executable('apt-get', '#!' + sys.executable + '\n' + '''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['MOCK_LOG'], 'a') as stream:
    stream.write(json.dumps(args) + '\\n')
if args[0] == 'update':
    sys.exit(100 if os.environ['MOCK_UPDATE_FAIL'] == '1' else 0)
conflict = os.environ['MOCK_CONFLICT']
if 'default-mysql-client' in args or (conflict and conflict in args):
    if '--no-remove' in args:
        print('E: Packages need to be removed but remove is disabled.', file=sys.stderr)
        sys.exit(100)
    Path(os.environ['MOCK_SERVER']).unlink(missing_ok=True)
for package, commands in {'iputils-ping': ['ping'], 'openssh-client': ['ssh', 'ssh-keyscan'],
                          'snmp': ['snmpwalk', 'snmpbulkwalk'],
                          'postgresql-client': ['psql'], 'mariadb-client': ['mariadb']}.items():
    if package in args:
        for command in commands:
            target = Path(os.environ['PATH']) / command
            target.write_text('#!/bin/sh\\nexit 0\\n')
            target.chmod(0o755)
''')
            # Execute the real dependency phase; stop before users/files/services.
            source = source if source is not None else (ROOT / 'install.sh').read_text()
            prefix, _ = source.split('APP="$DESTDIR/opt/netzmonitor"', 1)
            script = root / 'install.sh'
            script.write_text(prefix)
            env = dict(os.environ, PATH=str(binaries), MOCK_LOG=str(log),
                       MOCK_SERVER=str(server), MOCK_CONFLICT=conflict,
                       MOCK_UPDATE_FAIL='1' if update_fail else '0')
            result = subprocess.run(['/bin/sh', str(script), *args], env=env,
                                    capture_output=True, text=True, timeout=10)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls, server.exists()

    def installs(self, calls):
        return [call for call in calls if call[0] == 'install']

    def test_existing_mariadb_missing_postgresql_preserves_server(self):
        result, calls, server = self.run_installer(clients=('mariadb',))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(server)
        self.assertEqual(len(self.installs(calls)), 1)
        self.assertIn('postgresql-client', self.installs(calls)[0])
        self.assertNotIn('mariadb-client', self.installs(calls)[0])
        self.assertNotIn('default-mysql-client', self.installs(calls)[0])

    def test_existing_mysql_is_also_reused(self):
        result, calls, server = self.run_installer(clients=('mysql',))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(server)
        self.assertEqual(len(self.installs(calls)), 1)
        self.assertIn('postgresql-client', self.installs(calls)[0])

    def test_complete_clients_do_not_invoke_package_manager(self):
        for client in ('mysql', 'mariadb'):
            with self.subTest(client=client):
                result, calls, server = self.run_installer(clients=('psql', client))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, [])
                self.assertTrue(server)

    def test_only_missing_mysql_client_is_installed(self):
        result, calls, server = self.run_installer(clients=('psql',))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(server)
        self.assertEqual(len(self.installs(calls)), 1)
        self.assertIn('mariadb-client', self.installs(calls)[0])
        self.assertNotIn('postgresql-client', self.installs(calls)[0])

    def test_conflicting_optional_client_is_skipped_without_unsafe_retry(self):
        for package in ('postgresql-client', 'mariadb-client'):
            with self.subTest(package=package):
                result, calls, server = self.run_installer(conflict=package)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(server)
                self.assertIn('konnte nicht sicher installiert werden', result.stderr)
                installs = self.installs(calls)
                self.assertEqual(len(installs), 2)
                self.assertEqual(sum(package in call for call in installs), 1)
                for call in installs:
                    self.assertIn('--no-remove', call)
                    self.assertIn('--no-upgrade', call)

    def test_all_apt_dependency_transactions_refuse_removals(self):
        result, calls, server = self.run_installer(missing=('ping', 'ssh', 'snmpwalk'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(server)
        self.assertEqual(len(self.installs(calls)), 5)
        for call in self.installs(calls):
            self.assertIn('--no-remove', call)

    def test_conflicting_required_dependency_stops_before_installing_app(self):
        result, calls, server = self.run_installer(missing=('ping',), conflict='iputils-ping')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(server)
        self.assertEqual(len(self.installs(calls)), 1)

    def test_skip_packages_and_staging_never_invoke_apt(self):
        for args in (('--skip-packages',), ('--destdir', '/staging-only')):
            with self.subTest(args=args):
                result, calls, server = self.run_installer(args=args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, [])
                self.assertTrue(server)

    def test_repository_failure_does_not_attempt_install(self):
        result, calls, server = self.run_installer(update_fail=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(server)
        self.assertEqual(self.installs(calls), [])
        self.assertEqual(result.stderr.count('konnte nicht sicher installiert werden'), 2)


if __name__ == '__main__':
    unittest.main()
