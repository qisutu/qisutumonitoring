"""Windows performance counters and filtered event records over read-only WMI."""
import datetime
import re
import time

from .integration_common import CheckFailure, metric, numeric


def validate_windows(cfg):
    for key in ('disk_io', 'network', 'process_monitoring'):
        value = cfg.get(key, False)
        if not isinstance(value, bool):
            raise ValueError('Ungültige Windows-Auswahl.')
        cfg[key] = value
    for key in ('processes', 'event_channels', 'event_ids', 'performance_counters'):
        value = cfg.get(key, [])
        if not isinstance(value, list) or len(value) > 100:
            raise ValueError('Höchstens 100 Windows-Einträge je Auswahl.')
        cfg[key] = list(dict.fromkeys(str(v).strip() for v in value if str(v).strip()))
        if any(len(v) > 200 or any(ord(c) < 32 for c in v) for v in cfg[key]):
            raise ValueError('Ungültiger Windows-Eintrag.')
    for code in cfg['event_ids']:
        if not code.isdigit() or not 0 <= int(code) <= 65535:
            raise ValueError('Ereignis-IDs müssen Zahlen zwischen 0 und 65535 sein.')
    for counter in cfg['performance_counters']:
        if not re.fullmatch(r'Win32_PerfFormattedData_[A-Za-z0-9_]+\.[A-Za-z][A-Za-z0-9_]*', counter):
            raise ValueError('Leistungszähler als Win32_PerfFormattedData_Klasse.Eigenschaft angeben.')
    for key in ('event_source', 'event_text'):
        cfg[key] = str(cfg.get(key, '')).strip()
        if len(cfg[key]) > 200 or any(ord(c) < 32 for c in cfg[key]):
            raise ValueError('Ereignisfilter ist ungültig.')
    if not cfg['event_channels']:
        cfg['event_channels'] = ['System', 'Application']
    return cfg


