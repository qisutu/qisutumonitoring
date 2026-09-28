"""Read Linux resource counters over OpenSSH using a pinned host key."""
import base64
import hashlib
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import tempfile
import time

# Fixed read-only commands; no downloaded or installed script on the target.
COLLECTOR = r'''
export LC_ALL=C
if [ ! -r /proc/stat ] || [ ! -r /proc/meminfo ]; then
 printf 'NETZMONITOR_NOT_LINUX\n'; exit 1
fi
printf 'NETZMONITOR_RESOURCES_1\n'
awk '/^cpu / { printf "CPU1 %.0f %.0f\n",$2+$3+$4+$5+$6+$7+$8+$9,$5+$6; exit }' /proc/stat
sleep 1
awk '/^cpu / { printf "CPU2 %.0f %.0f\n",$2+$3+$4+$5+$6+$7+$8+$9,$5+$6; exit }' /proc/stat
awk '/^MemTotal:/ {t=$2} /^MemAvailable:/ {a=$2;has=1} /^MemFree:/ {f=$2} /^Buffers:/ {b=$2} /^Cached:/ {c=$2} END { if(has) printf "RAM %.0f %.0f available\n",t,a; else printf "RAM %.0f %.0f estimated\n",t,f+b+c }' /proc/meminfo
printf 'FILESYSTEMS\n'
df -P -k -l -T
printf 'END_FILESYSTEMS\n'
'''


def host_key(value):
    parts=str(value).strip().split()
    if len(parts)!=2 or parts[0] not in ('ssh-ed25519','ecdsa-sha2-nistp256','ecdsa-sha2-nistp384','ecdsa-sha2-nistp521','ssh-rsa'):
        raise ValueError('Bitte zuerst den SSH-Server-Schlüssel abrufen und bestätigen.')
    try:
        raw=base64.b64decode(parts[1],validate=True)
        n=int.from_bytes(raw[:4],'big')
        if len(raw)<32 or len(raw)>8192 or raw[4:4+n].decode('ascii')!=parts[0]:
            raise ValueError()
    except (ValueError,UnicodeError):
        raise ValueError('Ungültiger SSH-Server-Schlüssel.')
    return ' '.join(parts), 'SHA256:'+base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')


def scan_key(address, port):
    binary=shutil.which('ssh-keyscan')
    if not binary:
        raise ValueError('Auf dem Monitoring-Server fehlt ssh-keyscan (OpenSSH-Client). Installer erneut ausführen.')
    candidates=[]
    deadline=time.monotonic()+6
    # keyscan can stop at an unreachable IPv6 address even though ssh falls back to IPv4.
    for family in ([],['-4'],['-6']):
        remaining=deadline-time.monotonic()
        if remaining<=0: break
        try:
            result=subprocess.run([binary,*family,'-T','2','-p',str(port),address],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=remaining)
        except (OSError,subprocess.TimeoutExpired):
            continue
        for line in result.stdout.decode(errors='replace').splitlines():
            parts=line.split()
            if len(parts)==3 and not line.startswith('#'):
                try: candidates.append(host_key(' '.join(parts[1:])))
                except ValueError: pass
        if candidates: break
    if not candidates:
        raise ValueError('Kein SSH-Server-Schlüssel erhalten. Adresse, Port und Firewall prüfen.')
    candidates.sort(key=lambda pair:0 if pair[0].startswith('ssh-ed25519 ') else 1 if pair[0].startswith('ecdsa-') else 2)
    key,fingerprint=candidates[0]
    return dict(ssh_host_key=key,fingerprint=fingerprint)


def parse_metrics(output):
    metrics=[]
    snapshots={}
    for line in output.splitlines():
        fields=line.split()
        if len(fields)==3 and fields[0] in ('CPU1','CPU2'):
            try: snapshots[fields[0]]=(float(fields[1]),float(fields[2]))
            except ValueError: pass
    percent=None
    if len(snapshots)==2:
        total=snapshots['CPU2'][0]-snapshots['CPU1'][0]; idle=snapshots['CPU2'][1]-snapshots['CPU1'][1]
        if total>0 and 0<=idle<=total:
            percent=100*(total-idle)/total
    metrics.append(dict(key='cpu',kind='cpu',label='CPU gesamt',percent=percent,
                        message='Auslastung aller logischen CPUs über eine Sekunde.' if percent is not None else 'Keine gültige CPU-Messung erhalten.'))
    total=free=used=None;note='Arbeitsspeicher konnte nicht ausgelesen werden.'
    match=re.search(r'^RAM (\d+) (\d+) (available|estimated)$',output,re.M)
    if match:
        t,f=int(match[1])*1024,int(match[2])*1024
        if t>0 and 0<=f<=t:
            total,free,used=t,f,t-f
            note='Verfügbarer RAM laut Linux, einschließlich wiederverwendbarem Cache.' if match[3]=='available' else 'Älterer Kernel: verfügbarer RAM aus freiem Speicher, Puffern und Cache geschätzt.'
    metrics.append(dict(key='ram',kind='ram',label='Arbeitsspeicher',percent=100*used/total if total else None,total=total,used=used,free=free,message=note))
    if 'FILESYSTEMS\n' in output and '\nEND_FILESYSTEMS' in output:
        disk_output=output.split('FILESYSTEMS\n',1)[1].split('\nEND_FILESYSTEMS',1)[0]
        for line in disk_output.splitlines():
            match=re.match(r'^.+?\s+(\S+)\s+(\d+)\s+(\d+)\s+(-?\d+)\s+(\d+)%\s+(.+)$',line)
            if not match: continue
            fs,t,u,f,percent,mount=match.groups()
            if fs in ('tmpfs','devtmpfs','squashfs','iso9660','ramfs','debugfs','securityfs'):
                continue
            total,used,free=int(t)*1024,int(u)*1024,max(0,int(f))*1024
            if total<=0 or used>total: continue
            metrics.append(dict(key='disk:'+hashlib.sha256(mount.encode()).hexdigest()[:24],kind='disk',label=mount,
                                percent=min(100,int(percent)),total=total,used=used,free=free,message='Lokales Dateisystem · '+fs+' · Belegung und freier Platz laut df.'))
    if not any(m['kind']=='disk' for m in metrics):
        metrics.append(dict(key='disk:none',kind='disk',label='Dateisysteme',percent=None,message='Keine lokalen Dateisysteme ausgelesen. Berechtigung und df-Unterstützung prüfen.'))
    return metrics


