"""Read-only database checks using distribution clients; passwords never in argv."""
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import time
from .integration_common import CheckFailure, metric, numeric

MYSQL_SQL = """SELECT 'probe',1;
SELECT 'max_connections',@@GLOBAL.max_connections;
SHOW GLOBAL STATUS WHERE Variable_name IN ('Threads_connected','Threads_running','Uptime',
 'Questions','Slow_queries','Aborted_connects','Innodb_buffer_pool_read_requests','Innodb_buffer_pool_reads');
SELECT 'database_bytes',COALESCE(SUM(DATA_LENGTH+INDEX_LENGTH),0) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE();
"""
POSTGRES_SQL = """BEGIN READ ONLY;
SELECT 'probe',1;
SELECT 'max_connections',current_setting('max_connections');
SELECT 'connections',count(*) FROM pg_stat_activity;
SELECT 'stats_permission',CASE WHEN pg_has_role(current_user,'pg_read_all_stats','MEMBER') THEN 1 ELSE 0 END;
SELECT 'active_connections',count(*) FROM pg_stat_activity WHERE state='active' AND pid<>pg_backend_pid();
SELECT 'lock_waits',count(*) FROM pg_stat_activity WHERE wait_event_type='Lock';
SELECT 'database_bytes',pg_database_size(current_database());
SELECT 'commits',xact_commit FROM pg_stat_database WHERE datname=current_database();
SELECT 'rollbacks',xact_rollback FROM pg_stat_database WHERE datname=current_database();
SELECT 'deadlocks',deadlocks FROM pg_stat_database WHERE datname=current_database();
SELECT 'cache_hits',blks_hit FROM pg_stat_database WHERE datname=current_database();
SELECT 'disk_reads',blks_read FROM pg_stat_database WHERE datname=current_database();
COMMIT;
"""


def database_metrics(values, cfg, elapsed):
    if values.get('probe') != 1: raise CheckFailure('Datenbank hat die Leseabfrage nicht bestätigt.')
    result = [metric('response','Verbindung und Leseabfragen',elapsed,'ms')]
    pg = cfg['engine']=='postgresql'
    connected = values.get('connections' if pg else 'Threads_connected')
    maximum = values.get('max_connections')
    result.extend([metric('connections','Offene Verbindungen',connected,'Verbindungen'),
                   metric('connection_limit','Verbindungslimit',maximum,'Verbindungen'),
                   metric('connection_usage','Verbindungsauslastung',100*connected/maximum if maximum and connected is not None else None,'%',
                          warn=cfg['connections_warn'],critical=cfg['connections_crit'])])
    fields = [('active_connections','Aktive Abfragen','Abfragen'),('lock_waits','Wartende Sperren','Abfragen'),
              ('commits','Transaktionen · bestätigt','gesamt'),('rollbacks','Transaktionen · zurückgerollt','gesamt'),('deadlocks','Deadlocks','gesamt')] if pg else [
              ('Threads_running','Aktive Abfragen','Abfragen'),('Uptime','Datenbanklaufzeit','s'),('Questions','Abfragen seit Start','gesamt'),
              ('Slow_queries','Langsame Abfragen seit Start','gesamt'),('Aborted_connects','Fehlgeschlagene Anmeldungen seit Start','gesamt')]
    for key,label,unit in fields:
        value = values.get(key)
        missing = pg and key in ('active_connections','lock_waits') and values.get('stats_permission')!=1
        result.append(metric(key,label,None if missing else value,unit,message='Für vollständige Sicht pg_read_all_stats zuweisen.' if missing else ''))
    if pg or cfg['database']:
        size = values.get('database_bytes')
        result.append(metric('database_size','Datenbankgröße',size/1024**2 if size is not None else None,'MiB',
                             message='Sichtbare Tabellen und Indizes (Schätzung).' if not pg else ''))
    reads = values.get('disk_reads' if pg else 'Innodb_buffer_pool_reads')
    hits = values.get('cache_hits' if pg else 'Innodb_buffer_pool_read_requests')
    total = (hits+reads if pg else hits) if hits is not None and reads is not None else None
    ratio = 100*(hits if pg else hits-reads)/total if total and total>0 else None
    result.append(metric('cache_hit','Cache-Trefferquote',ratio if ratio is None or 0<=ratio<=100 else None,'%',
                         message='Kumulativ seit Statistikstart; ohne Lesezugriffe nicht berechenbar.'))
    return result


