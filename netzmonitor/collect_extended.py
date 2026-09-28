"""Read-only Linux and standards-based SNMP collectors. No target installation."""
import json
import re
import shlex
from .extended import config, metric

IF = '.1.3.6.1.2.1.2.2.1'
IFX = '.1.3.6.1.2.1.31.1.1.1'
ENTITY = '.1.3.6.1.2.1.47.1.1.1.1'
SENSOR = '.1.3.6.1.2.1.99.1.1.1'
HRDEVICE = '.1.3.6.1.2.1.25.3.2.1'
RUN = '.1.3.6.1.2.1.25.4.2.1'

NETWORK_SCRIPT = r'''
printf 'NM_CLOCK|'; cat /proc/uptime
printf 'NM_BOOT|'; cat /proc/sys/kernel/random/boot_id
for n in /sys/class/net/*; do
 [ -r "$n/type" ] || continue
 [ "$(cat "$n/type")" = 772 ] && continue
 name=${n##*/}
 printf 'NM_NET|%s|' "$name"
 for f in address ifindex operstate flags speed; do v=$(cat "$n/$f" 2>/dev/null); printf '%s|' "${v:-?}"; done
 for f in rx_bytes tx_bytes rx_errors tx_errors rx_dropped tx_dropped; do v=$(cat "$n/statistics/$f" 2>/dev/null); printf '%s|' "${v:-?}"; done
 printf '\n'
done
'''
IO_SCRIPT = r'''
printf 'NM_CLOCK|'; cat /proc/uptime
printf 'NM_BOOT|'; cat /proc/sys/kernel/random/boot_id
for n in /sys/block/*; do
 name=${n##*/}
 case "$name" in loop*|ram*|zram*) continue;; esac
 [ -r "$n/stat" ] || continue
 printf 'NM_IO|%s|' "$name"; cat "$n/stat"
done
'''
HARDWARE_SCRIPT = r'''
for h in /sys/class/hwmon/hwmon*; do
 [ -d "$h" ] || continue
 chip=$(cat "$h/name" 2>/dev/null | tr '\n|' '  ')
 dev=$(readlink -f "$h/device" 2>/dev/null); dev=${dev##*/}
 for p in "$h"/temp*_input "$h"/fan*_input "$h"/in*_input; do
  [ -r "$p" ] || continue
  prefix=${p%_input}; channel=${prefix##*/}
  label=$(cat "${prefix}_label" 2>/dev/null | tr '\n|' '  ')
  printf 'NM_SENSOR|%s @ %s · %s|%s|' "$chip" "${dev:-$chip}" "${label:-$channel}" "$channel"
  for f in input max crit min alarm fault; do v=$(cat "${prefix}_$f" 2>/dev/null); printf '%s|' "${v:-?}"; done
  printf '\n'
 done
done
for m in /sys/block/md*/md; do
 [ -d "$m" ] || continue
 name=${m%/md}; name=${name##*/}
 printf 'NM_RAID|%s|' "$name"
 for f in degraded array_state sync_action; do v=$(cat "$m/$f" 2>/dev/null); printf '%s|' "${v:-?}"; done
 printf '\n'
done
'''
SMART_SCRIPT = r'''
if command -v smartctl >/dev/null 2>&1; then
 for d in /sys/block/sd* /sys/block/nvme*n*; do
  [ -d "$d" ] || continue
  name=${d##*/}; printf 'NM_SMART_BEGIN|%s\n' "$name"
  smartctl -H -j "/dev/$name" 2>/dev/null
  printf '\nNM_SMART_END\n'
 done
else printf 'NM_NO_SMART\n'; fi
'''


def ssh_script(target):
    c=config(target.get('advanced'));s=''
    if c['network']:s+=NETWORK_SCRIPT
    if c['disk_io']:s+=IO_SCRIPT
    if c['hardware']:s+=HARDWARE_SCRIPT
    if c['smart']:s+=SMART_SCRIPT
    if c['processes']:
        s+=r'''
printf 'NM_PROCESSES_BEGIN\n'
for process_file in /proc/[0-9]*/comm; do
 [ -r "$process_file" ] || continue
 if IFS= read -r process_name < "$process_file" 2>/dev/null; then printf '%s\n' "$process_name"; fi
done
printf 'NM_PROCESSES_END\n'
'''
    if c['services']:
        s+='\nfor unit in '+' '.join(shlex.quote(u) for u in c['services'])+'; do\n'
        s+=r'''
 if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  printf 'NM_UNIT_BEGIN|%s\n' "$unit"
  systemctl show --no-pager --property=LoadState --property=ActiveState --property=SubState -- "$unit" 2>/dev/null
  printf 'NM_UNIT_END\n'
 else printf 'NM_UNIT_UNSUPPORTED|%s\n' "$unit"; fi
done
'''
    return s+'\nprintf "NM_EXTENDED_END\\n"\n'


def numeric(text):
    try:return float(text)
    except (ValueError,TypeError):return None


