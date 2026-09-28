#!/usr/bin/env python3
"""Remove the installed Qisutu Monitoring application and its private data."""
import argparse
import grp
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import subprocess
import sys
import time

SERVICE = 'netzmonitor'
UNIT = SERVICE + '.service'
APP = Path('/opt/netzmonitor')
DATA = Path('/var/lib/netzmonitor')


def command(args):
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, timeout=120)
    if result.returncode:
        raise RuntimeError('%s: %s' % (' '.join(args), result.stderr.strip() or result.stdout.strip()))
    return result.stdout


def destination(value):
    if value is None:
        return Path('/')
    path = Path(value)
    if not path.is_absolute() or path.resolve() == Path('/') or path != path.resolve():
        raise ValueError('--destdir muss ein absolutes, echtes Staging-Verzeichnis sein (nicht / oder ein Symlink).')
    if not path.is_dir():
        raise ValueError('--destdir existiert nicht oder ist kein Verzeichnis.')
    return path


def installed_paths(root):
    def inside(path):
        return root / str(path).lstrip('/')
    targets = [inside(p) for p in (
        APP, DATA, '/usr/local/bin/netzmonitor', '/etc/init.d/netzmonitor',
        '/etc/systemd/system/netzmonitor.service', '/etc/systemd/system/netzmonitor.service.d',
        '/etc/default/netzmonitor', '/etc/conf.d/netzmonitor')]
    for pattern in ('etc/systemd/system/*.wants/netzmonitor.service',
                    'etc/systemd/system/*.requires/netzmonitor.service',
                    'etc/runlevels/*/netzmonitor', 'etc/rc*.d/*netzmonitor',
                    'etc/rc.d/rc*.d/*netzmonitor'):
        for path in root.glob(pattern):
            if path.name == SERVICE or path.name == UNIT or re.fullmatch(r'[SK]\d+netzmonitor', path.name):
                targets.append(path)
    # Never follow parent symlinks outside a staging tree. System directories can
    # legitimately be symlinks on Linux (for example /etc/init.d on Fedora).
    for path in targets:
        if root != Path('/') and root not in (path.parent.resolve(), *path.parent.resolve().parents):
            raise ValueError('Übergeordnetes Verzeichnis verlässt das Staging-Verzeichnis: ' + str(path.parent))
        if path.is_dir() and not path.is_symlink():
            for directory, dirs, _ in os.walk(path, followlinks=False):
                if os.path.ismount(directory):
                    raise ValueError('Vor der Deinstallation eingebundenes Dateisystem aushängen: ' + directory)
                dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
    return list(dict.fromkeys(targets))


def service_processes():
    """Match exact argv entries, never an unrelated process containing our name."""
    found = []
    for item in Path('/proc').iterdir():
        if not item.name.isdecimal() or int(item.name) == os.getpid():
            continue
        try:
            args = (item / 'cmdline').read_bytes().split(b'\0')
            if os.fsencode(APP / 'run.py') in args and b'serve' in args:
                found.append(int(item.name))
        except (FileNotFoundError, ProcessLookupError):
            pass
    return found


def stop_service():
    systemd = Path('/run/systemd/system').is_dir()
    if systemd:
        state = command(['systemctl', 'show', UNIT, '--property=LoadState', '--value']).strip()
        if state != 'not-found':
            command(['systemctl', 'stop', UNIT])
            command(['systemctl', 'reset-failed', UNIT])
            command(['systemctl', 'disable', UNIT])
    elif Path('/etc/init.d/netzmonitor').exists() and shutil.which('rc-service'):
        command(['rc-service', '--ifstarted', SERVICE, 'stop'])
    # Covers manual starts and SysV, as well as a process outside a service manager.
    for pid in service_processes():
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 90
    while service_processes():
        if time.monotonic() >= deadline:
            raise RuntimeError('Dienst läuft noch. Keine Programmdaten gelöscht; bitte Dienst beenden und erneut versuchen.')
        time.sleep(0.25)
    return systemd