def performance(client, cfg):
    result = []

    def area(name, operation):
        try:
            result.extend(operation())
        except CheckFailure as exc:
            result.append(metric('missing:' + name, name, message=str(exc)))

    def disks():
        rows = client.query('SELECT * FROM Win32_PerfFormattedData_PerfDisk_PhysicalDisk')
        if not rows:
            raise CheckFailure('Keine Festplatten-Leistungszähler verfügbar.')
        values = []
        for row in rows:
            name = row.get('Name')
            if not name or name == '_Total':
                continue
            for prop, label, unit in (
                ('DiskReadsPersec', 'Lesevorgänge', 'IOPS'),
                ('DiskWritesPersec', 'Schreibvorgänge', 'IOPS'),
                ('DiskReadBytesPersec', 'Lesen', 'B/s'),
                ('DiskWriteBytesPersec', 'Schreiben', 'B/s'),
                ('CurrentDiskQueueLength', 'Warteschlange', ''),
            ):
                values.append(metric('diskio:' + name + ':' + prop, name + ' · ' + label, row.get(prop), unit))
        # PERF_AVERAGE_TIMER needs two raw snapshots; formatted integer WMI
        # values lose the sub-second precision of disk latency.
        query = ('SELECT Name,AvgDisksecPerRead,AvgDisksecPerRead_Base,'
                 'AvgDisksecPerWrite,AvgDisksecPerWrite_Base,Frequency_PerfTime '
                 'FROM Win32_PerfRawData_PerfDisk_PhysicalDisk')
        before = {r.get('Name'): {k.lower():v for k,v in r.items()} for r in client.query(query)}
        time.sleep(0.3)
        for row in client.query(query):
            name = row.get('Name')
            old = before.get(name)
            if not old or name == '_Total':
                continue
            row = {k.lower():v for k,v in row.items()}
            frequency = numeric(row.get('frequency_perftime'))
            for suffix, label in (('Read', 'Leselatenz'), ('Write', 'Schreiblatenz')):
                key = ('AvgDisksecPer' + suffix).lower()
                a, b = numeric(row.get(key)), numeric(old.get(key))
                base, previous = numeric(row.get(key + '_base')), numeric(old.get(key + '_base'))
                value = None
                if None not in (a, b, base, previous) and frequency and a >= b and base > previous:
                    value = 1000 * (a - b) / (base - previous) / frequency
                values.append(metric('diskio:' + name + ':latency' + suffix, name + ' · ' + label,
                                     value, 'ms', message='' if value is not None else 'Keine abgeschlossenen Vorgänge im Messfenster.'))
        return values

    def network():
        rows = client.query('SELECT * FROM Win32_PerfFormattedData_Tcpip_NetworkInterface')
        if not rows:
            raise CheckFailure('Keine Netzwerk-Leistungszähler verfügbar.')
        values = []
        for row in rows:
            name = row.get('Name') or '?'
            speed = numeric(row.get('CurrentBandwidth'))
            for prop, label, unit in (
                ('BytesReceivedPersec', 'Empfangen', 'B/s'), ('BytesSentPersec', 'Gesendet', 'B/s'),
                ('PacketsReceivedErrors', 'Empfangsfehler', 'gesamt'),
                ('PacketsOutboundErrors', 'Sendefehler', 'gesamt'),
                ('PacketsReceivedDiscarded', 'Verworfen empfangen', 'gesamt'),
                ('PacketsOutboundDiscarded', 'Verworfen gesendet', 'gesamt'),
            ):
                values.append(metric('winnet:' + name + ':' + prop, name + ' · ' + label, row.get(prop), unit))
            for prop, label in (('BytesReceivedPersec', 'Empfangsauslastung'), ('BytesSentPersec', 'Sendeauslastung')):
                rate = numeric(row.get(prop))
                usage = 800 * rate / speed if speed and rate is not None else None
                values.append(metric('winnet:' + name + ':usage:' + prop, name + ' · ' + label, usage, '%'))
        return values

    def processes():
        rows = client.query('SELECT Name,IDProcess,PercentProcessorTime,WorkingSetPrivate,PrivateBytes,IODataBytesPersec '
                            'FROM Win32_PerfFormattedData_PerfProc_Process')
        cpus = client.query('SELECT NumberOfLogicalProcessors FROM Win32_ComputerSystem')
        cores = numeric(cpus[0].get('NumberOfLogicalProcessors')) if cpus else None
        wanted = {(n.lower()[:-4] if n.lower().endswith('.exe') else n.lower()) for n in cfg.get('processes', [])}
        grouped = {}
        for row in rows:
            name = re.sub(r'#\d+$', '', row.get('Name', ''))
            if not name or name in ('_Total', 'Idle') or (wanted and name.lower() not in wanted):
                continue
            grouped.setdefault(name, []).append(row)
        values = []
        for name, entries in sorted(grouped.items()):
            for prop, label, unit, divisor in (
                ('PercentProcessorTime', 'CPU', '%', cores),
                ('WorkingSetPrivate', 'Privater Arbeitsspeicher', 'MiB', 1024 ** 2),
                ('PrivateBytes', 'Zugesicherter Speicher', 'MiB', 1024 ** 2),
                ('IODataBytesPersec', 'Ein-/Ausgabe', 'B/s', 1),
            ):
                numbers = [numeric(r.get(prop)) for r in entries]
                value = sum(numbers) / divisor if divisor and all(n is not None for n in numbers) else None
                values.append(metric('process:' + name + ':' + prop, name + ' · ' + label, value, unit))
            values.append(metric('process:' + name + ':count', name + ' · Instanzen', len(entries)))
        for missing in wanted - {n.lower() for n in grouped}:
            values.append(metric('process:' + missing + ':count', missing + ' · Instanzen', 0,
                                 status='critical', message='Der ausgewählte Prozess läuft nicht.'))
        if not values:
            raise CheckFailure('Keine Prozess-Leistungswerte verfügbar.')
        return values

    if cfg.get('disk_io'):
        area('Windows-Festplattenleistung', disks)
    if cfg.get('network'):
        area('Windows-Netzwerk', network)
    if cfg.get('process_monitoring'):
        area('Windows-Prozesse', processes)
    for counter in cfg.get('performance_counters', []):
        cls, prop = counter.split('.')
        def custom(cls=cls, prop=prop):
            rows = client.query('SELECT Name,' + prop + ' FROM ' + cls)
            if not rows:
                raise CheckFailure('Der Leistungszähler liefert keine Instanzen.')
            return [metric('counter:' + cls + ':' + str(r.get('Name', '')) + ':' + prop,
                           str(r.get('Name', cls)) + ' · ' + prop, r.get(prop)) for r in rows]
        area(counter, custom)
    return result


def events(client, cfg):
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=cfg['event_minutes'])).strftime('%Y%m%d%H%M%S.000000+000')
    values = []
    def quote(value):
        return value.replace('\\', '\\\\').replace("'", "\\'")
    for channel in cfg.get('event_channels', ['System', 'Application']):
        query = "SELECT RecordNumber,EventCode,SourceName,Message,TimeGenerated FROM Win32_NTLogEvent WHERE Logfile='%s' AND TimeGenerated>='%s'" % (quote(channel), since)
        ids = cfg.get('event_ids', [])
        if ids:
            query += ' AND (' + ' OR '.join('EventCode=' + str(int(n)) for n in ids) + ')'
        else:
            query += ' AND EventType=1'
        if cfg.get('event_source'):
            query += " AND SourceName='%s'" % quote(cfg['event_source'])
        rows = client.query(query, limit=1000)
        limited = len(rows) == 1000
        pattern = cfg.get('event_text', '').casefold()
        rows = [r for r in rows if pattern in (r.get('Message') or '').casefold()]
        rows.sort(key=lambda r: r.get('TimeGenerated', ''), reverse=True)
        details = '\n'.join('%s · %s · %s: %s' % (r.get('TimeGenerated', ''), r.get('EventCode', ''),
                            r.get('SourceName', ''), (r.get('Message') or '').strip()) for r in rows[:5])
        message = ('Mindestens ' if limited else '') + str(len(rows)) + ' Ereignisse. ' + details
        values.append(metric('events:' + channel, 'Ereignisse · ' + channel, len(rows), 'Ereignisse',
                             status='warning' if rows else 'unknown' if limited else 'up', message=message))
    return values
