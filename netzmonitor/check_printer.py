"""Printer-MIB v2 (RFC 3805) and HOST-RESOURCES-MIB read-only metrics."""
from .integration_common import metric, numeric

ROOT = '.1.3.6.1.2.1.43'


def printer_check(cfg, timeout, diagnostic=False):
    """Bounded read-only GETNEXT queries; automatic mode never includes v3."""
    import os
    from pathlib import Path
    import shutil
    import subprocess
    import tempfile
    import time
    from .resources import config_text, run_walk, CheckError
    deadline = time.monotonic()+timeout
    checks = []
    binary = shutil.which('snmpwalk')
    if not binary:
        return dict(kind='error', metrics=[], message='Die Druckerabfrage fehlt auf dem Monitoring-Server. Den Installer erneut ausführen (Net-SNMP).', diagnostics=[])
    if diagnostic:
        ping = shutil.which('ping')
        status, message = 'unknown', 'Netzwerkerreichbarkeit konnte nicht geprüft werden.'
        if ping:
            try:
                result = subprocess.run([ping,'-n','-c','1','-W','1','-w','1',cfg['host']],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=min(1.5,timeout/3),
                    env={**os.environ,'LC_ALL':'C'})
                if result.returncode==0: status,message = 'up','Der Drucker hat auf Ping geantwortet.'
                elif result.returncode==1: message = 'Keine Ping-Antwort. Der Drucker kann ausgeschaltet sein; Ping kann aber auch gesperrt sein.'
            except (OSError,subprocess.TimeoutExpired): pass
        checks.append(dict(label='Netzwerkerreichbarkeit',status=status,message=message))
    versions = ['2c','1'] if cfg['version']=='auto' else [cfg['version']]
    for index,version in enumerate(versions):
        target = {**cfg,'version':version,'device_address':cfg['host']}
        attempt_deadline = time.monotonic()+max(0,deadline-time.monotonic())/(len(versions)-index)
        values = {}; errors = []
        with tempfile.TemporaryDirectory(prefix='netzmonitor-printer-') as directory:
            path = Path(directory)/'snmp.conf'
            path.write_text(config_text(target),encoding='utf-8');path.chmod(0o600)
            for root in ('.1.3.6.1.2.1.25.3.5',ROOT):
                try: values[root] = run_walk(binary,target,root,directory,attempt_deadline,bulk=False)
                except CheckError as exc: values[root] = {};errors.append(str(exc))
            host,data = values['.1.3.6.1.2.1.25.3.5'],values[ROOT]
            identity = {}
            if not host and not data:
                try: identity = run_walk(binary,target,'.1.3.6.1.2.1.1.1',directory,attempt_deadline,bulk=False)
                except CheckError as exc: errors.append(str(exc))
        protocol = 'SNMPv'+version
        if host or data or identity:
            metrics = printer_metrics(host,data,cfg)
            message = ('Druckerdaten empfangen über '+protocol+'.') if host or data else 'Der Drucker antwortet, liefert aber keine auswertbaren Druckerdaten.'
            checks.append(dict(label='Statusabfrage · '+protocol,status='up',message=message))
            return dict(kind='ok',metrics=metrics,message=message,diagnostics=checks)
        rejected = any('abgelehnt' in error for error in errors)
        checks.append(dict(label='Statusabfrage · '+protocol,status='unknown',message='Zugriff abgelehnt.' if rejected else 'Keine verwertbaren Statusdaten empfangen.'))
    if cfg['version']=='3':
        message = 'Die verschlüsselte Druckerabfrage ist fehlgeschlagen. Den eingerichteten SNMPv3-Zugang und die Netzwerkfreigabe am Drucker prüfen.'
    else:
        message = 'Keine Druckerdaten erhalten. Das bedeutet nicht automatisch, dass der Drucker ausgefallen ist. In seiner Netzwerkverwaltung die Statusabfrage (SNMP v1/v2c) und den Lesezugriff für den Monitoring-Server prüfen. Ein abweichender Leseschlüssel gehört unter „Zugriff anpassen“.'
    return dict(kind='error',metrics=[],message=message,diagnostics=checks)


def table(data, root):
    rows = {}
    for oid, value in data.items():
        if not oid.startswith(root+'.'): continue
        parts = oid[len(root)+1:].split('.')
        if len(parts)==3: rows.setdefault('.'.join(parts[1:]),{})[int(parts[0])] = value
    return rows


