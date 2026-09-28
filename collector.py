#!/usr/bin/env python3
"""Qisutu Monitoring site collector with durable SQLite spool and HTTPS uplink."""
import argparse
import concurrent.futures
import contextlib
import getpass
import json
import logging
import os
import re
import tempfile
from pathlib import Path
import signal
import sqlite3
import threading
import time
import uuid
from urllib.parse import urlsplit

from netzmonitor.check_custom import HTTP
from netzmonitor.integration_common import CheckFailure
from netzmonitor.integrations import probe_integration
from netzmonitor.resources import probe_resources
from netzmonitor.services import probe_service

LOG=logging.getLogger('qisutu-collector')


def connection_config(config):
    parsed=urlsplit(config['url'])
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('Die Zentrale muss eine HTTPS-Adresse ohne Pfad sein.')
    pin=config.get('fingerprint','').replace(':','').lower()
    if pin and not re.fullmatch('[0-9a-f]{64}',pin):raise ValueError('Ungültiger SHA-256-Fingerabdruck.')
    if not 1<=int(config['collector_id'])<=2147483647 or not 30<=len(config['token'])<=200:raise ValueError('Ungültige Messsammler-ID oder Zugangsschlüssel.')
    if not 1<=int(config.get('workers',8))<=64 or not 100<=int(config.get('max_buffer_records',100000))<=1000000:
        raise ValueError('Worker müssen zwischen 1 und 64 und der Puffer zwischen 100 und 1.000.000 liegen.')
    return dict(host=parsed.hostname,port=parsed.port or 443,token=config['token'],fingerprint=pin)


