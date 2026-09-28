"""vSphere Web Services inventory and quick statistics with session cleanup."""
from xml.sax.saxutils import escape
from .integration_common import HTTPS, CheckFailure, local, metric, numeric, text_at, xml


class VSphere:
    def __init__(self, cfg, timeout):
        self.cfg, self.http = cfg, HTTPS(cfg,timeout)
        self.refs={};self.logged_in=False;self.view=None

    def call(self, method, body):
        payload=('''<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><soapenv:Body>
         <%s xmlns="urn:vim25">%s</%s></soapenv:Body></soapenv:Envelope>''' % (method,body,method)).encode('utf-8')
        return xml(self.http.request('/sdk','POST',payload,{'Content-Type':'text/xml; charset=utf-8','SOAPAction':'"urn:vim25/6.5"'}))

    def reference(self, key):
        if key not in self.refs: raise CheckFailure('vSphere liefert keine erforderliche Referenz: '+key)
        typ,ref=self.refs[key]
        return '<_this type="%s">%s</_this>' % (escape(typ),escape(ref))

    def connect(self):
        result=self.call('RetrieveServiceContent','<_this type="ServiceInstance">ServiceInstance</_this>')
        for n in result.iter():
            if local(n.tag) in ('sessionManager','propertyCollector','rootFolder','viewManager','perfManager','eventManager') and n.text:
                self.refs[local(n.tag)]=(n.attrib.get('type',''),n.text)
        self.call('Login',self.reference('sessionManager')+'<userName>'+escape(self.cfg['username'])+'</userName><password>'+escape(self.cfg['password'])+'</password>')
        self.logged_in=True

    def objects(self, types):
        result=self.call('CreateContainerView',self.reference('viewManager')+'<container type="Folder">'+escape(self.refs['rootFolder'][1])+'</container>'+''.join('<type>'+t+'</type>' for t in types)+'<recursive>true</recursive>')
        self.view=next((n.text for n in result.iter() if local(n.tag)=='returnval'),None)
        if not self.view: raise CheckFailure('vSphere-Inventar konnte nicht geöffnet werden.')
        body=self.reference('propertyCollector')+'<specSet>'+''.join('<propSet><type>'+t+'</type><all>false</all><pathSet>name</pathSet><pathSet>summary</pathSet></propSet>' for t in types)
        body+='<objectSet><obj type="ContainerView">'+escape(self.view)+'</obj><skip>true</skip><selectSet xsi:type="TraversalSpec"><name>viewTraversal</name><type>ContainerView</type><path>view</path><skip>false</skip></selectSet></objectSet></specSet><options><maxObjects>100</maxObjects></options>'
        result=self.call('RetrievePropertiesEx',body);objects=[];token=None
        try:
            for _ in range(100):
                for n in result.iter():
                    if local(n.tag)=='objects': objects.append(n)
                token=next((n.text for n in result.iter() if local(n.tag)=='token'),None)
                if len(objects)>5000:raise CheckFailure('Mehr als 5.000 vSphere-Objekte. Überwachung aufteilen.')
                if not token:return objects
                result=self.call('ContinueRetrievePropertiesEx',self.reference('propertyCollector')+'<token>'+escape(token)+'</token>')
            raise CheckFailure('vSphere-Inventar ist zu umfangreich.')
        finally:
            if token:
                try:self.call('CancelRetrievePropertiesEx',self.reference('propertyCollector')+'<token>'+escape(token)+'</token>')
                except Exception:pass

    def close(self):
        if self.view:
            try:self.call('DestroyView','<_this type="ContainerView">'+escape(self.view)+'</_this>')
            except Exception:pass
        if self.logged_in:
            try:self.call('Logout',self.reference('sessionManager'))
            except Exception:pass


