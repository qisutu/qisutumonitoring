"""Declarative check forms shared by validation, templates, and the local UI."""
import copy
import math
import re


def field(key, label, kind='text', default='', **options):
    if kind in ('lines', 'rows') and default == '':
        default = []
    return dict(key=key, label=label, type=kind, default=default, **options)


SECRET_FIELDS = ('token', 'secret_key', 'session_token', 'client_secret', 'ssh_password', 'ssh_key', 'client_key')
AUTH = [field('username', 'Benutzername'), field('password', 'Passwort', 'password'),
        field('token', 'Zugangstoken', 'password'), field('fingerprint', 'SHA-256-Fingerabdruck')]
LIMITS = [field('warn', 'Warnung ab', 'optional_number'), field('critical', 'Kritisch ab', 'optional_number')]
METRICS = [field('name', 'Bezeichnung'), field('path', 'JSON-Pfad'), field('unit', 'Einheit'),
           field('scale', 'Faktor', 'number', 1), *LIMITS]
STEPS = [field('name', 'Bezeichnung'), field('path', 'Pfad', default='/'),
         field('method', 'Methode', 'select', 'GET', choices=['GET', 'POST']),
         field('body', 'Formulardaten'), field('codes', 'HTTP-Codes', default='200-299'),
         field('contains', 'Erwarteter Inhalt'), field('extract', 'Ausdruck für Variable'),
         field('variable', 'Variablenname')]
SNMP = [field('version', 'SNMP-Version', 'select', '3', choices=['3', '2c']),
        field('username', 'SNMP-Benutzer'), field('community', 'Community', 'password'),
        field('auth_password', 'Authentifizierungspasswort', 'password'),
        field('priv_password', 'Verschlüsselungspasswort', 'password'),
        field('auth_protocol', 'Authentifizierung', 'select', 'SHA-256', choices=['SHA', 'SHA-256', 'SHA-512'])]
SSH = [field('username', 'Benutzername'), field('ssh_auth', 'Anmeldung', 'select', 'password', choices=['password', 'key']),
       field('ssh_password', 'Passwort', 'password'), field('ssh_key', 'Privater SSH-Schlüssel', 'secret_text'),
       field('ssh_host_key', 'Bestätigter SSH-Server-Schlüssel')]
