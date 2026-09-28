"""Bounded HTTP, SSH, SNMP and exporter checks configured through typed forms."""
import base64
import hashlib
import http.client
import http.cookiejar
import json
import re
import shlex
import shutil
import ssl
import tempfile
import time
from pathlib import Path
from urllib.parse import quote, urlsplit, urlencode, urljoin
from urllib.request import Request

from .integration_common import CheckFailure, metric, numeric, tls_context, verify_pin


class HTTP:
    def __init__(self, cfg, timeout):
        self.cfg, self.timeout = cfg, timeout
        self.jar = http.cookiejar.CookieJar()

    def request(self, path, method='GET', body=None, headers=None, redirects=5):
        scheme = self.cfg.get('scheme', 'https')
        host = self.cfg['host']
        authority = ('[' + host + ']' if ':' in host else host) + ':' + str(self.cfg['port'])
        origin = scheme + '://' + authority
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or not path.startswith('/') or path.startswith('//') or '\\' in path or any(ord(c)<32 for c in path):
            raise CheckFailure('Ungültiger Pfad zur Schnittstelle.')
        context = tls_context(self.cfg)
        with tempfile.TemporaryDirectory(prefix='qisutu-tls-') as directory:
            if self.cfg.get('client_cert') or self.cfg.get('client_key'):
                if not self.cfg.get('client_cert') or not self.cfg.get('client_key'):
                    raise CheckFailure('Client-Zertifikat und Client-Schlüssel gemeinsam angeben.')
                cert, key = Path(directory)/'cert.pem', Path(directory)/'key.pem'
                cert.write_text(self.cfg['client_cert']);key.write_text(self.cfg['client_key']);key.chmod(0o600)
                context.load_cert_chain(str(cert),str(key))
            connection = http.client.HTTPSConnection(host,self.cfg['port'],timeout=self.timeout,context=context) if scheme=='https' else http.client.HTTPConnection(host,self.cfg['port'],timeout=self.timeout)
            try:
                connection.connect()
                if scheme=='https': verify_pin(connection.sock,self.cfg)
                hdr = {'Accept':'application/json', 'User-Agent':'QisutuMonitoring/1.0.1'}
                if self.cfg.get('token'):
                    hdr['Authorization']='Bearer '+self.cfg['token']
                elif self.cfg.get('username'):
                    hdr['Authorization']='Basic '+base64.b64encode((self.cfg['username']+':'+self.cfg.get('password','')).encode()).decode()
                hdr.update(headers or {})
                request=Request(origin+path,headers=hdr)
                self.jar.add_cookie_header(request)
                started=time.monotonic()
                connection.request(method,path,body,dict(request.header_items()))
                response=connection.getresponse()
                data=response.read(4*1024*1024+1)
                if len(data)>4*1024*1024: raise CheckFailure('Antwort zu groß. Auswahl begrenzen.')
                self.jar.extract_cookies(response,request)
                status=response.status;location=response.getheader('Location')
                elapsed=(time.monotonic()-started)*1000
                if status in (301,302,303,307,308) and location:
                    if redirects<=0: raise CheckFailure('Zu viele Weiterleitungen.')
                    target=urlsplit(urljoin(origin+path,location))
                    if target.scheme!=scheme or target.hostname!=host or (target.port or (443 if scheme=='https' else 80))!=self.cfg['port'] or target.username:
                        raise CheckFailure('Weiterleitung auf einen anderen Server wird nicht mit Zugangsdaten verfolgt.')
                    next_path=target.path or '/'
                    if target.query:next_path+='?'+target.query
                    if status==303 or (status in (301,302) and method=='POST'):method,body='GET',None
                    return self.request(next_path,method,body,headers,redirects-1)
                return status,data,elapsed
            finally:
                connection.close()

    def json(self,path,method='GET',body=None,headers=None):
        code,data,_=self.request(path,method,body,headers)
        if not 200<=code<300:raise CheckFailure('Schnittstelle antwortet mit HTTP %s.'%code)
        try:return json.loads(data)
        except (ValueError,UnicodeError):raise CheckFailure('Schnittstelle liefert keine gültige JSON-Antwort.')