def printer_metrics(host, data, cfg):
    result = []
    for oid, value in host.items():
        if oid.startswith('.1.3.6.1.2.1.25.3.5.1.2.') and isinstance(value,str):
            bits = bytes.fromhex(value[4:]) if value.startswith('hex:') else value.encode('latin1',errors='replace')
            descriptions = ['Papier niedrig','Papier leer','Toner/Tinte niedrig','Toner/Tinte leer','Abdeckung offen',
                            'Papierstau','Offline','Service erforderlich','Eingabefach fehlt','Ausgabefach fehlt',
                            'Verbrauchsmaterial fehlt','Ausgabe fast voll','Ausgabe voll','Eingabefach leer','Wartung überfällig']
            active = [i for i in range(min(15,len(bits)*8)) if bits[i//8] & (128>>(i%8))]
            result.append(metric('errors:'+oid.rsplit('.',1)[1],'Druckerfehler',len(active),'',
                          status='critical' if any(i not in (0,2,11,14) for i in active) else 'warning' if active else 'up',
                          message=', '.join(descriptions[i] for i in active) or 'Keine Fehlerbits gesetzt.'))
        if oid.startswith('.1.3.6.1.2.1.25.3.5.1.1.'):
            index = oid.rsplit('.',1)[1]
            result.append(metric('state:'+index,'Druckerzustand',value,status={3:'up',4:'up',5:'up'}.get(value,'unknown'),
                                 message={1:'Anderer Zustand',2:'Unbekannt',3:'Bereit',4:'Druckt',5:'Aufwärmen'}.get(value,'Unbekannt')))
    # Alerts include paper empty/jam, open covers and offline states, as reported by the printer.
    alerts = table(data,ROOT+'.18.1.1')
    for index,row in alerts.items():
        severity = row.get(2)
        result.append(metric('alert:'+index,'Druckermeldung',None,status={3:'critical',4:'warning',5:'up'}.get(severity,'unknown'),
                             message=str(row.get(8) or 'Druckercode %s' % row.get(7,'unbekannt'))))
    if not alerts:
        result.append(metric('alerts','Aktuelle Druckermeldungen',0,'',message='Keine Einträge in der gelieferten Meldungstabelle.'))
    for index,row in table(data,ROOT+'.11.1.1').items():
        label = str(row.get(6) or 'Verbrauchsmaterial '+index)
        capacity, level = numeric(row.get(8)), numeric(row.get(9))
        # -1 other, -2 unknown, -3 some supply remains. None is a percentage.
        value = None
        if level is not None and level >= 0:
            if capacity is not None and capacity > 0: value = 100*level/capacity
            elif row.get(7)==19 and level<=100: value = level
        if value is not None and not 0 <= value <= 100: value = None
        receptacle = row.get(4)==4
        message = ('Sammelbehälter · Füllstand' if receptacle else 'Verbleibender Vorrat') if value is not None else {
            -1:'Füllstand nicht bezifferbar',-2:'Füllstand unbekannt',-3:'Vorrat vorhanden, Prozentwert nicht verfügbar'}.get(level,'Keine verwertbare Kapazität/Füllhöhe geliefert')
        result.append(metric('supply:'+index,label,value,'%',message=message,low=not receptacle,
                             warn=100-cfg['supply_warn'] if receptacle else cfg['supply_warn'],
                             critical=100-cfg['supply_crit'] if receptacle else cfg['supply_crit']))
    units = {7:'Druckseiten',8:'Blätter',5:'Zeichen',6:'Zeilen',9:'Punktzeilen',11:'Stunden'}
    for index,row in table(data,ROOT+'.10.2.1').items():
        if 4 in row:
            result.append(metric('counter:'+index,'Druckwerk '+index+' · Gesamtzähler',row[4],units.get(row.get(3),'Zähleinheiten')))
    for index,row in table(data,ROOT+'.8.2.1').items():
        cap,level = numeric(row.get(9)),numeric(row.get(10))
        value = 100*level/cap if cap and cap>0 and level is not None and 0<=level<=cap else None
        result.append(metric('paper:'+index,str(row.get(13) or row.get(18) or 'Papierfach '+index),value,'%',low=True,warn=10,critical=0,
                             message='Papierfüllstand' if value is not None else 'Papierfüllstand nicht numerisch verfügbar'))
    if not any(m['key'].startswith('state:') for m in result):
        result.append(metric('state:missing','Druckerzustand',message='HOST-RESOURCES-Drucker-MIB fehlt. SNMP-Freigabe prüfen.'))
    if not data:
        result = [m for m in result if m['key']!='alerts']
        result.append(metric('printer:missing','Verbrauchsmaterial / Papier / Zähler',message='Printer-MIB wird nicht geliefert. Unterstützung und SNMP-Leserechte prüfen.'))
    return result
