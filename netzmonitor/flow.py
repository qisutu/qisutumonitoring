"""Bounded passive NetFlow v5/v9 and IPFIX UDP collector. No packet capture."""
from collections import Counter, OrderedDict
import hashlib
import ipaddress
import json
import select
import socket
import struct
import threading
import time
from .integration_common import CheckFailure, metric


class FlowParser:
    def __init__(self):
        self.templates = OrderedDict()
        self.streams = OrderedDict()

    def parse(self, data, session, now=None):
        now = time.monotonic() if now is None else now
        while self.templates and next(iter(self.templates.values()))[0] < now-1800:
            self.templates.popitem(last=False)
        if len(data)<2: raise ValueError('Kurzes Datagramm')
        version = struct.unpack_from('!H',data)[0]
        if version==5:
            if len(data)<24: raise ValueError('Kurzer NetFlow-v5-Header')
            count = struct.unpack_from('!H',data,2)[0]
            if not 1<=count<=30 or len(data)!=24+count*48: raise ValueError('Ungültige NetFlow-v5-Länge')
            flows=[]
            for offset in range(24,len(data),48):
                packets,octets = struct.unpack_from('!II',data,offset+16)
                sport,dport = struct.unpack_from('!HH',data,offset+32)
                flows.append((str(ipaddress.ip_address(data[offset:offset+4])),str(ipaddress.ip_address(data[offset+4:offset+8])),
                              data[offset+38],sport,dport,octets,packets))
            sampling=struct.unpack_from('!H',data,22)[0]&0x3fff
            return flows, ('Stichprobenexport erkannt; nur exportierte Zähler, keine Hochrechnung.' if sampling>1 else '')
        if version not in (9,10): raise ValueError('Erwartet NetFlow v5/v9 oder IPFIX')
        header = 20 if version==9 else 16
        if len(data)<header: raise ValueError('Kurzer Export-Header')
        if version==10 and struct.unpack_from('!H',data,2)[0]!=len(data): raise ValueError('Ungültige IPFIX-Länge')
        domain=struct.unpack_from('!I',data,16 if version==9 else 12)[0]
        stream=(session,version,domain)
        exported=struct.unpack_from('!I',data,8 if version==9 else 4)[0]
        counter=struct.unpack_from('!I',data,4 if version==9 else 8)[0]
        previous=self.streams.get(stream)
        # A reboot must not decode fresh data with stale templates from the old
        # process. Ignore ordinary out-of-order datagrams and counter rollover.
        if previous and exported>previous[0] and counter<previous[1] and previous[1]-counter<0x80000000:
            for key in list(self.templates):
                if key[:3]==stream:del self.templates[key]
        if not previous or exported>=previous[0]:
            self.streams[stream]=(exported,counter);self.streams.move_to_end(stream)
        while len(self.streams)>1024:self.streams.popitem(last=False)
        flows=[]; warning=''; offset=header
        while offset<len(data):
            if offset+4>len(data): raise ValueError('Unvollständiger FlowSet-Header')
            sid,length=struct.unpack_from('!HH',data,offset)
            if length<4 or offset+length>len(data): raise ValueError('Ungültige FlowSet-Länge')
            body=data[offset+4:offset+length];offset+=length
            if sid==(0 if version==9 else 2):
                pos=0
                while pos+4<=len(body):
                    tid,count=struct.unpack_from('!HH',body,pos);pos+=4
                    if tid<256 or not 1<=count<=128: raise ValueError('Ungültige UDP-Vorlage')
                    fields=[]
                    for _ in range(count):
                        if pos+4>len(body): raise ValueError('Unvollständige Vorlage')
                        ident,size=struct.unpack_from('!HH',body,pos);pos+=4
                        enterprise=version==10 and bool(ident&0x8000)
                        if enterprise:
                            if pos+4>len(body): raise ValueError('Unvollständiges Enterprise-Feld')
                            pos+=4
                        if size==0: raise ValueError('Leeres Vorlagenfeld')
                        fields.append((None if enterprise else ident,size))
                    key=(session,version,domain,tid)
                    self.templates[key]=(now,fields);self.templates.move_to_end(key)
                    while len(self.templates)>2048:self.templates.popitem(last=False)
                if any(body[pos:]): raise ValueError('Ungültiges Vorlagen-Padding')
            elif sid in (1,3):
                # Remember option-template IDs so their later data sets are not mistaken
                # for traffic without a template. Sampling is not extrapolated.
                pos=0
                while pos+6<=len(body):
                    tid,a,b=struct.unpack_from('!HHH',body,pos);pos+=6
                    if tid<256:raise ValueError('Ungültige Optionsvorlage')
                    if version==9:
                        if (a+b)%4 or pos+a+b>len(body):raise ValueError('Ungültige Optionslänge')
                        pos+=a+b
                    else:
                        if not 1<=a<=128 or not 1<=b<=a:raise ValueError('Ungültiger Optionsumfang')
                        for _ in range(a):
                            if pos+4>len(body):raise ValueError('Unvollständige Optionsvorlage')
                            ident,size=struct.unpack_from('!HH',body,pos);pos+=4
                            if ident&0x8000:pos+=4
                            if pos>len(body) or not size:raise ValueError('Ungültiges Optionsfeld')
                    key=(session,version,domain,tid)
                    self.templates[key]=(now,None);self.templates.move_to_end(key)
                    while len(self.templates)>2048:self.templates.popitem(last=False)
                if len(body)-pos>3 or any(body[pos:]):raise ValueError('Ungültiges Options-Padding')
            elif sid>=256:
                tpl=self.templates.get((session,version,domain,sid))
                if tpl is None:
                    warning='Daten ohne passende Vorlage empfangen. Vorlagenexport am Router aktivieren (höchstens 60 Sekunden).'
                    continue
                if tpl[1] is None:continue
                fields=tpl[1];pos=0;minimum=sum(1 if size==65535 else size for _,size in fields)
                while len(body)-pos>=minimum:
                    values={}
                    for ident,size in fields:
                        if size==65535:
                            if pos>=len(body): raise ValueError('Variable Feldlänge fehlt')
                            size=body[pos];pos+=1
                            if size==255:
                                if pos+2>len(body): raise ValueError('Variable Feldlänge abgeschnitten')
                                size=struct.unpack_from('!H',body,pos)[0];pos+=2
                        if pos+size>len(body): raise ValueError('Unvollständiger Flow-Datensatz')
                        if ident in (1,2,4,7,8,11,12,27,28): values[ident]=body[pos:pos+size]
                        pos+=size
                    src=values.get(8) or values.get(27);dst=values.get(12) or values.get(28)
                    if not src or not dst or len(src) not in (4,16) or len(dst)!=len(src) or not values.get(1) or not values.get(2):
                        warning='Exportvorlage benötigt Quell-/Ziel-IP sowie octetDeltaCount und packetDeltaCount (Byte-/Paket-Deltazähler).';continue
                    if any(len(v)>8 for k,v in values.items() if k not in (8,12,27,28)): raise ValueError('Zählerfeld zu groß')
                    number=lambda k:int.from_bytes(values.get(k,b'\0'),'big')
                    if number(4)>255 or number(7)>65535 or number(11)>65535: raise ValueError('Ungültiges Protokoll/Port')
                    flows.append((str(ipaddress.ip_address(src)),str(ipaddress.ip_address(dst)),number(4),number(7),number(11),number(1),number(2)))
                if len(body)-pos>3 or any(body[pos:]): raise ValueError('Unvollständiger Flow-Datensatz')
        return flows,warning