def json_path(data,path):
    """A bounded, explicit JSON path subset; never evaluate code from a path."""
    if not isinstance(path,str) or len(path)>500:raise CheckFailure('Ungültiger JSON-Pfad.')
    if path.startswith('$'):path=path[1:]
    tokens=[];position=0
    pattern=re.compile(r'\.([A-Za-z0-9_:-]+)|\[(\d+|\*)\]|\["([^"\\]+)"\]')
    for match in pattern.finditer(path):
        if match.start()!=position:raise CheckFailure('JSON-Pfad unterstützt .feld, [0], [*] und ["feld"].')
        tokens.append(('index',match[2]) if match[2] is not None else ('field',match[1] or match[3]));position=match.end()
    if position!=len(path):raise CheckFailure('Ungültiger JSON-Pfad.')
    values=[data]
    for kind,key in tokens:
        following=[]
        for value in values:
            if kind=='field' and isinstance(value,dict) and key in value:following.append(value[key])
            elif kind=='index' and isinstance(value,list):
                if key=='*':following.extend(value)
                elif int(key)<len(value):following.append(value[int(key)])
        values=following
        if len(values)>1000:raise CheckFailure('JSON-Auswahl enthält mehr als 1.000 Werte.')
    return values


def json_metrics(data, specs):
    result=[]
    for index,spec in enumerate(specs):
        values=json_path(data,spec['path'])
        if not values:values=[None]
        for n,value in enumerate(values):
            number=numeric(value)
            label=spec['name']+(' ['+str(n)+']' if len(values)>1 else '')
            identity=hashlib.sha256(json.dumps([spec['path'],spec['scale'],spec['unit']],ensure_ascii=False).encode()).hexdigest()[:24]
            result.append(metric('json:'+identity+':'+str(n),label,number*spec['scale'] if number is not None else None,
                                 spec['unit'],warn=spec.get('warn'),critical=spec.get('critical'),
                                 message='' if number is not None else 'JSON-Pfad fehlt oder liefert keine Zahl.'))
    return result


def web_scenario(cfg,timeout):
    from .services import status_codes
    client=HTTP(cfg,timeout);variables={k:cfg.get(k,'') for k in ('username','password','token')};result=[]
    def substitute(text):
        def value(match):
            if match[1] not in variables:raise CheckFailure('Eine benötigte Sitzungsvariable fehlt.')
            return quote(str(variables[match[1]]),safe='')
        return re.sub(r'\{\{([A-Za-z][A-Za-z0-9_]*)\}\}',value,text)
    for n,step in enumerate(cfg['steps']):
        started=time.monotonic()
        code,raw,_=client.request(substitute(step['path']),step['method'],
            substitute(step['body']).encode() if step['method']=='POST' else None,
            {'Content-Type':'application/x-www-form-urlencoded','Accept':'text/html,application/json'})
        text=raw.decode('utf-8',errors='replace')
        valid=code in status_codes(step['codes']) and (not step['contains'] or step['contains'] in text)
        if step['extract']:
            found=re.search(step['extract'],text)
            valid=valid and found is not None
            if found and step['variable']:variables[step['variable']]=found.group(1) if found.lastindex else found.group()
        identity=hashlib.sha256(json.dumps([n,step['path'],step['method'],step['body']]).encode()).hexdigest()[:24]
        result.append(metric('step:'+identity,step['name'] or 'Schritt '+str(n+1),(time.monotonic()-started)*1000,'ms',
            status='up' if valid else 'critical',message='HTTP '+str(code)+(' · Inhalt bestätigt.' if valid else ' · Status, Inhalt oder Sitzungsvariable nicht bestätigt.')))
        if not valid:break
    return result


def snmp_metrics(cfg,timeout):
    from .resources import config_text,run_walk,CheckError
    from .advanced_config import PROFILES
    binary=shutil.which('snmpbulkwalk')
    if not binary:raise CheckFailure('Net-SNMP fehlt auf dem Monitoring-Server.')
    specs=PROFILES.get(cfg['profile'],[])+cfg['metrics'];result=[]
    target=dict(cfg,device_address=cfg['host'],method='snmp',priv_protocol='AES')
    with tempfile.TemporaryDirectory(prefix='qisutu-snmp-') as directory:
        path=Path(directory)/'snmp.conf';path.write_text(config_text(target));path.chmod(0o600)
        deadline=time.monotonic()+timeout
        for index,spec in enumerate(specs):
            try:
                values=run_walk(binary,target,spec['oid'],directory,deadline,include_root=True)
                if not values:raise CheckFailure('OID wird nicht geliefert.')
                for oid,value in values.items():
                    number=numeric(value);expected=spec.get('expected','')
                    status=('up' if str(value)==expected else 'critical') if expected else None
                    row=metric('oid:'+oid,spec['name']+' · '+oid,number*spec.get('scale',1) if number is not None else None,
                               spec.get('unit',''),status=status,warn=spec.get('warn'),critical=spec.get('critical'),
                               message=str(value)[:250] if number is None or expected else '')
                    if spec.get('rate'):
                        row.update(counter=True,counter_bits=64)
                    result.append(row)
            except (ValueError,CheckFailure,CheckError) as exc:
                result.append(metric('missing:oid:'+spec['oid'],spec['name'],message=str(exc)))
    return result


