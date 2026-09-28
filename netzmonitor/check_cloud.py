"""Read-only Docker, Kubernetes, CloudWatch and Azure Monitor API collectors."""
import concurrent.futures
import datetime
import hashlib
import hmac
import json
import re
from urllib.parse import quote, urlencode, urlsplit

from .check_custom import HTTP
from .integration_common import CheckFailure, metric, numeric, xml, local, child, text_at


def identified(prefix, identity, name, value, unit='', **kwargs):
    return metric(prefix+':'+hashlib.sha256(identity.encode()).hexdigest()[:24],name,value,unit,**kwargs)


def docker(cfg,timeout):
    client=HTTP(cfg,timeout)
    info=client.json('/version')
    version=info.get('ApiVersion','')
    if not re.fullmatch(r'1\.[0-9]+',version):raise CheckFailure('Docker meldet keine gültige API-Version.')
    base='/v'+version
    containers=client.json(base+'/containers/json?all=true')
    if not isinstance(containers,list):raise CheckFailure('Docker liefert keine Containerliste.')
    selected=set(cfg['names']);expected=set(cfg['expected_running']);present=set()
    chosen=[]
    for row in containers:
        names=[n.lstrip('/') for n in row.get('Names',[])];ident=row.get('Id','')
        if not ident:continue
        present.update(names);present.add(ident)
        if selected and not ((selected|expected).intersection(names) or ident in selected or ident in expected):continue
        chosen.append((row,names[0] if names else ident[:12]))
    if len(chosen)>100:raise CheckFailure('Mehr als 100 Container. Auswahl auf mehrere Prüfungen aufteilen.')
    def collect(pair):
        row,name=pair;ident=row['Id'];state=row.get('State');values=[]
        prefix='container:'+ident+':'
        required=bool(expected.intersection([ident]+[n.lstrip('/') for n in row.get('Names',[])]))
        values.append(metric(prefix+'running',name+' · Betrieb',int(state=='running'),
            status='critical' if required and state!='running' else 'up',message=str(state)))
        try:
            http=HTTP(cfg,timeout)
            details=http.json(base+'/containers/'+quote(ident,safe='')+'/json')
            values.append(metric(prefix+'restarts',name+' · Neustarts',details.get('RestartCount'),'gesamt'))
            health=(details.get('State') or {}).get('Health') or {}
            if health:
                status=health.get('Status')
                values.append(metric(prefix+'health',name+' · Healthcheck',int(status=='healthy'),
                    status='up' if status=='healthy' else 'critical' if status=='unhealthy' else 'warning',message=str(status)))
            if state!='running':return values
            stats=http.json(base+'/containers/'+quote(ident,safe='')+'/stats?stream=false')
            cpu=stats.get('cpu_stats') or {};before=stats.get('precpu_stats') or {}
            total=numeric((cpu.get('cpu_usage') or {}).get('total_usage'));old=numeric((before.get('cpu_usage') or {}).get('total_usage'))
            system=numeric(cpu.get('system_cpu_usage'));previous=numeric(before.get('system_cpu_usage'))
            cores=numeric(cpu.get('online_cpus')) or len((cpu.get('cpu_usage') or {}).get('percpu_usage',[]))
            usage=100*(total-old)/(system-previous)*cores if None not in (total,old,system,previous) and system>previous and total>=old and cores else None
            values.append(metric(prefix+'cpu',name+' · CPU (100 % je Kern)',usage,'%'))
            mem=stats.get('memory_stats') or {};used=numeric(mem.get('usage'));limit=numeric(mem.get('limit'))
            values.append(metric(prefix+'memory',name+' · RAM',used/1024**2 if used is not None else None,'MiB'))
            values.append(metric(prefix+'memory-percent',name+' · RAM-Auslastung',100*used/limit if used is not None and limit else None,'%'))
            for interface,network in (stats.get('networks') or {}).items():
                for key in ('rx_bytes','tx_bytes','rx_errors','tx_errors','rx_dropped','tx_dropped'):
                    m=metric(prefix+interface+':'+key,name+' · '+interface+' · '+key,network.get(key),'B/s' if 'bytes' in key else '/s')
                    m.update(counter=True,counter_epoch=str((details.get('State') or {}).get('StartedAt','')));values.append(m)
            for entry in (stats.get('blkio_stats') or {}).get('io_service_bytes_recursive') or []:
                identity=str(entry.get('major'))+':'+str(entry.get('minor'))+':'+str(entry.get('op'))
                m=metric(prefix+'io:'+identity,name+' · I/O '+identity,entry.get('value'),'B/s')
                m.update(counter=True,counter_epoch=str((details.get('State') or {}).get('StartedAt','')));values.append(m)
        except CheckFailure as exc:
            values.append(metric(prefix+'missing',name+' · Messwerte',message=str(exc)))
        return values
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        result=[m for batch in pool.map(collect,chosen) for m in batch]
    for missing in expected-present:
        result.append(identified('missing',missing,missing+' · Betrieb',0,status='critical',message='Erwarteter Container fehlt.'))
    if not result:result=[metric('containers','Container',0)]
    return result