class FlowBuffer:
    def __init__(self):
        self.buckets={};self.last_packet=0;self.last_data=0;self.first=0;self.message='';self.seen=OrderedDict()

    def prune(self,now):
        self.buckets={k:v for k,v in self.buckets.items() if k>=int((now-3600)//60)*60}
        self.seen=OrderedDict((k,v) for k,v in self.seen.items() if v>=now-120)

    def add(self,data,flows,warning,now):
        digest=hashlib.sha256(data).digest()
        if digest in self.seen and self.seen[digest]>now-120:return
        self.seen[digest]=now
        while len(self.seen)>512:self.seen.popitem(last=False)
        self.last_packet=now;self.message=warning
        self.prune(now)
        if not flows:return
        self.last_data=now
        if not self.first:self.first=now
        bucket=self.buckets.setdefault(int(now//60)*60,{'flows':Counter(),'bytes':0,'packets':0,'overflow':0})
        count=sum(len(b['flows']) for b in self.buckets.values())
        for src,dst,proto,sport,dport,octets,packets in flows:
            bucket['bytes']+=octets;bucket['packets']+=packets
            key=(src,dst,proto,sport,dport)
            if key not in bucket['flows'] and count>=20000:bucket['overflow']+=1;continue
            if key not in bucket['flows']:count+=1
            bucket['flows'][key]+=octets

    def result(self,cfg,now):
        duration=cfg['window_minutes']*60
        # Whole minute buckets make the displayed rolling window stable and bounded.
        cutoff=int(now//60)*60-duration+60
        buckets=[b for stamp,b in self.buckets.items() if stamp>=cutoff]
        if not self.last_data or self.last_data<cutoff:
            return dict(kind='error',metrics=[],message=self.message or 'Noch keine aktuellen Flussdaten. Exportziel, Quell-IP, UDP-Freigabe und Vorlagenexport prüfen.')
        traffic=sum(b['bytes'] for b in buckets);packets=sum(b['packets'] for b in buckets)
        elapsed=max(1,now-max(cutoff,self.first))
        total=Counter()
        for b in buckets:total.update(b['flows'])
        sources=Counter();destinations=Counter();protocols=Counter()
        for (src,dst,proto,sport,dport),octets in total.items():
            sources[src]+=octets;destinations[dst]+=octets;protocols[proto]+=octets
        note='Exportierte Zähler der letzten %s Minuten (Minutenraster); keine Sampling-Hochrechnung.' % cfg['window_minutes']
        metrics=[metric('traffic','Exportiertes Datenvolumen',traffic/1024**2,'MiB',message=note),
                 metric('rate','Datenrate nach Empfangszeit',traffic*8/elapsed/1e6,'Mbit/s',message='Mittelwert im Empfangsfenster; Exportverzögerung beeinflusst diesen Wert.'),
                 metric('packets','Exportierte Pakete',packets,'Pakete'),
                 metric('age','Letzter Datensatz vor',now-self.last_data,'s')]
        for prefix,label,counter in [('src','Quelle',sources),('dst','Ziel',destinations),('protocol','Protokoll',protocols)]:
            for key,value in counter.most_common(10):
                name={6:'TCP',17:'UDP',1:'ICMP',58:'ICMPv6'}.get(key,str(key)) if prefix=='protocol' else key
                metrics.append(metric(prefix+':'+str(key),label+' · '+name,value/1024**2,'MiB',message='Anteil am exportierten Volumen: %.1f %%' % (100*value/traffic if traffic else 0)))
        for (src,dst,proto,sport,dport),value in total.most_common(10):
            key='%s|%s|%s|%s|%s' % (src,dst,proto,sport,dport)
            metrics.append(metric('connection:'+key,'Verbindung · [%s]:%s → [%s]:%s' % (src,sport,dst,dport),value/1024**2,'MiB',message={6:'TCP',17:'UDP',1:'ICMP',58:'ICMPv6'}.get(proto,'IP-Protokoll '+str(proto))))
        if self.message:metrics.append(metric('export-note','Exporthinweis',None,status='warning',message=self.message))
        if any(b['overflow'] for b in buckets):metrics.append(metric('limit','Verursacherauswertung unvollständig',None,status='unknown',message='Mehr als 20.000 Verbindungen pro Exporter. Gesamtvolumen erfasst; Top-Listen unvollständig. Exportbereich einschränken.'))
        return dict(kind='ok',metrics=metrics,message='',inventory=[])


class FlowCollector:
    def __init__(self,store):
        self.store=store;self.lock=threading.RLock();self.stopping=threading.Event()
        self.buffers={};self.tests={};self.errors={};self.sockets={};self.parser=FlowParser()
        self.thread=threading.Thread(target=self.loop,name='flow-collector',daemon=True)

    def start(self):
        self.refresh()
        self.thread.start()

    def close(self):
        self.stopping.set()
        if self.thread.is_alive():self.thread.join(5)

    def subscriptions(self):
        self.store.refresh_license_access()
        licensed={r['id'] for r in self.store.rows('SELECT id FROM devices WHERE license_blocked=0')}
        rows=self.store.rows("SELECT i.config FROM integration_targets i JOIN devices d ON d.id=i.device_id WHERE i.kind='flow' AND i.enabled=1 AND d.enabled=1 AND d.blocked=0 AND d.license_blocked=0")
        keys={(c['host'],c['port']) for c in (json.loads(r['config']) for r in rows)}
        with self.lock:
            now=time.monotonic();self.tests={k:v for k,v in self.tests.items() if v>now and k[2] in licensed}
            return keys|{k[:2] for k in self.tests}

    def refresh(self):
        wanted=self.subscriptions()
        endpoints={(socket.AF_INET6 if ':' in host else socket.AF_INET,port) for host,port in wanted}
        with self.lock:
            self.buffers={k:v for k,v in self.buffers.items() if k in wanted}
            for key in wanted:self.buffers.setdefault(key,FlowBuffer())
            for buffer in self.buffers.values():buffer.prune(time.time())
            self.errors={k:v for k,v in self.errors.items() if k in endpoints}
            for endpoint in list(self.sockets):
                if endpoint not in endpoints:self.sockets.pop(endpoint).close();self.errors.pop(endpoint,None)
            for endpoint in sorted(endpoints):
                if endpoint in self.sockets:continue
                family,port=endpoint;sock=None
                try:
                    sock=socket.socket(family,socket.SOCK_DGRAM)
                    if family==socket.AF_INET6:sock.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
                    sock.bind(('::' if family==socket.AF_INET6 else '0.0.0.0',port));sock.setblocking(False)
                    self.sockets[endpoint]=sock;self.errors.pop(endpoint,None)
                except OSError:
                    if sock:sock.close()
                    self.errors[endpoint]='UDP-Empfangsport %s nicht verfügbar. Portbelegung und Berechtigung prüfen.' % port

    def loop(self):
        refreshed=0
        try:
            while not self.stopping.is_set():
                if time.monotonic()-refreshed>=1:
                    try:self.refresh()
                    except Exception:
                        # A transient SQLite lock must not terminate passive reception.
                        self.stopping.wait(.2);continue
                    refreshed=time.monotonic()
                sockets=list(self.sockets.values())
                if not sockets:self.stopping.wait(.1);continue
                ready,_,_=select.select(sockets,[],[],.2)
                for sock in ready:
                    for _ in range(100):
                        try:data,source=sock.recvfrom(65535)
                        except BlockingIOError:break
                        port=sock.getsockname()[1];host=str(ipaddress.ip_address(source[0]));key=(host,port)
                        with self.lock:
                            buf=self.buffers.get(key)
                            if buf is None:continue
                            try:
                                flows,warning=self.parser.parse(data,(host,source[1],port))
                                buf.add(data,flows,warning,time.time())
                            except (ValueError,struct.error):buf.message='Nicht unterstützte oder unvollständige Flussdaten. NetFlow v5/v9 oder IPFIX mit IP-Adressen und Byte-Deltazählern aktivieren.'
        finally:
            for sock in self.sockets.values():sock.close()
            self.sockets.clear()

    def probe(self,target):
        cfg=json.loads(target['config']) if isinstance(target['config'],str) else target['config']
        key=(cfg['host'],cfg['port']);endpoint=(socket.AF_INET6 if ':' in key[0] else socket.AF_INET,key[1])
        with self.lock:
            if endpoint in self.errors:return dict(kind='error',metrics=[],message=self.errors[endpoint])
            buf=self.buffers.get(key)
            if buf:return buf.result(cfg,time.time())
        return dict(kind='error',metrics=[],message='UDP-Empfang wird vorbereitet. Export am Router/Switch aktivieren und erneut prüfen.')

    def test(self,target):
        self.store.require_device_license(target.get('device_id'))
        cfg=json.loads(target['config']);key=(cfg['host'],cfg['port']);started=time.time()
        test_key=(*key,target['device_id'])
        timeout=target['timeout'];end=time.monotonic()+timeout
        with self.lock:
            if key not in self.buffers and len(self.buffers)+len(self.tests)>=64:
                raise ValueError('Maximal 64 Flussexporter gleichzeitig prüfen.')
            endpoints={((':' in h),p) for h,p in set(self.buffers)|{k[:2] for k in self.tests}|{key}}
            if len(endpoints)>16:raise ValueError('Maximal 16 UDP-Empfangsports gleichzeitig prüfen.')
            self.tests[test_key]=max(self.tests.get(test_key,0),end+2)
            self.errors.pop((socket.AF_INET6 if ':' in key[0] else socket.AF_INET,key[1]),None)
        try:
            while time.monotonic()<end and not self.stopping.is_set():
                self.store.require_device_license(target['device_id'])
                with self.lock:
                    buf=self.buffers.get(key)
                    fresh=buf and buf.last_data>=started
                if fresh:return self.probe(target)
                endpoint=(socket.AF_INET6 if ':' in key[0] else socket.AF_INET,key[1])
                if endpoint in self.errors:return self.probe(target)
                self.stopping.wait(.1)
            result=self.probe(target)
            return dict(kind='error',metrics=[],message='Im Verbindungstest keine neuen Flussdaten von %s empfangen. Router/Switch muss an die IP des Monitoring-Servers, UDP %s, exportieren. Aktiven Export und Vorlagenintervall auf 60 Sekunden setzen; bei Bedarf Antwortfrist auf 90 Sekunden erhöhen. %s' % (cfg['host'],cfg['port'],result.get('message','')))
        finally:
            with self.lock:
                if self.tests.get(test_key,0)<=end+2:self.tests.pop(test_key,None)