def ssh_check(kind,cfg,timeout):
    from .ssh_resources import probe_ssh
    if kind=='linuxlog':
        command='journalctl --no-pager --output=json -n 5000 --since '+shlex.quote(str(int(cfg['minutes']))+' minutes ago')+' --priority='+cfg['priority']
        if cfg['unit']:command+=' --unit='+shlex.quote(cfg['unit'])
        command+='\n'
    else:command=cfg['command']+'\n'
    output=probe_ssh(dict(cfg,device_address=cfg['host'],timeout=timeout),script=command)
    if output['kind']!='ok':raise CheckFailure(output['message'])
    text=output['output']
    if kind=='linuxlog':
        rows=[]
        for line in text.splitlines():
            try:row=json.loads(line)
            except ValueError:
                if line.strip():raise CheckFailure('Journal-Ausgabe enthält Fehler oder ist nicht vollständig lesbar.')
                continue
            message=row.get('MESSAGE','')
            if isinstance(message,list):message=bytes(message).decode(errors='replace')
            if cfg['contains'].casefold() in str(message).casefold():rows.append((row,str(message)))
        detail='\n'.join((r.get('_SYSTEMD_UNIT') or r.get('SYSLOG_IDENTIFIER') or '')+': '+m for r,m in rows[-5:])
        limited=len(text.splitlines())>=5000
        return [metric('journal:matches','Passende Protokollereignisse',len(rows),'Ereignisse',
                       status='warning' if rows else 'unknown' if limited else 'up',
                       message=('Auswahl auf die letzten 5.000 Einträge begrenzt. ' if limited else '')+detail)]
    if cfg['metrics']:
        try:data=json.loads(text)
        except ValueError:raise CheckFailure('Messbefehl liefert kein gültiges JSON.')
        return json_metrics(data,cfg['metrics'])
    value=numeric(text.strip())
    if value is None:raise CheckFailure('Messbefehl muss eine einzelne Zahl liefern.')
    return [metric('ssh:value','Messwert',value)]


def prometheus(cfg,timeout):
    code,raw,_=HTTP(cfg,timeout).request(cfg['path'])
    if code!=200:raise CheckFailure('Exporter antwortet mit HTTP '+str(code)+'.')
    result=[];names=set(cfg['names'])
    expression=re.compile(r'^([A-Za-z_:][A-Za-z0-9_:]*)(\{.*\})?\s+([^\s]+)(?:\s+[^\s]+)?$')
    for line in raw.decode('utf-8',errors='replace').splitlines():
        if not line or line.startswith('#'):continue
        match=expression.fullmatch(line)
        if not match or (names and match[1] not in names):continue
        label=match[1]+(match[2] or '')
        result.append(metric('prom:'+hashlib.sha256(label.encode()).hexdigest()[:32],label,numeric(match[3])))
        if len(result)>2000:raise CheckFailure('Mehr als 2.000 Exporter-Messreihen. Namensfilter eingrenzen.')
    if not result:raise CheckFailure('Keine passenden Exporter-Messwerte.')
    return result


def check(kind,cfg,timeout):
    if kind=='webscenario':return web_scenario(cfg,timeout)
    if kind=='httpjson':return json_metrics(HTTP(cfg,timeout).json(cfg['path']),cfg['metrics'])
    if kind=='snmpcustom':return snmp_metrics(cfg,timeout)
    if kind in ('sshcheck','linuxlog'):return ssh_check(kind,cfg,timeout)
    if kind=='prometheus':return prometheus(cfg,timeout)
    if kind in ('docker','kubernetes','aws','azure'):
        from .check_cloud import check_cloud
        return check_cloud(kind,cfg,timeout)
    if kind=='mssql':
        from .check_sql import mssql
        return mssql(cfg,timeout)
    raise CheckFailure('Diese Prüfung benötigt den zentralen Messwertspeicher.')