def quantity(value):
    match=re.fullmatch(r'([+-]?[0-9]+(?:\.[0-9]+)?)([eE][+-]?[0-9]+|[numkKMGTPE]|[KMGTPE]i)?',str(value or ''))
    if not match:return None
    number=float(match[1]);suffix=match[2] or ''
    if suffix.startswith(('e','E')) and len(suffix)>1:return number*10**int(suffix[1:])
    scales={'':1,'n':1e-9,'u':1e-6,'m':1e-3,'k':1e3,'K':1e3,'M':1e6,'G':1e9,'T':1e12,'P':1e15,'E':1e18}
    scales.update({letter+'i':1024**n for n,letter in enumerate('KMGTPE',1)})
    return number*scales[suffix]


def kubernetes(cfg,timeout):
    client=HTTP(cfg,timeout);result=[]
    def listing(path):
        rows=[];next_token=''
        for _ in range(20):
            page=client.json(path+'?'+urlencode({'limit':200,'continue':next_token}))
            rows.extend(page.get('items',[]));next_token=(page.get('metadata') or {}).get('continue','')
            if len(rows)>2000:raise CheckFailure('Mehr als 2.000 Kubernetes-Objekte. Namespace eingrenzen.')
            if not next_token:return rows
        raise CheckFailure('Kubernetes-Auswahl ist zu umfangreich.')
    if not cfg['namespace']:
        for node in listing('/api/v1/nodes'):
            name=node['metadata']['name'];status=node.get('status') or {}
            ready=next((c.get('status') for c in status.get('conditions',[]) if c.get('type')=='Ready'),None)
            result.append(metric('node:'+name+':ready',name+' · Bereit',None if ready is None else int(ready=='True'),
                                 status='unknown' if ready is None else 'up' if ready=='True' else 'critical'))
            for condition in status.get('conditions',[]):
                if condition.get('type') in ('MemoryPressure','DiskPressure','PIDPressure','NetworkUnavailable'):
                    known=condition.get('status') in ('True','False');bad=condition.get('status')=='True'
                    result.append(metric('node:'+name+':'+condition['type'],name+' · '+condition['type'],int(bad) if known else None,status='unknown' if not known else 'warning' if bad else 'up'))
    base='/api/v1'+('/namespaces/'+quote(cfg['namespace'],safe='') if cfg['namespace'] else '')
    for pod in listing(base+'/pods'):
        meta=pod['metadata'];identity=meta['namespace']+'/'+meta['name'];status=pod.get('status') or {};phase=status.get('phase')
        containers=status.get('containerStatuses') or [];ready=bool(containers) and all(c.get('ready') for c in containers)
        result.append(metric('pod:'+identity+':ready',identity+' · Bereit',int(ready),
            status='up' if ready or phase=='Succeeded' else 'critical' if phase=='Failed' else 'warning',message=str(phase)))
        result.append(metric('pod:'+identity+':restarts',identity+' · Neustarts',sum(c.get('restartCount',0) for c in containers),'gesamt'))
    if cfg['metrics_api']:
        for kind in ('nodes','pods'):
            if kind=='nodes' and cfg['namespace']:continue
            suffix=('/namespaces/'+quote(cfg['namespace'],safe='') if cfg['namespace'] and kind=='pods' else '')+'/'+kind
            try:
                # v1beta1 remains available on established clusters. Try stable
                # v1 first where present, without changing the cluster.
                code,raw,_=client.request('/apis/metrics.k8s.io/v1'+suffix)
                data=json.loads(raw) if code==200 else client.json('/apis/metrics.k8s.io/v1beta1'+suffix)
                for row in data.get('items',[]):
                    meta=row['metadata'];identity=(meta.get('namespace','')+'/').lstrip('/')+meta['name']
                    entries=row.get('containers') if kind=='pods' else [dict(name='',usage=row.get('usage',{}))]
                    for item in entries or []:
                        name=identity+('/'+item['name'] if item['name'] else '');usage=item.get('usage') or {}
                        for key,unit,scale in [('cpu','Kerne',1),('memory','MiB',1024**2)]:
                            value=quantity(usage.get(key))
                            result.append(metric('usage:'+kind+':'+name+':'+key,name+' · '+key,value/scale if value is not None else None,unit))
            except (CheckFailure,ValueError):
                result.append(metric('missing:metrics:'+kind,'Kubernetes Metrics API · '+kind,message='Metrics API nicht verfügbar oder Leserecht fehlt.'))
    return result or [metric('objects','Kubernetes-Objekte',0)]


