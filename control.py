#!/usr/bin/env python3
"""Small service controller for systemd and other Linux init environments."""
import fcntl
import json
import os
from pathlib import Path
import pwd
import signal
import subprocess
import sys
import time

APP = Path(__file__).resolve().parent
DATA = Path('/var/lib/netzmonitor')


def systemd():
    return Path('/run/systemd/system').is_dir() and Path('/etc/systemd/system/netzmonitor.service').is_file()


def process():
    path = DATA / 'service.lock'
    if not path.exists():
        return None
    with open(path, 'r+') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return None
        except BlockingIOError:
            handle.seek(0)
            try:
                pid = int(handle.read())
                command = Path('/proc/%s/cmdline' % pid).read_bytes().replace(b'\x00', b' ').decode()
                if str(APP / 'run.py') in command and 'serve' in command:
                    return pid
            except (ValueError, OSError):
                return None
    return None


def child_user():
    user = pwd.getpwnam('netzmonitor')
    os.initgroups(user.pw_name, user.pw_gid)
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)
    os.umask(0o027)


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if action not in ('start', 'stop', 'restart', 'status', 'doctor', 'password', 'backup', 'uninstall'):
        raise SystemExit('Aufruf: netzmonitor start|stop|restart|status|doctor|password|backup|uninstall [Optionen]')
    if action != 'status' and os.geteuid() != 0:
        raise SystemExit('Bitte mit sudo oder als root ausführen.')
    if action == 'uninstall':
        return subprocess.call([sys.executable, str(APP / 'uninstall.py')] + sys.argv[2:])
    if action in ('doctor', 'password', 'backup'):
        command = [sys.executable, str(APP / 'run.py'), action, '--data-dir', str(DATA)]
        if action == 'password' and len(sys.argv) > 2:
            command += ['--username', sys.argv[2]]
        if action == 'backup':
            if len(sys.argv) < 3:
                raise SystemExit('Aufruf: sudo netzmonitor backup /absoluter/pfad/sicherung.sqlite3')
            command += ['--output', sys.argv[2]]
        if action == 'doctor':
            if systemd():
                # Same CAP_NET_RAW permission as the installed monitoring service.
                return subprocess.call(['systemd-run', '--quiet', '--wait', '--pipe', '--collect',
                    '-p', 'User=netzmonitor', '-p', 'AmbientCapabilities=CAP_NET_RAW',
                    '-p', 'CapabilityBoundingSet=CAP_NET_RAW'] + command)
            return subprocess.call(command, preexec_fn=child_user)
        if action == 'password':
            return subprocess.call(command, preexec_fn=child_user)
        return subprocess.call(command)
    if systemd():
        return subprocess.call(['systemctl', action, 'netzmonitor'])
    pid = process()
    if action == 'status':
        print('Qisutu Monitoring läuft (PID %s).' % pid if pid else 'Qisutu Monitoring ist beendet.')
        return 0 if pid else 3
    if action in ('stop', 'restart') and pid:
        os.kill(pid, signal.SIGTERM)
        for _ in range(180):
            if not process():
                break
            time.sleep(0.5)
        else:
            raise SystemExit('Dienst reagiert nicht. Bitte das Protokoll prüfen; kein erzwungenes Beenden ausgeführt.')
        print('Qisutu Monitoring beendet.')
    if action == 'stop':
        return 0
    if action == 'start' and pid:
        print('Qisutu Monitoring läuft bereits.')
        return 0
    log = open(DATA / 'startup.log', 'ab', buffering=0)
    child = subprocess.Popen([sys.executable, str(APP / 'run.py'), 'serve', '--data-dir', str(DATA)],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True, preexec_fn=child_user)
    log.close()
    for _ in range(30):
        if child.poll() is not None:
            raise SystemExit('Dienststart fehlgeschlagen. Details: /var/lib/netzmonitor/startup.log')
        if process():
            print('Qisutu Monitoring gestartet (PID %s).' % child.pid)
            return 0
        time.sleep(0.2)
    raise SystemExit('Dienststart nicht bestätigt. Bitte das Protokoll prüfen.')


if __name__ == '__main__':
    try:
        sys.exit(main() or 0)
    except (OSError, ValueError) as exc:
        raise SystemExit('Fehler: ' + str(exc))
