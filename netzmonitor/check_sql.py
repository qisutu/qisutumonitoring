"""Microsoft SQL Server checks through the system ODBC driver."""
import re
from .integration_common import CheckFailure, metric, numeric


def validate_select(query):
    # Read-only database permissions remain authoritative. This gate additionally
    # excludes multi-statements, comments, stored procedures and SELECT INTO.
    if not isinstance(query,str) or len(query)>16000 or not re.match(r'^\s*SELECT\b',query,re.I) or re.search(r';|--|/\*|\b(INTO|OPENROWSET|OPENQUERY|EXEC|EXECUTE|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|GRANT|DENY|REVOKE|MERGE|WAITFOR)\b',query,re.I):
        raise ValueError('Nur eine einzelne lesende SELECT-Abfrage ohne Kommentare verwenden.')
    return query


def mssql(cfg,timeout):
    try:import pyodbc
    except ImportError:raise CheckFailure('python3-pyodbc und Microsoft ODBC Driver 18 fehlen. Installationshinweise in der Prüfung öffnen.')
    def escape(value):return '{'+str(value).replace('}','}}')+'}'
    connection=None;result=[]
    try:
        dsn=';'.join(k+'='+escape(v) for k,v in {
            'DRIVER':cfg['driver'],'SERVER':'tcp:'+cfg['host']+','+str(cfg['port']),
            'DATABASE':cfg['database'],'UID':cfg['username'],'PWD':cfg['password'],
            'Encrypt':'yes','TrustServerCertificate':'no','ApplicationIntent':'ReadOnly',
            'APP':'Qisutu Monitoring'}.items())
        connection=pyodbc.connect(dsn,timeout=max(1,int(timeout)),autocommit=True)
        connection.timeout=max(1,int(timeout))
        def read(sql):
            cursor=connection.cursor()
            try:
                cursor.execute(sql)
                names=[c[0] for c in cursor.description]
                rows=cursor.fetchmany(1001)
                if len(rows)>1000:raise CheckFailure('SQL-Abfrage liefert mehr als 1.000 Zeilen.')
                return [dict(zip(names,row)) for row in rows]
            finally:cursor.close()
        checks=[
            ('Sitzungen',"SELECT COUNT(*) AS sessions, SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS active FROM sys.dm_exec_sessions WHERE is_user_process=1"),
            ('Wartende Anforderungen',"SELECT COUNT(*) AS waiting_requests,COALESCE(MAX(wait_time),0) AS maximum_wait_ms FROM sys.dm_exec_requests WHERE wait_type IS NOT NULL AND session_id<>@@SPID"),
            ('Datenbankgröße',"SELECT DB_NAME(database_id) AS name,SUM(CAST(size AS bigint))*8192 AS bytes FROM sys.master_files GROUP BY database_id"),
            ('Leistungszähler',"SELECT RTRIM(object_name)+'.'+RTRIM(counter_name)+'.'+RTRIM(instance_name) AS name,cntr_value,cntr_type FROM sys.dm_os_performance_counters WHERE counter_name IN ('Batch Requests/sec','Transactions/sec','Number of Deadlocks/sec','Lock Waits/sec','Page life expectancy','Memory Grants Pending','User Connections')"),
        ]
        for label,query in checks:
            try:
                for row in read(query):
                    identity=str(row.get('name',label))
                    if 'cntr_value' in row:
                        m=metric('sql:'+identity,identity,row['cntr_value'])
                        if row.get('cntr_type') in (272696320,272696576):m.update(counter=True,unit='/s')
                        result.append(m)
                    else:
                        for key,value in row.items():
                            if key=='name':continue
                            result.append(metric('sql:'+identity+':'+key,identity+' · '+key,numeric(value),'B' if key=='bytes' else 'ms' if key.endswith('_ms') else ''))
            except pyodbc.Error:
                result.append(metric('missing:sql:'+label,label,message='Statistikansicht nicht lesbar. VIEW SERVER STATE bzw. VIEW SERVER PERFORMANCE STATE prüfen.'))
        if cfg['query']:
            for index,row in enumerate(read(validate_select(cfg['query']))):
                for key,value in row.items():
                    if numeric(value) is not None:result.append(metric('custom:'+str(index)+':'+key,key+' ['+str(index)+']',value))
        return result
    except pyodbc.Error:
        raise CheckFailure('SQL-Server-Verbindung oder Abfrage fehlgeschlagen. Treiber, TLS-Zertifikat und Leserechte prüfen.')
    finally:
        if connection is not None:connection.close()
