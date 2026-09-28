"""Read-only WMI enumeration over WinRM HTTPS (no remote shell or agent)."""
import datetime
import time
import uuid
from xml.sax.saxutils import escape
from .integration_common import HTTPS, CheckFailure, child, local, metric, numeric, text_at, xml

ENUM = 'http://schemas.xmlsoap.org/ws/2004/09/enumeration'
WSMAN = 'http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd'
WQL = 'http://schemas.microsoft.com/wbem/wsman/1/WQL'


class WinRM:
    def __init__(self, config, timeout):
        self.http = HTTPS(config, timeout)
        host = '['+config['host']+']' if ':' in config['host'] else config['host']
        self.endpoint = 'https://%s:%s/wsman' % (host, config['port'])

    def request(self, action, resource, content):
        payload = '''<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
          xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
          xmlns:w="%s" xmlns:n="%s">
          <s:Header><a:To s:mustUnderstand="true">%s</a:To>
          <w:ResourceURI s:mustUnderstand="true">%s</w:ResourceURI>
          <a:ReplyTo><a:Address s:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address></a:ReplyTo>
          <a:Action s:mustUnderstand="true">%s/%s</a:Action><a:MessageID>uuid:%s</a:MessageID>
          <w:MaxEnvelopeSize s:mustUnderstand="true">153600</w:MaxEnvelopeSize>
          <w:OperationTimeout>PT5S</w:OperationTimeout></s:Header>
          <s:Body>%s</s:Body></s:Envelope>''' % (WSMAN,ENUM,escape(self.endpoint),escape(resource),ENUM,action,uuid.uuid4(),content)
        data = self.http.request('/wsman','POST',payload.encode('utf-8'),{'Content-Type':'application/soap+xml;charset=UTF-8'})
        return xml(data)

    def query(self, query, namespace='root/cimv2', limit=5000):
        resource = 'http://schemas.microsoft.com/wbem/wsman/1/wmi/' + namespace + '/*'
        content = '<n:Enumerate><w:OptimizeEnumeration/><w:MaxElements>100</w:MaxElements><w:Filter Dialect="%s">%s</w:Filter></n:Enumerate>' % (WQL,escape(query))
        root = self.request('Enumerate', resource, content)
        rows, context = [], None
        try:
            for _ in range(100):
                for items in root.iter():
                    if local(items.tag) == 'Items':
                        for item in items:
                            if local(item.tag) == 'XmlFragment' and len(item) == 1: item = item[0]
                            rows.append({local(n.tag):n.text for n in item})
                context = next((n.text for n in root.iter() if local(n.tag)=='EnumerationContext'),None)
                if any(local(n.tag)=='EndOfSequence' for n in root.iter()) or not context:
                    context = None
                    return rows[:limit]
                if len(rows) >= limit:
                    if limit==1000: return rows[:limit]
                    raise CheckFailure('WMI-Inventar umfasst mehr als 5.000 Einträge. Auswahl begrenzen.')
                root=self.request('Pull',resource,'<n:Pull><n:EnumerationContext>%s</n:EnumerationContext><n:MaxElements>100</n:MaxElements><n:MaxTime>PT5S</n:MaxTime></n:Pull>' % escape(context))
            raise CheckFailure('WMI-Antwort ist zu umfangreich. Auswahl begrenzen.')
        finally:
            if context:
                try: self.request('Release',resource,'<n:Release><n:EnumerationContext>%s</n:EnumerationContext></n:Release>' % escape(context))
                except Exception: pass