def parse_objects(objects,cfg):
    metrics=[];inventory=[];expected=set(cfg['expected_running']);found=set()
    def limit(stem):return dict(warn=cfg[stem+'_warn'],critical=cfg[stem+'_crit'])
    for obj in objects:
        ref=next((n for n in obj if local(n.tag)=='obj'),None)
        if ref is None or not ref.text:continue
        props={}
        for p in obj:
            if local(p.tag)=='propSet':
                value=next((n for n in p if local(n.tag)=='val'),None)
                props[text_at(p,'name')]=value
        name=props['name'].text if props.get('name') is not None else ref.text
        s=props.get('summary');kind=ref.attrib.get('type');key=kind+':'+ref.text
        if s is None:
            metrics.append(metric(key,name,None,status='unknown',message='Zusammenfassung fehlt. vSphere-Leserechte prüfen.'));continue
        def num(path):return numeric(text_at(s,path))
        if kind=='HostSystem':
            connection=text_at(s,'runtime.connectionState');power=text_at(s,'runtime.powerState')
            status='unknown' if connection is None else 'up' if connection=='connected' and power=='poweredOn' else 'critical'
            metrics.append(metric(key+':state',name+' · Host',1 if status=='up' else 0,'',status,(connection or 'Unbekannt')+' / '+(power or 'Unbekannt')))
            cpu=num('quickStats.overallCpuUsage');mhz=num('hardware.cpuMhz');cores=num('hardware.numCpuCores')
            metrics.append(metric(key+':cpu',name+' · CPU',100*cpu/(mhz*cores) if cpu is not None and mhz and cores else None,'%',**limit('cpu')))
            ram=num('quickStats.overallMemoryUsage');total=num('hardware.memorySize')
            metrics.append(metric(key+':ram',name+' · Arbeitsspeicher',100*ram*1024*1024/total if ram is not None and total else None,'%',**limit('ram')))
        elif kind=='VirtualMachine':
            inventory.append(dict(id=ref.text,name=name));found|={ref.text,name}
            power=text_at(s,'runtime.powerState');required=ref.text in expected or name in expected
            status='unknown' if power is None else 'critical' if required and power!='poweredOn' else 'up'
            metrics.append(metric(key+':power',name+' · Betrieb',1 if power=='poweredOn' else 0 if power else None,'',status,
                (power or 'Unbekannt')+(' · Betrieb erwartet' if required else ' · Zustand zur Information')))
            active=power=='poweredOn';cpu=num('quickStats.overallCpuUsage');ram=num('quickStats.guestMemoryUsage');total=num('config.memorySizeMB')
            metrics.append(metric(key+':cpu',name+' · CPU-Nutzung',cpu if active else None,'MHz',status=None if active else 'up',message='' if active else 'VM ausgeschaltet; keine Leistungswerte.'))
            metrics.append(metric(key+':ram',name+' · Aktiver Gast-RAM',100*ram/total if active and ram is not None and total else None,'%',
                status=None if active else 'up',message='' if active else 'VM ausgeschaltet; keine Leistungswerte.',**limit('ram')))
            health=text_at(s,'overallStatus')
            metrics.append(metric(key+':health',name+' · vSphere-Zustand',None,'',
                {'green':'up','yellow':'warning','red':'critical','gray':'up' if not active else 'unknown'}.get(health,'up' if power=='poweredOff' and health is None else 'unknown'),health or ('VM ausgeschaltet; kein Gesundheitszustand geliefert.' if power=='poweredOff' else 'Nicht geliefert')))
        elif kind=='Datastore':
            accessible=text_at(s,'accessible');capacity=num('capacity');free=num('freeSpace')
            metrics.append(metric(key+':access',name+' · Datenspeicher',1 if accessible=='true' else 0,'','up' if accessible=='true' else 'critical','Erreichbar' if accessible=='true' else 'Nicht erreichbar'))
            metrics.append(metric(key+':space',name+' · Belegung',100*(capacity-free)/capacity if accessible=='true' and capacity and free is not None else None,'%',**limit('disk')))
    for name in expected-found:
        metrics.append(metric('missing-vm:'+name,'Erwartete VM '+name,None,status='critical',message='Erwartete VM wurde nicht gefunden.'))
    return metrics,inventory


def vmware_check(cfg,timeout):
    client=VSphere(cfg,timeout)
    try:
        client.connect()
        types=[typ for flag,typ in [('hosts','HostSystem'),('vms','VirtualMachine'),('datastores','Datastore')] if cfg[flag]]
        objects=client.objects(types)
        metrics,inventory=parse_objects(objects,cfg)
        from .vmware_extended import performance, events
        for flag, action in [('performance',performance),('events',events)]:
            if cfg.get(flag):
                try:metrics.extend(action(client,objects,cfg) if flag=='performance' else action(client,cfg))
                except CheckFailure as exc:metrics.append(metric('missing:'+flag,'VMware · '+flag,message=str(exc)))
        if not metrics:raise CheckFailure('Keine überwachten vSphere-Objekte sichtbar. Berechtigungen und Auswahl prüfen.')
        return metrics,inventory
    finally:client.close()