def probe_ssh(target, script=None):
    binary=shutil.which('ssh')
    if not binary:
        return dict(kind='error',metrics=[],message='Auf dem Monitoring-Server fehlt der OpenSSH-Client. Installer erneut ausführen.')
    deadline=time.monotonic()+target['timeout']
    try:
        with tempfile.TemporaryDirectory(prefix='netzmonitor-ssh-') as directory:
            root=Path(directory)
            def private(name,content):
                path=root/name;path.write_text(content,encoding='utf-8');path.chmod(0o600);return str(path)
            host=target['device_address'];port=target['port']
            known=private('known_hosts','[%s]:%s %s\n%s %s\n' % (host,port,target['ssh_host_key'],host,target['ssh_host_key']))
            password=private('password',target.get('ssh_password',''))
            ask=root/'askpass';ask.write_text('#!/bin/sh\ncat "$NETZMONITOR_SSH_PASSWORD_FILE"\n');ask.chmod(0o700)
            args=[binary,'-F','/dev/null','-p',str(port),'-l',target['username'],
                  '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+known,
                  '-o','GlobalKnownHostsFile=/dev/null','-o','CheckHostIP=no','-o','UpdateHostKeys=no',
                  '-o','ConnectTimeout='+str(min(10,target['timeout'])),'-o','NumberOfPasswordPrompts=1',
                  '-o','IdentitiesOnly=yes','-o','IdentityAgent=none','-o','RequestTTY=no','-o','LogLevel=ERROR']
            if target['ssh_auth']=='key':
                key=private('identity',target['ssh_key'])
                args+=['-i',key,'-o','PreferredAuthentications=publickey']
            else:
                args+=['-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password,keyboard-interactive']
            args += [host,'sh -s']
            env={**os.environ,'SSH_ASKPASS':str(ask),'SSH_ASKPASS_REQUIRE':'force','DISPLAY':'netzmonitor:0',
                 'NETZMONITOR_SSH_PASSWORD_FILE':password}
            proc=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env,start_new_session=True)
            output=bytearray()
            try:
                from .collect_extended import ssh_script
                proc.stdin.write((script if script is not None else COLLECTOR+ssh_script(target)).encode());proc.stdin.close()
                with selectors.DefaultSelector() as selector:
                    selector.register(proc.stdout,selectors.EVENT_READ)
                    while True:
                        left=deadline-time.monotonic()
                        if left<=0 or not selector.select(left):
                            return dict(kind='down',metrics=[],message='SSH-Antwortfrist überschritten.')
                        block=os.read(proc.stdout.fileno(),65536)
                        if not block: break
                        output.extend(block)
                        if len(output)>2_000_000:
                            return dict(kind='error',metrics=[],message='SSH-Antwort ist zu groß.')
                proc.wait(timeout=max(.05,deadline-time.monotonic()))
            finally:
                if proc.poll() is None: proc.kill()
                proc.wait();proc.stdout.close()
                if not proc.stdin.closed: proc.stdin.close()
            text=output.decode('utf-8',errors='replace')
            if proc.returncode or (script is None and 'NETZMONITOR_RESOURCES_1\n' not in text):
                if 'Host key verification failed' in text or 'HOST IDENTIFICATION HAS CHANGED' in text:
                    message='SSH-Server-Schlüssel stimmt nicht überein. Unter Bearbeiten den Schlüssel prüfen und gegebenenfalls neu bestätigen.'
                elif 'Permission denied' in text or 'invalid format' in text or 'Load key' in text:
                    message='SSH-Anmeldung fehlgeschlagen. Benutzer, Passwort oder privaten Schlüssel prüfen.'
                elif 'NETZMONITOR_NOT_LINUX' in text:
                    message='SSH-Ressourcenabfragen benötigen ein Linux-Ziel mit lesbarem /proc. Für andere Geräte SNMP verwenden.'
                else:
                    message='SSH-Abfrage fehlgeschlagen. Erreichbarkeit, Zugang und Berechtigung für sh, awk und df prüfen.'
                return dict(kind='down',metrics=[],message=message)
            if script is not None:
                return dict(kind='ok', output=text, message='')
            from .collect_extended import parse_ssh
            return dict(kind='ok',metrics=parse_metrics(text),message='',**parse_ssh(text,target))
    except (OSError,subprocess.TimeoutExpired):
        return dict(kind='error',metrics=[],message='SSH-Prüfung konnte auf dem Monitoring-Server nicht ausgeführt werden.')
