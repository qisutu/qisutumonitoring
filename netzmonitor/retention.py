"""Hourly, weighted trend storage maintained transactionally with raw samples."""
import json
import time

SOURCES = {
    'service': ('service_samples','service_id','rtt','kind','services'),
    'resource': ('resource_samples','metric_id','percent','status','resource_metrics'),
    'extended': ('extended_samples','metric_id','value','status','extended_metrics'),
    'integration': ('integration_samples','metric_id','value','status','integration_metrics'),
}
SEVERITY="CASE {status} WHEN 'critical' THEN 7 WHEN 'down' THEN 6 WHEN 'error' THEN 5 WHEN 'unknown' THEN 4 WHEN 'warning' THEN 3 WHEN 'up' THEN 1 ELSE 2 END"


def init_retention(store):
    with store.connect() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS history_trends(
            source TEXT NOT NULL,metric_id INTEGER NOT NULL,hour INTEGER NOT NULL,
            count INTEGER NOT NULL,missing INTEGER NOT NULL,value_sum REAL NOT NULL,
            minimum REAL,maximum REAL,healthy INTEGER NOT NULL,failed INTEGER NOT NULL,severity INTEGER NOT NULL,
            total_sum REAL NOT NULL DEFAULT 0,used_sum REAL NOT NULL DEFAULT 0,free_sum REAL NOT NULL DEFAULT 0,resource_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(source,metric_id,hour));
            CREATE INDEX IF NOT EXISTS history_trend_expiry ON history_trends(hour);''')
        for key,value in (('history_days',30),('trend_days',730),('service_workers',8),('resource_workers',4),('integration_workers',4)):
            db.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',(key,json.dumps(value)))
        for source,(table,ident,value,status,parent) in SOURCES.items():
            db.execute(f"CREATE TRIGGER IF NOT EXISTS trend_{source}_delete AFTER DELETE ON {parent} BEGIN DELETE FROM history_trends WHERE source='{source}' AND metric_id=OLD.id; END")
            severity=SEVERITY.format(status=status)
            migration='trends-v1-'+source
            if not db.execute('SELECT 1 FROM schema_migrations WHERE name=?',(migration,)).fetchone():
                extra='COALESCE(SUM(total),0),COALESCE(SUM(used),0),COALESCE(SUM(free),0),SUM(total IS NOT NULL)' if source=='resource' else '0,0,0,0'
                db.execute(f'''INSERT INTO history_trends SELECT ?,{ident},CAST(time/3600 AS INTEGER)*3600,
                    COUNT(*),SUM({value} IS NULL),COALESCE(SUM({value}),0),MIN({value}),MAX({value}),
                    SUM({status}='up'),SUM({status} NOT IN ('up','warning','critical')),MAX({severity}),{extra}
                    FROM {table} GROUP BY {ident},CAST(time/3600 AS INTEGER)
                    ON CONFLICT(source,metric_id,hour) DO NOTHING''',(source,))
                db.execute('INSERT INTO schema_migrations VALUES(?,?)',(migration,time.time()))
            new_severity=SEVERITY.format(status='NEW.'+status)
            resource_values='COALESCE(NEW.total,0),COALESCE(NEW.used,0),COALESCE(NEW.free,0),NEW.total IS NOT NULL' if source=='resource' else '0,0,0,0'
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS trend_{source}_insert AFTER INSERT ON {table} BEGIN
                INSERT INTO history_trends VALUES('{source}',NEW.{ident},CAST(NEW.time/3600 AS INTEGER)*3600,
                    1,NEW.{value} IS NULL,COALESCE(NEW.{value},0),NEW.{value},NEW.{value},
                    NEW.{status}='up',NEW.{status} NOT IN ('up','warning','critical'),{new_severity},{resource_values})
                ON CONFLICT(source,metric_id,hour) DO UPDATE SET
                    count=count+1,missing=missing+excluded.missing,value_sum=value_sum+excluded.value_sum,
                    minimum=CASE WHEN minimum IS NULL THEN excluded.minimum WHEN excluded.minimum IS NULL THEN minimum ELSE MIN(minimum,excluded.minimum) END,
                    maximum=CASE WHEN maximum IS NULL THEN excluded.maximum WHEN excluded.maximum IS NULL THEN maximum ELSE MAX(maximum,excluded.maximum) END,
                    healthy=healthy+excluded.healthy,failed=failed+excluded.failed,severity=MAX(severity,excluded.severity),
                    total_sum=total_sum+excluded.total_sum,used_sum=used_sum+excluded.used_sum,free_sum=free_sum+excluded.free_sum,
                    resource_count=resource_count+excluded.resource_count;
                END''')


