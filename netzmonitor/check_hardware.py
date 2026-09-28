"""Redfish hardware inventory plus documented Synology and UPS-MIB profiles."""
import os
from pathlib import Path
import shutil
import tempfile
import time
from .integration_common import HTTPS, CheckFailure, metric, numeric


def redfish_check(cfg,timeout):
    http=HTTPS(cfg,timeout);metrics=[];visited=set();counts={k:0 for k in ('system','thermal','power','storage')}
    def health(obj,key,label,category):
        if not isinstance(obj,dict):return
        status=obj.get('Status') or {}
        if status.get('State')=='Absent':return
        h=status.get('HealthRollup') or status.get('Health')
        if h:
            metrics.append(metric(category+':'+key+':health',label+' · Zustand',None,status={'OK':'up','Warning':'warning','Critical':'critical'}.get(h,'unknown'),message=h))
            counts[category]+=1
        for field,unit in [('ReadingCelsius','°C'),('ReadingRPM','U/min'),('PowerConsumedWatts','W'),('LastPowerOutputWatts','W'),('ReadingVolts','V')]:
            if field not in obj:continue
            value=numeric(obj[field]);warn=numeric(obj.get('UpperThresholdNonCritical'));crit=numeric(obj.get('UpperThresholdCritical'))
            metrics.append(metric(category+':'+key+':'+field,label+' · '+unit,value,unit,warn=warn,critical=crit))
            counts[category]+=1
        if obj.get('Reading') is not None:
            unit=str(obj.get('ReadingUnits') or obj.get('ReadingType') or '')[:40]
            thresholds=obj.get('Thresholds') or {}
            metrics.append(metric(category+':'+key+':reading',label+' · Messwert',obj['Reading'],unit,
               warn=numeric((thresholds.get('UpperCaution') or {}).get('Reading')),
               critical=numeric((thresholds.get('UpperCritical') or {}).get('Reading'))))
            counts[category]+=1
    def visit(path,category,depth=0):
        if not path or path in visited:return
        if depth>10 or len(visited)>=256:raise CheckFailure('Redfish-Inventar zu groß. Hardwarebereiche einzeln einrichten.')
        visited.add(path)
        obj=http.json(path,allow_missing=True)
        if obj is None:return
        label=str(obj.get('Name') or obj.get('Id') or path)
        health(obj,path,label,category)
        for field in ('Temperatures','Fans','PowerSupplies','PowerControl','Voltages','StorageControllers','Controllers','Devices'):
            values=obj.get(field,[])
            if isinstance(values,list):
                for i,item in enumerate(values):
                    if not isinstance(item,dict):continue
                    sub=str(item.get('MemberId') or item.get('Id') or i)
                    health(item,path+':'+field+':'+sub,str(item.get('Name') or field+' '+sub),category)
        if 'Members' in obj:
            for member in obj['Members']:
                if isinstance(member,dict):visit(member.get('@odata.id'),category,depth+1)
        next_link=obj.get('Members@odata.nextLink') or obj.get('@odata.nextLink')
        if next_link:visit(next_link,category,depth+1)
        if category=='system':
            for field in ('ProcessorSummary','MemorySummary'):health(obj.get(field),path+':'+field,label+' · '+field,category)
        allowed={'system':(), 'thermal':('Fans','Temperatures','Sensors','EnvironmentMetrics'),
                 'power':('PowerSupplies','Voltages','PowerControl'), 'storage':('Drives','Volumes','Controllers','StorageControllers')}[category]
        for field in allowed:
            value=obj.get(field)
            links=value if isinstance(value,list) else [value]
            for link in links:
                if isinstance(link,dict) and link.get('@odata.id'):visit(link['@odata.id'],category,depth+1)
    root=http.json('/redfish/v1/')
    systems=http.json((root.get('Systems') or {}).get('@odata.id','/redfish/v1/Systems'),allow_missing=True)
    chassis=http.json((root.get('Chassis') or {}).get('@odata.id','/redfish/v1/Chassis'),allow_missing=True)
    # System/Chassis collections may paginate independently.
    def collection(value):
        result=[];pages=set()
        while value:
            result.extend(value.get('Members',[]))
            link=value.get('Members@odata.nextLink')
            if not link:return result
            if link in pages or len(pages)>=20:raise CheckFailure('Redfish-Inventarliste ist unvollständig oder zyklisch.')
            pages.add(link);value=http.json(link)
        return result
    for member in collection(systems):
        path=member.get('@odata.id')
        if not path:continue
        if cfg['system']:visit(path,'system')
        if cfg['storage']:
            obj=http.json(path)
            for field in ('Storage','SimpleStorage'):
                link=(obj.get(field) or {}).get('@odata.id')
                if link:visit(link,'storage')
    for member in collection(chassis):
        path=member.get('@odata.id')
        if not path:continue
        obj=http.json(path)
        for category,fields in [('thermal',('Thermal','ThermalSubsystem','Sensors')),('power',('Power','PowerSubsystem'))]:
            if not cfg[category]:continue
            for field in fields:
                link=(obj.get(field) or {}).get('@odata.id')
                if link:visit(link,category)
    for category in counts:
        if cfg[category] and not counts[category]:
            label={'system':'Systemzustand','thermal':'Temperaturen / Lüfter','power':'Stromversorgung','storage':'Controller / Laufwerke'}[category]
            metrics.append(metric(category+':missing',label,None,status='unknown',message='Dieser Bereich wird nicht geliefert oder ist nicht freigegeben. Auswahl oder BMC-Leserechte prüfen.'))
    return metrics


def snmp_table(data,prefix):
    rows={}
    for oid,value in data.items():
        if not oid.startswith(prefix+'.'):continue
        parts=oid[len(prefix)+1:].split('.')
        if len(parts)==2:rows.setdefault(parts[1],{})[int(parts[0])]=value
    return rows