PROFILES = {
    'cisco': [
        dict(name='CPU (5 min)', oid='.1.3.6.1.4.1.9.9.109.1.1.1.1.8', unit='%', scale=1, warn=80, critical=95),
        dict(name='Speicher belegt', oid='.1.3.6.1.4.1.9.9.48.1.1.1.5', unit='B', scale=1),
        dict(name='Speicher frei', oid='.1.3.6.1.4.1.9.9.48.1.1.1.6', unit='B', scale=1),
    ],
    'fortigate': [
        dict(name='CPU', oid='.1.3.6.1.4.1.12356.101.4.1.3.0', unit='%', scale=1, warn=80, critical=95),
        dict(name='Arbeitsspeicher', oid='.1.3.6.1.4.1.12356.101.4.1.4.0', unit='%', scale=1, warn=80, critical=95),
        dict(name='Sitzungen', oid='.1.3.6.1.4.1.12356.101.4.1.8.0', unit='', scale=1),
        dict(name='VPN-Tunnel', oid='.1.3.6.1.4.1.12356.101.12.2.2.1.20', unit='', scale=1, expected='2'),
    ],
    'mikrotik': [
        dict(name='Temperatur', oid='.1.3.6.1.4.1.14988.1.1.3.10.0', unit='°C', scale=0.1, warn=70, critical=85),
        dict(name='Spannung', oid='.1.3.6.1.4.1.14988.1.1.3.8.0', unit='V', scale=0.1),
    ],
    'standard': [dict(name='Betriebszeit', oid='.1.3.6.1.2.1.1.3.0', unit='s', scale=0.01)],
}
SCHEMAS = {
    'webscenario': dict(label='Web-Ablauf', port=443, help='Prüft mehrere Seiten mit gemeinsamer Sitzung, Anmeldung und Inhaltsprüfung. Formulardaten können {{username}}, {{password}} und zuvor extrahierte Variablen verwenden.', fields=[
        field('scheme', 'Verbindung', 'select', 'https', choices=['https', 'http']), *AUTH,
        field('steps', 'Prüfschritte', 'rows', [], fields=STEPS, maximum=20)]),
    'httpjson': dict(label='HTTP / JSON', port=443, help='Liest eine API-Antwort aus und erzeugt eigene Messwerte. JSON-Pfade unterstützen $.feld, [0] und [*].', fields=[
        field('scheme', 'Verbindung', 'select', 'https', choices=['https', 'http']), *AUTH,
        field('path', 'Pfad', default='/'), field('metrics', 'Messwerte', 'rows', [], fields=METRICS, maximum=100)]),
    'snmpcustom': dict(label='SNMP / Herstellerprofil', port=161, help='Herstellerprofil auswählen oder eigene OIDs ergänzen. Tabellen werden automatisch nach Instanzen aufgelöst. Nicht unterstützte OIDs werden ausdrücklich als fehlend angezeigt.', fields=[
        *SNMP, field('profile', 'Herstellerprofil', 'select', 'standard', choices=['standard', 'cisco', 'fortigate', 'mikrotik', 'custom']),
        field('metrics', 'Zusätzliche OIDs', 'rows', [], maximum=100, fields=[
            field('name', 'Bezeichnung'), field('oid', 'OID'), field('unit', 'Einheit'), field('scale', 'Faktor', 'number', 1),
            field('rate', 'Änderung pro Sekunde', 'bool', False), field('expected', 'Erwarteter Wert'), *LIMITS])]),
    'linuxlog': dict(label='Linux-Protokoll', port=22, help='Liest das systemd-Journal des gewählten Zeitraums über SSH. Filter nach Dienst und Text; das Journal wird nicht verändert.', fields=[
        *SSH, field('unit', 'Systemd-Dienst'), field('minutes', 'Zeitraum in Minuten', 'number', 15, minimum=1, maximum=1440),
        field('priority', 'Schweregrad bis', 'select', '3', choices=['0','1','2','3','4','5','6','7']), field('contains', 'Enthaltener Text')]),
    'sshcheck': dict(label='Eigene SSH-Messung', port=22, help='Führt den angegebenen Messbefehl mit den Rechten des SSH-Benutzers aus. Die Ausgabe muss eine Zahl oder JSON mit den gewählten Messwerten enthalten.', fields=[
        *SSH, field('command', 'Messbefehl', 'multiline'), field('metrics', 'JSON-Messwerte (optional)', 'rows', [], fields=METRICS, maximum=100)]),
    'prometheus': dict(label='Prometheus-Exporter', port=443, help='Liest Messwerte eines Exporters im Prometheus-Textformat. Namensfilter begrenzen die Auswahl; Labels bleiben je Messreihe erhalten.', fields=[
        field('scheme', 'Verbindung', 'select', 'https', choices=['https','http']), *AUTH,
        field('path', 'Pfad', default='/metrics'), field('names', 'Messwertnamen (leer = alle)', 'lines')]),
    'docker': dict(label='Docker-Container', port=2376, help='Liest Containerzustand, CPU, RAM, Netzwerk- und Datenträgerzähler über die geschützte Docker-API. Der Monitoring-Server selbst benötigt kein Docker.', fields=[
        *AUTH, field('client_cert', 'Client-Zertifikat (PEM)', 'multiline'), field('client_key', 'Client-Schlüssel (PEM)', 'secret_text'),
        field('names', 'Containernamen (leer = alle)', 'lines'), field('expected_running', 'Diese Container sollen laufen', 'lines')]),
    'kubernetes': dict(label='Kubernetes', port=6443, help='Liest Nodes, Pods, Neustarts und Bereitschaft. CPU/RAM benötigen die Kubernetes Metrics API. Das Token benötigt ausschließlich Leserechte.', fields=[
        *AUTH, field('namespace', 'Namespace (leer = alle)'), field('metrics_api', 'CPU und RAM erfassen', 'bool', True)]),
    'aws': dict(label='AWS CloudWatch', port=443, help='Erkennt CloudWatch-Messreihen eines Namensraums und liest aktuelle Werte. Erforderliche IAM-Leserechte: cloudwatch:ListMetrics und cloudwatch:GetMetricData.', fields=[
        field('region', 'Region', default='eu-central-1'), field('access_key', 'Access Key ID'),
        field('secret_key', 'Secret Access Key', 'password'), field('session_token', 'Session-Token (optional)', 'password'),
        field('namespace', 'Namensraum', default='AWS/EC2'), field('names', 'Messwertnamen (leer = alle)', 'lines'),
        field('statistic', 'Statistik', 'select', 'Average', choices=['Average','Minimum','Maximum','Sum','SampleCount']),
        field('dimensions', 'Dimensionsfilter', 'rows', [], maximum=10, fields=[field('name','Name'),field('value','Wert')])]),
    'azure': dict(label='Azure Monitor', port=443, help='Erkennt Ressourcen einer Subscription und liest ausgewählte Azure-Monitor-Messwerte. Benötigt einen Dienstprinzipal mit Monitoring-Reader-Rechten.', fields=[
        field('tenant_id','Tenant-ID'), field('client_id','Client-ID'), field('client_secret','Client-Secret','password'),
        field('subscription_id','Subscription-ID'), field('resource_group','Ressourcengruppe (optional)'),
        field('resource_id','Ressourcen-ID (optional)'), field('names','Messwertnamen (leer = alle)','lines')]),
    'mssql': dict(label='Microsoft SQL Server', port=1433, help='Liest Sitzungen, Datenbankgrößen, Wartevorgänge und Leistungszähler über ODBC Driver 18. Der Benutzer benötigt Leserechte auf die Statistikansichten.', fields=[
        field('username','Benutzername'),field('password','Passwort','password'),field('database','Datenbankname',default='master'),
        field('driver','ODBC-Treiber',default='ODBC Driver 18 for SQL Server'),field('query','Eigene SELECT-Abfrage (optional)','multiline')]),
    'calculated': dict(label='Berechneter Messwert', port=1, help='Berechnet einen Wert aus vorhandenen Messreihen. Quellen werden über Messreihe und ID ausgewählt. Veraltete oder fehlende Werte ergeben keinen gültigen Messwert.', fields=[
        field('expression','Formel',default='a'),field('unit','Einheit'),*LIMITS,
        field('sources','Quellen','rows',[],maximum=20,fields=[field('name','Variable'),field('route','Messreihe','select','integration',choices=['integration','extended','resource','service']),field('id','Messwert-ID','number',1,minimum=1,maximum=2147483647)]),
        field('max_age','Höchstalter in Sekunden','number',300,minimum=15,maximum=86400)]),
}