def parse_ssh(text,target):
    c=config(target.get('advanced'));result=dict(extended=[],interfaces=[],disk_counters=[])
    boot=re.search(r'^NM_BOOT\|([^\n]*)',text,re.M);epoch=boot[1] if boot else ''
    clock=re.search(r'^NM_CLOCK\|([\d.]+)',text,re.M);clock=float(clock[1]) if clock else 0
    for line in text.splitlines():
        fields=line.split('|');tag=fields[0]
        if tag=='NM_NET' and len(fields)>=13:
            _,name,mac,index,oper,flags,speed,rx,tx,rxerr,txerr,rd,td,*_=fields
            result['interfaces'].append(dict(name=name,identity=index+':'+mac,epoch=epoch,clock=clock,bits=64,
                speed=max(0,numeric(speed) or 0)*1e6,oper={'up':1,'down':2,'testing':3,'unknown':4,'dormant':5,'notpresent':6,'lowerlayerdown':7}.get(oper,4),
                admin=1 if flags!='?' and int(flags,16)&1 else 2,**{k:int(v) if v.isdigit() else None for k,v in zip(('rx','tx','rx_errors','tx_errors','rx_drops','tx_drops'),(rx,tx,rxerr,txerr,rd,td))}))
        elif tag=='NM_IO' and len(fields)==3:
            values=fields[2].split()
            if len(values)<11 or not all(v.isdigit() for v in values):continue
            values=list(map(int,values))
            result['disk_counters'].append(dict(name=fields[1],identity=fields[1],epoch=epoch,clock=clock,
                reads=values[0],writes=values[4],read_bytes=values[2]*512,write_bytes=values[6]*512,
                read_ms=values[3],write_ms=values[7],busy_ms=values[9]))
        elif tag=='NM_SENSOR' and len(fields)>=9:
            _,name,kind,value,maximum,critical,minimum,alarm,fault,*_=fields
            val=numeric(value);lo=numeric(minimum);hi=numeric(maximum);crit=numeric(critical)
            unit='°C' if kind.startswith('temp') else 'U/min' if kind.startswith('fan') else 'V'
            factor=1 if unit=='U/min' else .001
            val=val*factor if val is not None else None
            hi=hi*factor if hi is not None else c['temp_warn'] if unit=='°C' else None
            crit=crit*factor if crit is not None else c['temp_crit'] if unit=='°C' else None
            status='unknown' if val is None or fault=='1' else 'critical' if alarm=='1' or lo is not None and val<lo*factor else None
            result['extended'].append(metric('hardware',name,'Temperatur' if unit=='°C' else 'Drehzahl' if unit=='U/min' else 'Spannung',val,unit,status,'Sensorfehler' if fault=='1' else 'Hardwarealarm' if alarm=='1' else '',hi,crit))
        elif tag=='NM_RAID' and len(fields)>=5:
            _,name,degraded,state,sync,*_=fields;value=numeric(degraded)
            result['extended'].append(metric('hardware',name,'RAID fehlende Mitglieder',value,'',
                'unknown' if value is None else 'critical' if value>0 or state in ('inactive','clear') else 'warning' if sync not in ('idle','?') else 'up',
                'Array: '+state+' · Aktion: '+sync,1,1))
    if c['processes']:
        section=re.search(r'NM_PROCESSES_BEGIN\n(.*?)NM_PROCESSES_END',text,re.S)
        names=[x.strip() for x in section[1].splitlines()] if section else []
        for name in c['processes']:
            count=names.count(name) if section and names else None
            result['extended'].append(metric('process',name,'Laufende Prozesse',count,'',
                'unknown' if count is None else 'critical' if count==0 else 'up','Exakter Prozessname (comm), keine Kommandozeileninhalte.'))
    for name in c['services']:
        unit=re.search(r'NM_UNIT_BEGIN\|'+re.escape(name)+r'\n(.*?)NM_UNIT_END',text,re.S)
        values=dict(re.findall(r'^(LoadState|ActiveState|SubState)=(.*)$',unit[1],re.M)) if unit else {}
        active=values.get('ActiveState');load=values.get('LoadState');sub=values.get('SubState')
        status='unknown' if not values else 'critical' if load!='loaded' or active in ('failed','inactive') else 'up' if active=='active' else 'warning'
        result['extended'].append(metric('service',name,'Aktiv',1 if status=='up' else 0 if values else None,'',status,
            ' / '.join(v for v in (load,active,sub) if v) if values else 'systemd nicht verfügbar oder Leserecht fehlt.'))
    for found in re.finditer(r'NM_SMART_BEGIN\|([^\n]+)\n(.*?)\nNM_SMART_END',text,re.S):
        name,body=found.groups()
        try: data=json.loads(body)
        except ValueError:data={}
        passed=data.get('smart_status',{}).get('passed')
        messages='; '.join(str(m.get('string','')) for m in data.get('messages',[]))[:400]
        result['extended'].append(metric('smart',name,'SMART Gesamtzustand',1 if passed is True else 0 if passed is False else None,'',
            'up' if passed is True else 'critical' if passed is False else 'unknown',messages or ('SMART bestanden' if passed is True else 'SMART meldet Fehler' if passed is False else 'SMART nicht lesbar. Berechtigung oder Geräteunterstützung prüfen.')))
    if c['smart'] and 'NM_NO_SMART' in text:
        result['extended'].append(metric('smart','SMART','Verfügbarkeit',None,'','unknown','smartctl ist auf dem Ziel nicht installiert. Hardware-Sensoren und Linux-RAID werden separat geprüft.'))
    return result


