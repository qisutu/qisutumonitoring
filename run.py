#!/usr/bin/env python3
"""Qisutu Monitoring command-line entry point."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor'))
if sys.version_info < (3, 9):
    raise SystemExit('Qisutu Monitoring benötigt Python 3.9 oder neuer.')

import argparse
import asyncio
import fcntl
import getpass
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import secrets
import signal
import socket
import sqlite3
import ssl

from netzmonitor.core import Store, Engine, VERSION, probe
from netzmonitor.server import WebApp, read_config, write_config, set_password
import tornado.httpserver
from netzmonitor.agents import Agents
from netzmonitor.i18n import LANGUAGES, translate


def parser():
    p = argparse.ArgumentParser(description='Qisutu Monitoring ' + VERSION)
    p.add_argument('command', choices=['init', 'serve', 'password', 'doctor', 'backup'])
    p.add_argument('--data-dir', default='/var/lib/netzmonitor')
    p.add_argument('--bind')
    p.add_argument('--port', type=int)
    p.add_argument('--cert')
    p.add_argument('--key')
    p.add_argument('--allow-http', action='store_true', help='HTTP ausschließlich für lokale Entwicklung auf 127.0.0.1')
    p.add_argument('--password-stdin', action='store_true')
    p.add_argument('--language', choices=LANGUAGES, help='Initial interface language')
    p.add_argument('--username', default='admin', help='Agent account for password reset')
    p.add_argument('--output', help='Zieldatei für eine konsistente SQLite-Sicherung')
    return p


async def serve(args):
    directory = Path(args.data_dir)
    config = read_config(directory)
    lock = open(directory / 'service.lock', 'a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Für dieses Datenverzeichnis läuft bereits ein Qisutu Monitoring-Dienst.')
    lock.seek(0)
    lock.truncate()
    lock.write(str(os.getpid()))
    lock.flush()
    handlers = [logging.StreamHandler(), RotatingFileHandler(directory / 'netzmonitor.log', maxBytes=5_000_000, backupCount=3, encoding='utf-8')]
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', handlers=handlers)
    bind = args.bind or config.get('bind', '0.0.0.0')
    port = args.port if args.port is not None else config.get('port', 8787)
    context = None
    if args.allow_http:
        if bind != '127.0.0.1':
            raise SystemExit('Unverschlüsseltes HTTP ist nur auf 127.0.0.1 erlaubt.')
    else:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(args.cert or directory / 'server.crt', args.key or directory / 'server.key')
    store = Store(directory)
    engine = Engine(store)
    app = WebApp(directory, engine)
    server = tornado.httpserver.HTTPServer(app, ssl_options=context, max_body_size=2097152,
                                          max_header_size=16384, idle_connection_timeout=20,
                                          body_timeout=15, decompress_request=False, xheaders=False)
    server.listen(port, address=bind)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    engine.start()
    logging.info('Qisutu Monitoring %s gestartet auf %s://%s:%s', VERSION, 'https' if context else 'http', bind, port)
    try:
        await stop.wait()
    finally:
        server.stop()
        await server.close_all_connections()
        await loop.run_in_executor(None, engine.close)
        app.executor.shutdown(wait=True)
        lock.close()
        logging.info('Qisutu Monitoring beendet.')


def main():
    os.umask(0o027)
    args = parser().parse_args()
    data = Path(args.data_dir)
    if args.command == 'init':
        data.mkdir(parents=True, exist_ok=True)
        if (data / 'config.json').exists():
            print('Vorhandene Konfiguration bleibt erhalten.')
            return
        language = args.language
        if not language and sys.stdin.isatty() and not args.password_stdin:
            print('Language / Sprache:')
            for code, label in LANGUAGES.items():
                print('  ' + code + ' — ' + label)
            while language not in LANGUAGES:
                language = input('Language / Sprache [de]: ').strip() or 'de'
        language = language or 'de'
        password = sys.stdin.readline().rstrip('\r\n') if args.password_stdin else secrets.token_urlsafe(18)
        config = {'bind': '0.0.0.0', 'port': 8787, 'version': VERSION, 'language': language}
        set_password(config, password)
        write_config(data, config)
        Agents(Store(data), config)
        print(translate('Benutzername', language) + ': admin')
        if not args.password_stdin:
            print(translate('Startpasswort', language) + ': ' + password)
        return
    if args.command == 'password':
        config = read_config(data)
        password = sys.stdin.readline().rstrip('\r\n') if args.password_stdin else getpass.getpass('Neues Passwort (mindestens 12 Zeichen): ')
        accounts = Agents(Store(data), config)
        rows = accounts.store.rows('SELECT id FROM agents WHERE username=? COLLATE NOCASE', (args.username,))
        if not rows:
            raise ValueError('Agent nicht gefunden.')
        accounts.password(rows[0]['id'], '', password, verify=False)
        print('Passwort geändert. Bestehende Sitzungen dieses Agenten sind beendet.')
        return
    if args.command == 'doctor':
        result = probe('127.0.0.1', 2)
        print('Python: ' + sys.version.split()[0])
        print('SQLite: ' + sqlite3.sqlite_version)
        print('SSH-Abfrage: ' + ('verfügbar' if all(__import__('shutil').which(n) for n in ('ssh','ssh-keyscan')) else 'OpenSSH-Client fehlt'))
        print('Druckerabfrage: ' + ('verfügbar' if __import__('shutil').which('snmpwalk') else 'Net-SNMP (snmpwalk) fehlt'))
        print('SNMP-Abfrage: ' + ('verfügbar' if __import__('shutil').which('snmpbulkwalk') else 'Net-SNMP fehlt'))
        print('PostgreSQL-Abfrage: ' + ('verfügbar' if __import__('shutil').which('psql') else 'PostgreSQL-Client fehlt'))
        print('MariaDB/MySQL-Abfrage: ' + ('verfügbar' if any(__import__('shutil').which(n) for n in ('mariadb','mysql')) else 'MariaDB/MySQL-Client fehlt'))
        print('Ping-Selbsttest: ' + result['kind'])
        if result['message']:
            print(result['message'])
        return 0 if result['kind'] == 'up' else 1
    if args.command == 'backup':
        if not args.output:
            raise SystemExit('Bitte --output mit einem neuen Dateinamen angeben.')
        destination = Path(args.output)
        if destination.exists():
            raise SystemExit('Die Zieldatei existiert bereits.')
        source = sqlite3.connect(str(data / 'monitoring.sqlite3'))
        target = sqlite3.connect(str(destination))
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
        os.chmod(destination, 0o600)
        print('Datenbanksicherung erstellt: ' + str(destination))
        return
    asyncio.run(serve(args))


if __name__ == '__main__':
    try:
        sys.exit(main() or 0)
    except (ValueError, OSError) as exc:
        raise SystemExit('Fehler: ' + str(exc))