class Collector:
    def __init__(self,path):
        self.path=Path(path).resolve();self.config=json.loads(self.path.read_text())
        self.remote=connection_config(self.config)
        self.ident=int(self.config['collector_id']);self.stopping=threading.Event()
        self.database=self.path.parent/'collector.sqlite3'
        fd=os.open(self.database,os.O_CREAT|os.O_APPEND|os.O_WRONLY,0o600);os.close(fd)
        os.chmod(self.database,0o600)
        self.lock=threading.Lock();self.active=set();self.last_fetch=0
        self.workers=int(self.config.get('workers',8));self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=self.workers)
        with self.connect() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS jobs(key TEXT PRIMARY KEY,target TEXT NOT NULL,type TEXT NOT NULL,revision TEXT NOT NULL,next_check REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS spool(receipt TEXT PRIMARY KEY,time REAL NOT NULL,payload TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value REAL NOT NULL);''')
        os.chmod(self.database,0o600)

    @contextlib.contextmanager
    def connect(self):
        db=sqlite3.connect(self.database,timeout=30);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()

    def synchronize(self):
        bundle=HTTP(self.remote,15).json('/collector/v1/config/'+str(self.ident))
        server_time=bundle['server_time'];now=time.time()
        if abs(server_time-now)>60:raise CheckFailure('Systemzeit weicht um mehr als 60 Sekunden von der Zentrale ab.')
        jobs=bundle['jobs'];seen=set()
        with self.connect() as db:
            for job in jobs:
                target=job['target'];kind=job['type'];key=kind+':'+str(target['id']);seen.add(key)
                revision=json.dumps([target['revision'],target['device_revision'],target['device_block_revision']])
                old=db.execute('SELECT * FROM jobs WHERE key=?',(key,)).fetchone()
                due=old['next_check'] if old and old['revision']==revision else now
                db.execute('INSERT INTO jobs VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET target=excluded.target,revision=excluded.revision,next_check=excluded.next_check',
                           (key,json.dumps(target),kind,revision,due))
            for row in list(db.execute('SELECT key FROM jobs')):
                if row['key'] not in seen:db.execute('DELETE FROM jobs WHERE key=?',(row['key'],))
            db.execute("INSERT INTO metadata VALUES('lease',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(now+bundle['lease_seconds'],))
        self.last_fetch=now

    def flush(self):
        with self.connect() as db:
            # The server accepts at most 30 days of offline samples. Expired
            # records are logged explicitly; they cannot poison the whole queue.
            expired=db.execute('DELETE FROM spool WHERE time<?',(time.time()-30*86400+60,)).rowcount
            if expired:LOG.warning('%s gespeicherte Messungen sind älter als 30 Tage.',expired)
            rows=list(db.execute('SELECT * FROM spool ORDER BY time LIMIT 20'))
        if not rows:return
        records=[];size=0
        for row in rows:
            if records and size+len(row['payload'])>1800000:break
            records.append(json.loads(row['payload']));size+=len(row['payload'])
        answer=HTTP(self.remote,30).json('/collector/v1/results/'+str(self.ident),'POST',json.dumps({'records':records}).encode(),{'Content-Type':'application/json'})
        allowed={r['receipt'] for r in records}
        with self.connect() as db:
            db.executemany('DELETE FROM spool WHERE receipt=?',[(receipt,) for receipt in answer['accepted'] if receipt in allowed])

    def measure(self,row):
        key=row['key'];target=json.loads(row['target']);kind=row['type']
        try:
            result={'service':probe_service,'resource':probe_resources,'integration':probe_integration}[kind](target)
            stamp=time.time();receipt=str(uuid.uuid4())
            packet=dict(receipt=receipt,type=kind,id=target['id'],revision=target['revision'],device_revision=target['device_revision'],
                        block_revision=target['device_block_revision'],time=stamp,result=result)
            with self.connect() as db:
                current=db.execute('SELECT revision FROM jobs WHERE key=?',(key,)).fetchone()
                if current and current['revision']==row['revision']:
                    db.execute('INSERT INTO spool VALUES(?,?,?)',(receipt,stamp,json.dumps(packet)))
                    db.execute('UPDATE jobs SET next_check=? WHERE key=?',(stamp+target['interval'],key))
        except Exception:
            LOG.exception('Prüfung fehlgeschlagen: %s',key)
            with self.connect() as db:db.execute('UPDATE jobs SET next_check=? WHERE key=?',(time.time()+30,key))
        finally:
            with self.lock:self.active.discard(key)

    def run(self):
        retry=0
        try:
            while not self.stopping.is_set():
                now=time.time()
                if now>=retry:
                    try:
                        if now-self.last_fetch>=30:self.synchronize()
                        self.flush();retry=now+2
                    except Exception as exc:
                        # Never log the config, request, access token or passwords.
                        LOG.warning('Zentrale nicht erreichbar (%s). Messungen werden lokal gepuffert.',type(exc).__name__)
                        retry=now+15
                with self.connect() as db:
                    lease=db.execute("SELECT value FROM metadata WHERE key='lease'").fetchone()
                    pending=db.execute('SELECT COUNT(*) FROM spool').fetchone()[0]
                    jobs=list(db.execute('SELECT * FROM jobs WHERE next_check<=? ORDER BY next_check LIMIT 64',(now,)))
                if lease and lease[0]>now and pending<int(self.config.get('max_buffer_records',100000)):
                    for row in jobs:
                        with self.lock:
                            if row['key'] in self.active or len(self.active)>=self.workers:continue
                            self.active.add(row['key'])
                        self.pool.submit(self.measure,dict(row))
                self.stopping.wait(0.5)
        finally:self.pool.shutdown(wait=True)


def configure(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    url=input('HTTPS-Adresse der Zentrale: ').strip()
    ident=int(input('Messsammler-ID: ').strip())
    token=getpass.getpass('Zugangsschlüssel: ').strip()
    pin=input('Bestätigter SHA-256-Fingerabdruck (leer bei vertrauenswürdiger CA): ').strip().replace(':','')
    value=dict(url=url,collector_id=ident,token=token,fingerprint=pin,workers=8,max_buffer_records=100000)
    remote=connection_config(value)
    HTTP(remote,15).json('/collector/v1/config/'+str(ident))
    # Verify access before replacing a working configuration. A failed setup
    # must not leave a file that a later installation silently reuses.
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,prefix='collector-',suffix='.tmp',delete=False) as out:
            temporary=Path(out.name);json.dump(value,out,indent=2);out.write('\n');out.flush();os.fsync(out.fileno())
        os.replace(temporary,path)
    finally:
        if temporary and temporary.exists():temporary.unlink()
    print('Verbindung bestätigt. Konfiguration gespeichert.')


def main():
    parser=argparse.ArgumentParser(description='Qisutu Monitoring Messsammler')
    parser.add_argument('command',choices=['configure','run'])
    parser.add_argument('--config',default='/var/lib/netzmonitor-collector/collector.json')
    args=parser.parse_args()
    if args.command=='configure':configure(args.config);return
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    collector=Collector(args.config)
    for signum in (signal.SIGTERM,signal.SIGINT):signal.signal(signum,lambda *_:collector.stopping.set())
    collector.run()


if __name__=='__main__':main()