def aws_request(cfg,action,params,timeout):
    now=datetime.datetime.now(datetime.timezone.utc);date=now.strftime('%Y%m%d');stamp=now.strftime('%Y%m%dT%H%M%SZ')
    payload=urlencode({'Action':action,'Version':'2010-08-01',**params}).encode()
    headers={'content-type':'application/x-www-form-urlencoded; charset=utf-8','host':cfg['host'],'x-amz-date':stamp}
    if cfg.get('session_token'):headers['x-amz-security-token']=cfg['session_token']
    names=';'.join(sorted(headers));canonical=''.join(k+':'+headers[k].strip()+'\n' for k in sorted(headers))
    request='POST\n/\n\n'+canonical+'\n'+names+'\n'+hashlib.sha256(payload).hexdigest()
    scope=date+'/'+cfg['region']+'/monitoring/aws4_request'
    to_sign='AWS4-HMAC-SHA256\n'+stamp+'\n'+scope+'\n'+hashlib.sha256(request.encode()).hexdigest()
    key=('AWS4'+cfg['secret_key']).encode()
    for part in (date,cfg['region'],'monitoring','aws4_request'):key=hmac.new(key,part.encode(),hashlib.sha256).digest()
    headers['Authorization']='AWS4-HMAC-SHA256 Credential='+cfg['access_key']+'/'+scope+', SignedHeaders='+names+', Signature='+hmac.new(key,to_sign.encode(),hashlib.sha256).hexdigest()
    code,raw,_=HTTP(cfg,timeout).request('/','POST',payload,headers)
    if code!=200:raise CheckFailure('CloudWatch-Abfrage fehlgeschlagen (HTTP '+str(code)+'). IAM-Rechte, Region und Systemzeit prüfen.')
    return xml(raw)


def aws(cfg,timeout):
    params={'Namespace':cfg['namespace']}
    for n,d in enumerate(cfg['dimensions'],1):params.update({f'Dimensions.member.{n}.Name':d['name'],f'Dimensions.member.{n}.Value':d['value']})
    selected=[];token=''
    for _ in range(10):
        page=aws_request(cfg,'ListMetrics',dict(params,**({'NextToken':token} if token else {})),timeout)
        for node in page.iter():
            if local(node.tag)!='Metrics':continue
            for row in node:
                name=text_at(row,'MetricName');namespace=text_at(row,'Namespace');dims=child(row,'Dimensions')
                if cfg['names'] and name not in cfg['names']:continue
                selected.append(dict(name=name,namespace=namespace,dimensions=[(text_at(d,'Name'),text_at(d,'Value')) for d in dims] if dims is not None else []))
        token=next((n.text for n in page.iter() if local(n.tag)=='NextToken'),'')
        if len(selected)>200:raise CheckFailure('Mehr als 200 CloudWatch-Messreihen. Namen oder Dimensionsfilter eingrenzen.')
        if not token:break
    if token:raise CheckFailure('CloudWatch-Auswahl ist zu umfangreich.')
    if not selected:raise CheckFailure('Keine passenden CloudWatch-Messreihen gefunden.')
    end=datetime.datetime.now(datetime.timezone.utc);start=end-datetime.timedelta(minutes=15)
    args={'StartTime':start.isoformat(),'EndTime':end.isoformat(),'ScanBy':'TimestampDescending'}
    labels={}
    for n,row in enumerate(selected,1):
        prefix=f'MetricDataQueries.member.{n}.';ident='m'+str(n)
        args.update({prefix+'Id':ident,prefix+'ReturnData':'true',prefix+'MetricStat.Period':'60',prefix+'MetricStat.Stat':cfg['statistic'],
                     prefix+'MetricStat.Metric.Namespace':row['namespace'],prefix+'MetricStat.Metric.MetricName':row['name']})
        for i,(name,value) in enumerate(row['dimensions'],1):args.update({prefix+f'MetricStat.Metric.Dimensions.member.{i}.Name':name,prefix+f'MetricStat.Metric.Dimensions.member.{i}.Value':value})
        labels[ident]=row['name']+' · '+', '.join(name+'='+value for name,value in row['dimensions'])
    page=aws_request(cfg,'GetMetricData',args,timeout);result=[]
    for node in page.iter():
        if local(node.tag)!='MetricDataResults':continue
        for row in node:
            ident=text_at(row,'Id');values=child(row,'Values');timestamps=child(row,'Timestamps')
            value=next(iter(values)).text if values is not None and len(values) else None
            stamp=next(iter(timestamps)).text if timestamps is not None and len(timestamps) else ''
            label=labels.get(ident,ident or '?')
            result.append(identified('aws',label,label,value,message='CloudWatch · '+stamp if value is not None else 'Kein aktueller CloudWatch-Wert.'))
    return result