def validate_field(spec, value, previous=None):
    kind = spec['type']
    if kind in ('password', 'secret_text') and not value:
        value = previous or ''
    if kind == 'bool':
        if not isinstance(value, bool):
            raise ValueError('Ungültige Auswahl: ' + spec['label'])
    elif kind in ('number', 'optional_number'):
        if kind == 'optional_number' and value in ('', None):
            return None
        try:
            value = float(value)
        except (ValueError, TypeError):
            raise ValueError('Ungültige Zahl: ' + spec['label'])
        if not math.isfinite(value) or not spec.get('minimum', -1e15) <= value <= spec.get('maximum', 1e15):
            raise ValueError('Zahl außerhalb des Bereichs: ' + spec['label'])
    elif kind == 'rows':
        if not isinstance(value, list) or len(value) > spec['maximum']:
            raise ValueError('Zu viele Einträge: ' + spec['label'])
        result = []
        for row in value:
            if not isinstance(row, dict) or set(row) - {f['key'] for f in spec['fields']}:
                raise ValueError('Ungültige Zeile: ' + spec['label'])
            result.append({f['key']: validate_field(f, row.get(f['key'], copy.deepcopy(f['default']))) for f in spec['fields']})
        value = result
    elif kind == 'lines':
        if not isinstance(value, list) or len(value) > 200:
            raise ValueError('Ungültige Liste: ' + spec['label'])
        value = [str(v).strip() for v in value if str(v).strip()]
        if any(len(v) > 500 or any(ord(c) < 32 for c in v) for v in value):
            raise ValueError('Ungültiger Eintrag: ' + spec['label'])
    else:
        if not isinstance(value, str) or len(value) > (16000 if kind in ('multiline','secret_text') else 4096) or '\x00' in value:
            raise ValueError('Ungültiger Text: ' + spec['label'])
        if kind not in ('multiline','secret_text') and any(ord(c) < 32 for c in value):
            raise ValueError('Ungültiger Text: ' + spec['label'])
        if kind == 'select' and value not in spec['choices']:
            raise ValueError('Ungültige Auswahl: ' + spec['label'])
    return value