def database_check(cfg, timeout):
    pg = cfg['engine']=='postgresql'
    binary = shutil.which('psql') if pg else (shutil.which('mariadb') or shutil.which('mysql'))
    if not binary:
        raise CheckFailure(('PostgreSQL-Client (psql)' if pg else 'MariaDB/MySQL-Client')+' fehlt auf dem Monitoring-Server. Installer erneut ausführen oder Clientpaket bereitstellen.')
    env = {k:v for k,v in os.environ.items() if not k.startswith(('PG','MYSQL','MARIADB'))}
    env['LC_ALL'] = 'C'
    ca = ssl.get_default_verify_paths().cafile
    if cfg['security']=='verify' and not ca: raise CheckFailure('CA-Zertifikatsspeicher fehlt auf dem Monitoring-Server.')
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='netzmonitor-db-') as directory:
        env['HOME'] = directory
        if pg:
            # pgpass metacharacters are escaped; wildcard host is safe in this private single-use file.
            password = cfg['password'].replace('\\','\\\\').replace(':','\\:')
            path = Path(directory)/'pgpass'
            path.write_text('*:*:*:*:'+password+'\n',encoding='utf-8'); path.chmod(0o600)
            env.update(PGPASSFILE=str(path),PGHOST=cfg['host'],PGPORT=str(cfg['port']),PGUSER=cfg['username'],
                       PGDATABASE=cfg['database'],PGCONNECT_TIMEOUT=str(min(10,max(2,timeout-1))),
                       PGSSLMODE='verify-full' if cfg['security']=='verify' else 'disable',
                       PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=%s' % (max(1,timeout-1)*1000),
                       PGAPPNAME='Qisutu Monitoring')
            if ca: env['PGSSLROOTCERT'] = ca
            args = [binary,'-X','-w','-q','-A','-t','-F','\t','-v','ON_ERROR_STOP=1']
            sql = POSTGRES_SQL
        else:
            def quote(value): return '"'+str(value).replace('\\','\\\\').replace('"','\\"')+'"'
            path = Path(directory)/'client.cnf'
            lines = ['[client]','user='+quote(cfg['username']),'password='+quote(cfg['password']),
                     'host='+quote(cfg['host']),'port='+str(cfg['port']),'protocol=TCP','default-character-set=utf8mb4']
            # Identify the installed client, not the selected server engine (MariaDB can query MySQL).
            version = subprocess.run([binary,'--no-defaults','--version'],capture_output=True,text=True,timeout=2)
            maria = 'mariadb' in (version.stdout+version.stderr).lower()
            if cfg['security']=='verify':
                lines += (['ssl=1','ssl-verify-server-cert=1'] if maria else ['ssl-mode=VERIFY_IDENTITY'])+['ssl-ca='+quote(ca)]
            else: lines += ['skip-ssl'] if maria else ['ssl-mode=DISABLED']
            if cfg['database']: lines += ['database='+quote(cfg['database'])]
            path.write_text('\n'.join(lines)+'\n',encoding='utf-8');path.chmod(0o600)
            args = [binary,'--defaults-file='+str(path),'--batch','--skip-column-names','--raw',
                    '--connect-timeout='+str(min(10,max(1,timeout-1)))]
            sql = MYSQL_SQL
        try:
            proc = subprocess.run(args,input=sql,text=True,capture_output=True,env=env,
                                  timeout=max(.1,timeout-1-(time.monotonic()-started)))
        except subprocess.TimeoutExpired: raise CheckFailure('Datenbank-Antwortfrist überschritten. Erreichbarkeit, Auslastung und Leserechte prüfen.')
        if proc.returncode:
            error = proc.stderr.lower()
            if any(s in error for s in ('certificate','ssl','tls')):
                raise CheckFailure('Datenbank-TLS fehlgeschlagen. Servername und vertrauenswürdige CA-Zertifikate prüfen.')
            if any(s in error for s in ('denied','authentication','permission','password')):
                raise CheckFailure('Datenbankzugang oder Leserechte abgelehnt. Benutzer, Passwort und Statistikrechte prüfen.')
            raise CheckFailure('Datenbankabfrage fehlgeschlagen. Adresse, Port, Datenbankname und Clientversion prüfen.')
        values = {}
        for line in proc.stdout.splitlines():
            parts = line.split('\t')
            if len(parts)==2: values[parts[0]] = numeric(parts[1])
        return database_metrics(values,cfg,(time.monotonic()-started)*1000)
