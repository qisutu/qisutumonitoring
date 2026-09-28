"""vSphere performance-counter discovery and recent event retrieval."""
import datetime
from xml.sax.saxutils import escape
from .integration_common import CheckFailure, local, child, text_at, numeric, metric


def property_value(client, reference, path):
    typ,ident=client.refs[reference]
    body=client.reference('propertyCollector')+'<specSet><propSet><type>'+escape(typ)+'</type><all>false</all><pathSet>'+escape(path)+'</pathSet></propSet><objectSet><obj type="'+escape(typ)+'">'+escape(ident)+'</obj></objectSet></specSet><options/>'
    root=client.call('RetrievePropertiesEx',body)
    for item in root.iter():
        if local(item.tag)=='propSet' and text_at(item,'name')==path:
            return child(item,'val')
    raise CheckFailure('VMware-Eigenschaft nicht verfügbar: '+path)


def performance(client,objects,cfg):
    if 'perfManager' not in client.refs:raise CheckFailure('VMware PerformanceManager fehlt.')
    root=property_value(client,'perfManager','perfCounter');counters={}
    names={'usage','usagemhz','consumed','active','balloon','swapinRate','swapoutRate','numberReadAveraged','numberWriteAveraged',
           'read','write','totalReadLatency','totalWriteLatency','deviceReadLatency','deviceWriteLatency','kernelReadLatency',
           'kernelWriteLatency','received','transmitted','droppedRx','droppedTx','errorsRx','errorsTx'}
    for item in root:
        ident=text_at(item,'key');group=text_at(item,'groupInfo.key');name=text_at(item,'nameInfo.key');rollup=text_at(item,'rollupType')
        if ident and group in ('cpu','mem','disk','datastore','net') and name in names and rollup in ('average','summation','latest'):
            counters[ident]=(group+'.'+name+'.'+rollup,text_at(item,'unitInfo.key') or '')
    if not counters:raise CheckFailure('Keine passenden VMware-Leistungszähler verfügbar.')
    refs=[]
    for obj in objects:
        ref=child(obj,'obj')
        if ref is not None and ref.text:
            name=next((child(p,'val').text for p in obj if local(p.tag)=='propSet' and text_at(p,'name')=='name' and child(p,'val') is not None),ref.text)
            refs.append((ref.attrib.get('type'),ref.text,name))
    if len(refs)>cfg.get('performance_limit',50):raise CheckFailure('VMware-Objektzahl überschreitet die gewählte Leistungsgrenze. Auswahl aufteilen oder Grenze erhöhen.')
    result=[]
    for typ,ident,name in refs:
        try:
            summary=client.call('QueryPerfProviderSummary',client.reference('perfManager')+'<entity type="'+escape(typ)+'">'+escape(ident)+'</entity>')
            root=next((n for n in summary.iter() if local(n.tag)=='returnval'),None)
            current=text_at(root,'currentSupported')=='true'
            interval=int(numeric(text_at(root,'refreshRate')) or 20) if current else 300
            if not current and text_at(root,'summarySupported')!='true':raise CheckFailure('Keine Leistungsdaten für dieses Objekt.')
            body=client.reference('perfManager')+'<querySpec><entity type="'+escape(typ)+'">'+escape(ident)+'</entity><maxSample>1</maxSample>'
            body+=''.join('<metricId><counterId>'+key+'</counterId><instance>*</instance></metricId>' for key in counters)
            body+='<intervalId>'+str(interval)+'</intervalId><format>normal</format></querySpec>'
            response=client.call('QueryPerf',body);found=False
            for series in response.iter():
                if local(series.tag)!='value' or child(series,'id') is None:continue
                counter=text_at(series,'id.counterId');instance=text_at(series,'id.instance') or ''
                if counter not in counters:continue
                values=[numeric(n.text) for n in series if local(n.tag)=='value']
                value=next((n for n in reversed(values) if n is not None and n>=0),None)
                label,unit=counters[counter]
                if value is not None:
                    if unit=='percent':value/=100;unit='%'
                    elif unit=='kiloBytesPerSecond':value*=1024;unit='B/s'
                    elif unit=='kiloBytes':value*=1024;unit='B'
                    elif unit=='millisecond':unit='ms'
                result.append(metric('perf:'+typ+':'+ident+':'+counter+':'+instance,name+' · '+label+(' · '+instance if instance else ''),value,unit))
                found=True
            if not found:raise CheckFailure('VMware liefert für den Zeitraum keine Leistungsdaten.')
        except CheckFailure as exc:
            result.append(metric('missing:perf:'+ident,name+' · Leistungsdaten',message=str(exc)))
    return result


def events(client,cfg):
    if 'eventManager' not in client.refs:raise CheckFailure('VMware EventManager fehlt.')
    since=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(minutes=cfg.get('event_minutes',15))).isoformat()
    body=client.reference('eventManager')+'<filter><time><beginTime>'+since+'</beginTime></time><maxCount>100</maxCount></filter>'
    response=client.call('QueryEvents',body);rows=[]
    for event in response.iter():
        if local(event.tag)=='returnval':
            rows.append((text_at(event,'createdTime') or '',text_at(event,'fullFormattedMessage') or ''))
    rows.sort(reverse=True)
    return [metric('vmware:events','VMware-Ereignisse',len(rows),'Ereignisse',
                   message=('Mindestens 100 Ereignisse. ' if len(rows)>=100 else '')+'\n'.join(t+' · '+m for t,m in rows[:5]))]