def validate_advanced(kind, value, old=None):
    from .core import address, integer
    
    old = old or {}
    schema = SCHEMAS[kind]
    allowed = {'host','port','priv_protocol'} | {f['key'] for f in schema['fields']}
    if set(value) - allowed:
        raise ValueError('Unbekannte Einstellung für diese Prüfung.')
    cfg = {f['key']: validate_field(f, value.get(f['key'], copy.deepcopy(f['default'])), old.get(f['key'])) for f in schema['fields']}
    cfg.update(host=address(value.get('host','')), port=integer(value.get('port',schema['port']),1,65535,'Port'))
    pin = cfg.get('fingerprint','').replace(':','').lower()
    if pin and not re.fullmatch('[a-f0-9]{64}',pin):
        raise ValueError('Ungültiger SHA-256-Fingerabdruck.')
    if 'fingerprint' in cfg:
        cfg['fingerprint'] = pin
        if pin and old and pin == old.get('fingerprint') and (cfg['host'],cfg['port']) != (old.get('host'),old.get('port')):
            raise ValueError('Zertifikat für das neue Ziel erneut bestätigen.')
    if cfg.get('scheme') == 'http' and any(cfg.get(k) for k in ('username','password','token')):
        raise ValueError('Zugangsdaten benötigen HTTPS.')
    for row in cfg.get('metrics',[]):
        if not row['name']:
            raise ValueError('Bezeichnung für jeden Messwert angeben.')
        if row.get('warn') is not None and row.get('critical') is not None and row['warn'] >= row['critical']:
            raise ValueError('Warnwert muss kleiner als kritischer Wert sein.')
    if kind in ('httpjson',) and not cfg['metrics']:
        raise ValueError('Mindestens einen Messwert einrichten.')
    if kind == 'webscenario':
        from .services import status_codes
        if not cfg['steps']:
            raise ValueError('Mindestens einen Prüfschritt einrichten.')
        for step in cfg['steps']:
            status_codes(step['codes'])
            if step['variable'] and not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,40}',step['variable']):
                raise ValueError('Ungültiger Variablenname.')
            if step['extract']:
                try: re.compile(step['extract'])
                except re.error: raise ValueError('Ungültiger Ausdruck für die Variable.')
    if kind == 'snmpcustom':
        from .resources import validate_config
        validated = validate_config(dict(cfg,method='snmp',priv_protocol='AES'))
        for k in ('version','username','community','auth_password','priv_password','auth_protocol','priv_protocol'):
            cfg[k] = validated[k]
        for row in cfg['metrics']:
            if not re.fullmatch(r'\.?[0-9]+(?:\.[0-9]+){2,}',row['oid']):
                raise ValueError('OID muss numerisch sein.')
            row['oid']='.'+row['oid'].lstrip('.')
        if cfg['profile'] == 'custom' and not cfg['metrics']:
            raise ValueError('Mindestens eine OID einrichten.')
    if kind in ('linuxlog','sshcheck'):
        from .resources import validate_config
        validated = validate_config(dict(cfg,method='ssh'))
        for k in ('username','ssh_auth','ssh_password','ssh_key','ssh_host_key'):
            cfg[k] = validated[k]
        if kind == 'linuxlog' and cfg['unit'] and not re.fullmatch(r'[A-Za-z0-9_.@:+-]{1,200}',cfg['unit']):
            raise ValueError('Ungültiger Systemd-Dienst.')
        if kind == 'sshcheck' and not cfg['command'].strip():
            raise ValueError('Messbefehl angeben.')
    if kind == 'aws':
        if not re.fullmatch(r'[a-z]{2}(?:-[a-z]+)+-[0-9]',cfg['region']) or not cfg['access_key'] or not cfg['secret_key']:
            raise ValueError('AWS-Region und Zugangsdaten angeben.')
        cfg['host'] = 'monitoring.' + cfg['region'] + '.amazonaws.com'
        cfg['port'] = 443
    if kind == 'azure':
        for key in ('tenant_id','client_id','subscription_id'):
            if not re.fullmatch('[a-fA-F0-9-]{36}',cfg[key]):
                raise ValueError('Azure-IDs müssen gültige UUIDs sein.')
        if not cfg['client_secret']:
            raise ValueError('Azure-Client-Secret angeben.')
        cfg['host'] = 'management.azure.com'
        cfg['port'] = 443
    if kind == 'mssql':
        if not cfg['username'] or not cfg['password']:
            raise ValueError('Datenbankzugang angeben.')
        if cfg['query']:
            from .check_sql import validate_select
            validate_select(cfg['query'])
    if kind == 'calculated':
        if cfg['warn'] is not None and cfg['critical'] is not None and cfg['warn']>=cfg['critical']:raise ValueError('Warnwert muss kleiner als kritischer Wert sein.')
        for source in cfg['sources']:
            if source['id'] != int(source['id']):raise ValueError('Messwert-ID muss ganzzahlig sein.')
            source['id']=int(source['id'])
        from .calculated import validate_expression
        validate_expression(cfg['expression'], [s['name'] for s in cfg['sources']])
    return cfg