def account_removal():
    """Validate the dedicated service account before making any changes."""
    try:
        user = pwd.getpwnam(SERVICE)
    except KeyError:
        user = None
    if user and (user.pw_uid == 0 or user.pw_dir != str(DATA)
                 or Path(user.pw_shell).name not in ('false', 'nologin')):
        raise RuntimeError('Das Konto netzmonitor ist kein passendes Dienstkonto. Deinstallation abgebrochen.')
    try:
        group = grp.getgrnam(SERVICE)
    except KeyError:
        group = None
    if group and (group.gr_gid == 0 or (user and group.gr_gid != user.pw_gid)
                  or set(group.gr_mem) - {SERVICE}
                  or any(p.pw_gid == group.gr_gid and p.pw_name != SERVICE for p in pwd.getpwall())):
        raise RuntimeError('Die Gruppe netzmonitor wird anderweitig verwendet. Deinstallation abgebrochen.')
    user_tool = shutil.which('userdel') or shutil.which('deluser')
    group_tool = shutil.which('groupdel') or shutil.which('delgroup')
    if (user and not user_tool) or (group and not group_tool):
        raise RuntimeError('Benutzerverwaltung fehlt; userdel/deluser und groupdel/delgroup bereitstellen.')
    return user, group, user_tool, group_tool


def remove_account(plan):
    user, group, user_tool, group_tool = plan
    if user:
        command([user_tool, SERVICE])
    if group:
        try:
            grp.getgrnam(SERVICE)
        except KeyError:  # Some distributions remove the private group with the user.
            return
        command([group_tool, SERVICE])


def remove_path(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def uninstall(root, staged=False):
    targets = installed_paths(root)
    if not staged:
        plan = account_removal()
        systemd = stop_service()
        remove_account(plan)
    # Remove service registrations before the program/data directories.
    for path in reversed(targets):
        remove_path(path)
    if not staged and systemd:
        command(['systemctl', 'daemon-reload'])
    remaining = [str(p) for p in targets if p.exists() or p.is_symlink()]
    if remaining:
        raise RuntimeError('Nicht vollständig entfernt: ' + ', '.join(remaining))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Qisutu Monitoring mit allen eigenen Daten vollständig entfernen.')
    parser.add_argument('--yes', action='store_true', help='Löschung ohne Rückfrage bestätigen')
    parser.add_argument('--destdir', help='Nur eine Staging-Installation entfernen, ohne Dienste oder Systemkonten anzufassen')
    args = parser.parse_args(argv)
    root = destination(args.destdir)
    staged = args.destdir is not None
    if not staged and (sys.platform != 'linux' or os.geteuid() != 0):
        raise ValueError('Bitte unter Linux mit sudo oder als root ausführen.')
    installed_paths(root)  # Complete path preflight, including before confirmation.
    print('Qisutu Monitoring vollständig entfernen' + (' (Staging: %s)' % root if staged else ''))
    print('Gelöscht werden Programm, Geräte, Messwerte, Agentenkonten, Sprachen, Zugangsdaten,')
    print('Freischaltung, private Schlüssel, Zertifikate, eigene Protokolle und Autostart-Einträge.')
    if not args.yes:
        try:
            confirmed = input('Unwiderruflich löschen? Zum Bestätigen JA eingeben: ').strip() == 'JA'
        except EOFError:
            confirmed = False
        if not confirmed:
            print('Abgebrochen. Es wurde nichts entfernt.')
            return 1
    uninstall(root, staged)
    print('Qisutu Monitoring vollständig deinstalliert.')
    print('Gemeinsam genutzte Betriebssystempakete, Systemjournal und extern gespeicherte Sicherungen bleiben erhalten.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        sys.exit('Deinstallation nicht abgeschlossen: ' + str(exc))