def synology_metrics(system,disks,raids):
    metrics=[];root='.1.3.6.1.4.1.6574'
    for suffix,label in [('1.1.0','System'),('1.3.0','Stromversorgung'),('1.4.1.0','Systemlüfter'),('1.4.2.0','CPU-Lüfter')]:
        value=system.get(root+'.'+suffix)
        # Optional fans are omitted when the model does not expose them.
        if value is None and suffix!='1.1.0':continue
        metrics.append(metric('system:'+suffix,label,value,'',{1:'up',2:'critical'}.get(value,'unknown'),
                              {1:'Normal',2:'Fehler'}.get(value,'Nicht geliefert')))
    if root+'.1.2.0' in system:metrics.append(metric('temperature','Systemtemperatur',system[root+'.1.2.0'],'°C'))
    for index,row in snmp_table(disks,root+'.2.1.1').items():
        name=str(row.get(12) or row.get(2) or index);state=row.get(5);health=row.get(13)
        metrics.append(metric('disk:'+index+':state',name+' · Laufwerk',state,'',
            'up' if state in (1,2,3) else 'critical' if state in (4,5,6) else 'unknown',
            {1:'Normal',2:'Initialisiert, ohne Daten',3:'Nicht initialisiert',4:'Systempartition beschädigt',5:'Ausgefallen',6:'Getrennt'}.get(state,'Unbekannt')))
        if health is not None:
            metrics.append(metric('disk:'+index+':health',name+' · Gesundheit',health,'',
                {1:'up',2:'warning',3:'critical',4:'critical'}.get(health,'unknown'),{1:'Normal',2:'Warnung',3:'Kritisch',4:'Ausfall absehbar'}.get(health,'Unbekannt')))
        if 6 in row:metrics.append(metric('disk:'+index+':temp',name+' · Temperatur',row[6],'°C'))
    for index,row in snmp_table(raids,root+'.3.1.1').items():
        name=str(row.get(2) or index);state=row.get(3);summary=row.get(7)
        status=({1:'up',2:'critical',3:'critical',4:'critical',5:'warning'}.get(summary,'unknown') if summary is not None else
                'up' if state==1 else 'critical' if state in (11,12) else 'warning' if state in range(2,21) else 'unknown')
        metrics.append(metric('raid:'+index,name+' · RAID',summary if summary is not None else state,'',status,
            ('Speicherzustand '+str(summary)) if summary is not None else {1:'Normal',11:'Degradiert',12:'Ausgefallen / schreibgeschützt',13:'Datenprüfung'}.get(state,'RAID-Aufgabe / Zustand '+str(state))))
    if not disks:metrics.append(metric('disks:missing','Laufwerke',None,status='unknown',message='Synology-Laufwerks-MIB fehlt. SNMP-Freigabe prüfen.'))
    if not raids:metrics.append(metric('raids:missing','RAID',None,status='unknown',message='Synology-RAID-MIB fehlt oder kein Speicherpool vorhanden.'))
    return metrics


def ups_metrics(data):
    root='.1.3.6.1.2.1.33.1';get=lambda suffix:data.get(root+'.'+suffix)
    battery=get('2.1.0');source=get('4.1.0');alarms=get('6.1.0')
    result=[metric('battery-state','Batteriezustand',battery,'',{2:'up',3:'warning',4:'critical'}.get(battery,'unknown'),
             {2:'Normal',3:'Batterie niedrig',4:'Batterie erschöpft'}.get(battery,'Nicht geliefert')),
            metric('source','Stromquelle',source,'',{2:'critical',3:'up',4:'warning',5:'warning',6:'up',7:'up'}.get(source,'unknown'),
             {2:'Keine Versorgung',3:'Netzbetrieb',4:'Bypass',5:'Batteriebetrieb',6:'Spannung angehoben',7:'Spannung abgesenkt'}.get(source,'Unbekannt'))]
    for suffix,key,label,unit in [('2.4.0','charge','Batterieladung','%'),('2.3.0','runtime','Restlaufzeit','Minuten'),('2.7.0','temperature','Batterietemperatur','°C')]:
        if get(suffix) is not None:result.append(metric(key,label,get(suffix),unit))
    if alarms is not None:result.append(metric('alarms','Aktive USV-Alarme',alarms,'','critical' if alarms>0 else 'up','Vom Gerät gemeldete Alarme'))
    for index,row in snmp_table(data,root+'.4.4.1').items():
        if 5 in row:result.append(metric('load:'+index,'Auslastung Ausgang '+index,row[5],'%',warn=80,critical=95))
    return result


def snmp_profile(kind,cfg,timeout):
    from .resources import config_text,run_walk,CheckError
    binary=shutil.which('snmpbulkwalk')
    if not binary:raise CheckFailure('Net-SNMP fehlt auf dem Monitoring-Server. Installer erneut ausführen.')
    target={**cfg,'device_address':cfg['host']};deadline=time.monotonic()+timeout
    try:
        with tempfile.TemporaryDirectory(prefix='netzmonitor-profile-') as directory:
            path=Path(directory)/'snmp.conf';path.write_text(config_text(target),encoding='utf-8');path.chmod(0o600)
            def walk(root):return run_walk(binary,target,root,directory,deadline)
            if kind=='synology':
                return synology_metrics(walk('.1.3.6.1.4.1.6574.1'),walk('.1.3.6.1.4.1.6574.2'),walk('.1.3.6.1.4.1.6574.3'))
            return ups_metrics(walk('.1.3.6.1.2.1.33.1'))
    except CheckError as exc:raise CheckFailure(str(exc))