def azure(cfg,timeout):
    login=dict(host='login.microsoftonline.com',port=443)
    auth=HTTP(login,timeout).json('/'+cfg['tenant_id']+'/oauth2/v2.0/token','POST',urlencode({
        'grant_type':'client_credentials','client_id':cfg['client_id'],'client_secret':cfg['client_secret'],
        'scope':'https://management.azure.com/.default'}).encode(),{'Content-Type':'application/x-www-form-urlencoded'})
    token=auth.get('access_token')
    if not token:raise CheckFailure('Azure-Anmeldung liefert kein Zugriffstoken.')
    client=HTTP(dict(host='management.azure.com',port=443,token=token),timeout)
    prefix='/subscriptions/'+cfg['subscription_id']
    if cfg['resource_id']:
        if not cfg['resource_id'].lower().startswith(prefix.lower()+'/'):raise CheckFailure('Azure-Ressource gehört nicht zur gewählten Subscription.')
        resources=[dict(id=cfg['resource_id'],name=cfg['resource_id'].rsplit('/',1)[-1])]
    else:
        path=prefix+('/resourceGroups/'+quote(cfg['resource_group'],safe='') if cfg['resource_group'] else '')+'/resources?api-version=2021-04-01'
        resources=[]
        for _ in range(10):
            data=client.json(path);resources.extend(data.get('value',[]));link=data.get('nextLink')
            if len(resources)>100:raise CheckFailure('Mehr als 100 Azure-Ressourcen. Ressourcengruppe oder Ressourcen-ID eingrenzen.')
            if not link:break
            target=urlsplit(link)
            if target.scheme!='https' or target.hostname!='management.azure.com':raise CheckFailure('Ungültiger Azure-Folgeverweis.')
            path=target.path+'?'+target.query
        if link:raise CheckFailure('Azure-Auswahl ist zu umfangreich.')
    result=[];end=datetime.datetime.now(datetime.timezone.utc);start=end-datetime.timedelta(minutes=15)
    for resource in resources:
        identity=resource['id'];name=resource['name'];base=identity+'/providers/Microsoft.Insights/'
        try:
            definitions=client.json(base+'metricDefinitions?api-version=2018-01-01').get('value',[])
            if cfg['names']:definitions=[d for d in definitions if d.get('name',{}).get('value') in cfg['names']]
            if len(definitions)>50:raise CheckFailure('Mehr als 50 Metriken je Ressource. Messwertnamen eingrenzen.')
            for definition in definitions:
                key=definition['name']['value'];aggregation=definition.get('primaryAggregationType') or 'Average'
                args={'api-version':'2023-10-01','metricnames':key,'aggregation':aggregation,'interval':'PT1M',
                      'timespan':start.isoformat()+'/'+end.isoformat(),'AutoAdjustTimegrain':'true'}
                data=client.json(base+'metrics?'+urlencode(args))
                found=False
                for item in data.get('value',[]):
                    for series in item.get('timeseries',[]):
                        records=[p for p in series.get('data',[]) if p.get(aggregation.lower()) is not None]
                        dimensions=', '.join(str(d.get('name',{}).get('value'))+'='+str(d.get('value')) for d in series.get('metadatavalues',[]))
                        record=max(records,key=lambda p:p.get('timeStamp','')) if records else {}
                        label=name+' · '+key+(' · '+dimensions if dimensions else '')
                        result.append(identified('azure',identity+key+dimensions,label,record.get(aggregation.lower()),item.get('unit',''),
                                      message='Azure Monitor · '+record.get('timeStamp','') if record else 'Kein aktueller Azure-Messwert.'));found=True
                if not found:result.append(identified('azure',identity+key,name+' · '+key,None,message='Keine Messreihe verfügbar.'))
        except CheckFailure as exc:
            result.append(identified('missing',identity,name+' · Azure Monitor',None,message=str(exc)))
    return result or [metric('resources','Azure-Ressourcen',len(resources),message='Keine Ressourcen mit passenden Messwerten.')]


def check_cloud(kind,cfg,timeout):
    return {'docker':docker,'kubernetes':kubernetes,'aws':aws,'azure':azure}[kind](cfg,timeout)