def table(values,root):
    rows={}
    for oid,value in values.items():
        suffix=oid[len(root)+1:].split('.')
        if oid.startswith(root+'.') and len(suffix)==2:
            column,index=suffix;rows.setdefault(index,{})[int(column)]=value
    return rows


def parse_interfaces(basic,extended,clock=0):
    rows=table(basic,IF);ext=table(extended,IFX);result=[]
    for index,r in rows.items():
        if r.get(3)==24:continue
        x=ext.get(index,{});hc=isinstance(x.get(6),int) and isinstance(x.get(10),int)
        name=str(x.get(1) or r.get(2) or 'Port '+index)
        result.append(dict(name=name,alias=str(x.get(18) or ''),identity=index+':'+str(r.get(6,'')),
            clock=clock,epoch=x.get(19,0),speed=x.get(15,0)*1000000 or r.get(5,0),bits=64 if hc else 32,error_bits=32,
            admin=r.get(7),oper=r.get(8),rx=x.get(6) if hc else r.get(10),tx=x.get(10) if hc else r.get(16),
            rx_errors=r.get(14),tx_errors=r.get(20),rx_drops=r.get(13),tx_drops=r.get(19)))
    # Duplicated interface names must not share counter baselines.
    counts={n['name']:sum(x['name']==n['name'] for x in result) for n in result}
    for n in result:
        if counts[n['name']]>1:n['name']+=' [ifIndex '+n['identity'].split(':')[0]+']'
    return result


def parse_sensors(sensor,entity,devices,cfg):
    labels=table(entity,ENTITY);result=[]
    units={3:'V',4:'V',5:'A',6:'W',7:'Hz',8:'°C',9:'%',10:'U/min',11:'m³/min',12:''}
    for index,r in table(sensor,SENSOR).items():
        if r.get(1) not in units:continue
        typ=r[1];name=str(labels.get(index,{}).get(7) or labels.get(index,{}).get(2) or 'Sensor '+index)+' [Sensor '+index+']'
        value=r.get(4);scale=r.get(2,9);precision=r.get(3,0)
        val=value*10**((scale-9)*3-max(0,precision)) if isinstance(value,int) and abs(value)<1000000000 and 1<=scale<=17 and -8<=precision<=9 else None
        # TruthValue sensors define true(1), false(2), not an alarm interpretation.
        message='Sensor meldet wahr' if typ==12 and value==1 else 'Sensor meldet falsch' if typ==12 and value==2 else ''
        if typ==12:val=value
        status=None if r.get(5)==1 else 'unknown'
        result.append(metric('hardware',name,'Temperatur' if typ==8 else 'Sensorwert',val if status is None else None,units[typ],status,message or ('Sensor nicht betriebsbereit' if status else ''),cfg['temp_warn'] if typ==8 else None,cfg['temp_crit'] if typ==8 else None))
    for index,r in table(devices,HRDEVICE).items():
        state=r.get(5)
        if not isinstance(state,int):continue
        name=str(r.get(3) or 'Hardware '+index)+' [Gerät '+index+']'
        result.append(metric('hardware',name,'Gerätezustand',state,'',
            {1:'unknown',2:'up',3:'warning',4:'warning',5:'critical'}.get(state,'unknown'),
            {1:'Unbekannt',2:'Betriebsbereit',3:'Warnung',4:'Testbetrieb',5:'Nicht verfügbar'}.get(state,'Unbekannt')))
    return result


def collect_snmp(walk,target):
    c=config(target.get('advanced'));result=dict(extended=[],interfaces=[],disk_counters=[])
    if c['network']:
        basic=walk(IF);extended=walk(IFX)
        clock=walk('.1.3.6.1.2.1.1.3').get('.1.3.6.1.2.1.1.3.0',0)
        result['interfaces']=parse_interfaces(basic,extended,clock)
    if c['processes']:
        names=walk(RUN+'.2');statuses=walk(RUN+'.7')
        for name in c['processes']:
            count=sum(v==name and statuses.get(RUN+'.7.'+oid.rsplit('.',1)[1]) in (1,2,3) for oid,v in names.items()) if names and statuses else None
            result['extended'].append(metric('process',name,'Laufende Prozesse',count,'','unknown' if count is None else 'critical' if count==0 else 'up','Exakter Prozessname laut HOST-RESOURCES-MIB.'))
    if c['hardware']:
        result['extended']+=parse_sensors(walk(SENSOR),walk(ENTITY),walk(HRDEVICE),c)
    return result
