"""Bounded time series for the UI; SQL aggregates avoid loading raw months in RAM."""
import math
import time

PERIODS = {'1h': 3600, '6h': 21600, '24h': 86400, '7d': 604800, '30d': 2592000}
SERIES = {
    'history': ('samples', 'device_id', 'rtt', 'kind', 'time,kind,rtt'),
    'service/history': ('service_samples', 'service_id', 'rtt', 'kind', 'time,kind,rtt,message,status_code'),
    'resource/history': ('resource_samples', 'metric_id', 'percent', 'status', 'time,percent,total,used,free,status'),
    'extended/history': ('extended_samples', 'metric_id', 'value', 'status', 'time,value,status'),
    'integration/history': ('integration_samples', 'metric_id', 'value', 'status', 'time,value,status'),
}


def series(store, route, ident, period=None, now=None):
    # Old device-history URLs continue to open their migrated Ping service.
    if route == 'history':
        migrated = store.rows("SELECT id FROM services WHERE legacy_device_id=? AND type='ping'", (ident,))
        ident = migrated[0]['id'] if migrated else -1
        route = 'service/history'
    table, key, value, status, columns = SERIES[route]
    if period is None:  # Compatibility with existing clients.
        return {'samples': list(reversed(store.rows(
            f'SELECT {columns} FROM {table} WHERE {key}=? ORDER BY id DESC LIMIT 120', (ident,))))}
    if period not in PERIODS:
        raise ValueError('Unbekannter Zeitraum.')
    end = float(time.time() if now is None else now)
    start = end - PERIODS[period]
    bucket = max(1, math.ceil(PERIODS[period] / 360))
    extra = ',AVG(total) AS total,AVG(used) AS used,AVG(free) AS free' if value == 'percent' else ''
    rows = store.rows(f'''
        SELECT MAX(id) AS latest_id,AVG(time) AS time,CAST((time-?)/? AS INTEGER) AS bucket,
        AVG({value}) AS {value},MIN({value}) AS minimum,MAX({value}) AS maximum,
        COUNT(*) AS count,SUM({value} IS NULL) AS missing,
        SUM({status} NOT IN ('up','warning','critical')) AS failed,
        SUM({status}='up') AS healthy,
        MAX(CASE {status} WHEN 'critical' THEN 7 WHEN 'down' THEN 6
          WHEN 'error' THEN 5 WHEN 'unknown' THEN 4 WHEN 'warning' THEN 3
          WHEN 'up' THEN 1 ELSE 2 END) AS severity {extra}
        FROM {table} WHERE {key}=? AND time>=? AND time<=?
        GROUP BY bucket ORDER BY bucket''', (start, bucket, ident, start, end))
    latest = {}
    if route == 'service/history' and rows:
        ids = [row['latest_id'] for row in rows]
        latest = {row['id']: row for row in store.rows(
            'SELECT id,message,status_code FROM service_samples WHERE id IN (' + ','.join('?' for _ in ids) + ')', ids)}
    for row in rows:
        detail = latest.get(row.pop('latest_id'))
        if detail:
            row.update(message=detail['message'], status_code=detail['status_code'])
        row[status] = {1: 'up', 2: 'pending', 3: 'warning', 4: 'unknown', 5: 'error', 6: 'down', 7: 'critical'}[row.pop('severity')]
    measured = sum(r['count'] - r['missing'] for r in rows)
    valid = [r for r in rows if r[value] is not None]
    return {'samples': rows, 'from': start, 'to': end, 'period': period,
            'bucket_seconds': bucket, 'summary': {
                'count': sum(r['count'] for r in rows),
                'missing': sum(r['missing'] for r in rows),
                'failed': sum(r['failed'] for r in rows),
                'healthy': sum(r['healthy'] for r in rows),
                'minimum': min((r['minimum'] for r in valid), default=None),
                'maximum': max((r['maximum'] for r in valid), default=None),
                'average': sum(r[value] * (r['count'] - r['missing']) for r in valid) / measured if measured else None}}