def housekeeping(store,now=None):
    now=time.time() if now is None else now;settings=store.settings()
    cutoff=now-settings.get('history_days',30)*86400
    trend_cutoff=now-settings.get('trend_days',730)*86400
    with store.connect() as db:
        for source,(table,_,_,_,parent) in SOURCES.items():
            db.execute('DELETE FROM '+table+' WHERE time<?',(cutoff,))
            db.execute('DELETE FROM history_trends WHERE source=? AND metric_id NOT IN (SELECT id FROM '+parent+')',(source,))
        db.execute('DELETE FROM history_trends WHERE hour<?',(trend_cutoff,))
        db.execute('DELETE FROM samples WHERE time<?',(cutoff,))
        db.execute('DELETE FROM events WHERE time<?',(cutoff,))
        db.execute('DELETE FROM discoveries WHERE last_seen<?',(cutoff,))
        db.execute("DELETE FROM scans WHERE started<? AND status!='running'",(cutoff,))


def long_series(store,route,ident,seconds,end):
    import math
    source=route.split('/')[0];table,key,value,status,_=SOURCES[source]
    start=end-seconds;boundary=int(end//3600)*3600
    # Whole hour buckets keep weighted sums and exact min/max. Recent partial
    # hour uses raw values and is never counted twice.
    bucket=max(3600,math.ceil(seconds/360/3600)*3600)
    start=int(start//3600)*3600
    rows=store.rows('''SELECT hour AS time,count,missing,value_sum,minimum,maximum,healthy,failed,severity,
        total_sum,used_sum,free_sum,resource_count FROM history_trends
        WHERE source=? AND metric_id=? AND hour>=? AND hour<? ORDER BY hour''',(source,ident,start,boundary))
    severity=SEVERITY.format(status=status)
    extra='COALESCE(SUM(total),0) AS total_sum,COALESCE(SUM(used),0) AS used_sum,COALESCE(SUM(free),0) AS free_sum,SUM(total IS NOT NULL) AS resource_count' if source=='resource' else '0 AS total_sum,0 AS used_sum,0 AS free_sum,0 AS resource_count'
    recent=store.rows(f'''SELECT AVG(time) AS time,COUNT(*) AS count,SUM({value} IS NULL) AS missing,
        COALESCE(SUM({value}),0) AS value_sum,MIN({value}) AS minimum,MAX({value}) AS maximum,
        SUM({status}='up') AS healthy,SUM({status} NOT IN ('up','warning','critical')) AS failed,
        MAX({severity}) AS severity,{extra} FROM {table} WHERE {key}=? AND time>=? AND time<=? HAVING COUNT(*)>0''',(ident,boundary,end))
    grouped={}
    for row in rows+recent:
        index=int((row['time']-start)//bucket)
        current=grouped.setdefault(index,dict(time=start+index*bucket,count=0,missing=0,value_sum=0,minimum=None,maximum=None,healthy=0,failed=0,severity=0,total_sum=0,used_sum=0,free_sum=0,resource_count=0))
        for k in ('count','missing','value_sum','healthy','failed','total_sum','used_sum','free_sum','resource_count'):current[k]+=row[k] or 0
        for k,fn in (('minimum',min),('maximum',max)):
            if row[k] is not None:current[k]=row[k] if current[k] is None else fn(current[k],row[k])
        current['severity']=max(current['severity'],row['severity'] or 0)
    samples=[];total_sum=0;measured=0
    for row in sorted(grouped.values(),key=lambda r:r['time']):
        valid=row['count']-row['missing'];total_sum+=row['value_sum'];measured+=valid
        row[value]=row.pop('value_sum')/valid if valid else None
        row[status]={1:'up',2:'pending',3:'warning',4:'unknown',5:'error',6:'down',7:'critical'}.get(row.pop('severity'),'unknown')
        for k in ('total','used','free'):
            v=row.pop(k+'_sum')
            if source=='resource':row[k]=v/row['resource_count'] if row['resource_count'] else None
        row.pop('resource_count');samples.append(row)
    return dict(samples=samples,**{'from':start,'to':end},bucket_seconds=bucket,aggregated=True,summary=dict(
        count=sum(r['count'] for r in samples),missing=sum(r['missing'] for r in samples),failed=sum(r['failed'] for r in samples),
        healthy=sum(r['healthy'] for r in samples),minimum=min((r['minimum'] for r in samples if r['minimum'] is not None),default=None),
        maximum=max((r['maximum'] for r in samples if r['maximum'] is not None),default=None),average=total_sum/measured if measured else None))