def windows_check(cfg, timeout):
    client=WinRM(cfg,timeout); metrics=[]
    def area(label, action):
        try: action()
        except CheckFailure as exc: metrics.append(metric('missing:'+label,label,None,status='unknown',message=str(exc)))
    if cfg['basic']:
        def cpu():
            rows=client.query('SELECT LoadPercentage FROM Win32_Processor')
            loads=[numeric(r.get('LoadPercentage')) for r in rows]
            values=[n for n in loads if n is not None]
            metrics.append(metric('cpu','CPU gesamt',sum(values)/len(values) if values else None,'%',warn=cfg['cpu_warn'],critical=cfg['cpu_crit']))
        area('CPU',cpu)
        def memory():
            rows=client.query('SELECT TotalVisibleMemorySize,FreePhysicalMemory,LastBootUpTime FROM Win32_OperatingSystem')
            row=rows[0] if rows else {};total=numeric(row.get('TotalVisibleMemorySize'));free=numeric(row.get('FreePhysicalMemory'))
            metrics.append(metric('ram','Arbeitsspeicher',100*(total-free)/total if total and free is not None and 0<=free<=total else None,'%',warn=cfg['ram_warn'],critical=cfg['ram_crit']))
            metrics.append(metric('ram-free','Arbeitsspeicher frei',free/1024 if free is not None else None,'MiB'))
        area('Arbeitsspeicher',memory)
        def disks():
            rows=client.query('SELECT DeviceID,Size,FreeSpace FROM Win32_LogicalDisk WHERE DriveType=3')
            if not rows: raise CheckFailure('Keine lokalen Laufwerke oder fehlende WMI-Leserechte.')
            for row in rows:
                total=numeric(row.get('Size'));free=numeric(row.get('FreeSpace'));name=row.get('DeviceID') or '?'
                metrics.append(metric('disk:'+name,'Laufwerk '+name,100*(total-free)/total if total and free is not None and 0<=free<=total else None,'%',warn=cfg['disk_warn'],critical=cfg['disk_crit']))
        area('Laufwerke',disks)
    if cfg['services']:
        def services():
            rows=client.query('SELECT Name,DisplayName,State FROM Win32_Service')
            found={r.get('Name','').lower():r for r in rows}
            for name in cfg['services']:
                row=found.get(name.lower()); running=bool(row and row.get('State')=='Running')
                metrics.append(metric('service:'+name,'Dienst '+name,int(running),'','up' if running else 'critical',
                                      row.get('State','Unbekannt') if row else 'Dienst nicht gefunden. Internen Dienstnamen prüfen.'))
        area('Windows-Dienste',services)
    if cfg['event_errors']:
        def events():
            since=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(minutes=cfg['event_minutes'])).strftime('%Y%m%d%H%M%S.000000+000')
            for log in ('System','Application'):
                rows=client.query("SELECT RecordNumber FROM Win32_NTLogEvent WHERE Logfile='%s' AND EventType=1 AND TimeGenerated>='%s'" % (log,since),limit=1000)
                metrics.append(metric('events:'+log,'Fehlerereignisse · '+log,len(rows),'Ereignisse','warning' if rows else 'up',
                    ('Mindestens ' if len(rows)==1000 else '')+str(len(rows))+' Fehler in den letzten '+str(cfg['event_minutes'])+' Minuten.'))
        area('Ereignisprotokolle',events)
    return metrics


def hyperv_check(cfg, timeout):
    rows=WinRM(cfg,timeout).query('SELECT Name,ElementName,EnabledState,HealthState,Caption FROM Msvm_ComputerSystem','root/virtualization/v2')
    metrics=[]; expected=set(cfg['expected_running']); found=set(); inventory=[]
    for row in rows:
        # The host has Caption="Hosting Computer System"; virtual machines use "Virtual Machine".
        if row.get('Caption') != 'Virtual Machine': continue
        ident=row.get('Name');name=row.get('ElementName') or ident
        if not ident: continue
        inventory.append(dict(id=ident,name=name));found|={ident,name}
        power=numeric(row.get('EnabledState')); health=numeric(row.get('HealthState'))
        required=ident in expected or name in expected
        state='unknown' if power is None else 'critical' if required and power!=2 else 'up'
        message={2:'Läuft',3:'Ausgeschaltet',32768:'Pausiert',32769:'Gespeichert',32770:'Startet',32773:'Speichert',32774:'Stoppt'}.get(power,'Zustand '+str(power))
        metrics.append(metric('vm:'+ident+':power',name+' · Betrieb',1 if power==2 else 0 if power is not None else None,'',state,message+(' · Betrieb erwartet' if required else ' · Zustand zur Information')))
        metrics.append(metric('vm:'+ident+':health',name+' · Zustand',health,'',
            ('up' if power==3 else 'unknown') if health is None or health==0 else 'critical' if health>=20 else 'warning' if health>5 else 'up','Hyper-V HealthState '+str(health)))
    for missing in expected-found:
        metrics.append(metric('missing-vm:'+missing,'Erwartete VM '+missing,None,status='critical',message='Die erwartete VM wurde nicht gefunden.'))
    if not inventory: metrics.append(metric('inventory','Virtuelle Maschinen',0,'VMs','warning','Keine VMs sichtbar. Hyper-V-Rolle und Rechte auf root/virtualization/v2 prüfen.'))
    return metrics,inventory
