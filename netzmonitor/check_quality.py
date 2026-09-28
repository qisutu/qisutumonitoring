"""One bounded ICMP packet train. Jitter = mean adjacent RTT difference."""
import os
import re
import shutil
import subprocess
from .integration_common import CheckFailure, metric


def quality_metrics(output, cfg):
    summary = re.search(r'(\d+) packets transmitted,\s*(\d+) (?:packets )?received', output)
    if not summary or int(summary[1]) != cfg['packets']:
        raise CheckFailure('Ping-Messreihe unvollständig. Antwortfrist erhöhen oder ICMP-Berechtigung prüfen.')
    sent, received = map(int, summary.groups())
    if received > sent:
        raise CheckFailure('Ungültige Ping-Zusammenfassung.')
    samples = re.findall(r'icmp_seq[= ](\d+).*?time[=<]([0-9.]+)\s*ms', output)
    # Duplicated replies must not skew latency or jitter.
    samples = sorted({int(seq): float(rtt) for seq, rtt in samples}.items())
    times = [value for _, value in samples]
    deltas = [abs(b[1]-a[1]) for a, b in zip(samples, samples[1:]) if b[0] == a[0]+1]
    loss = 100*(sent-received)/sent
    result = [metric('loss','Paketverlust',loss,'%',warn=cfg['loss_warn'],critical=cfg['loss_crit'],
                     message='%s von %s Testpaketen beantwortet.' % (received,sent))]
    for key,label,value in [('latency','Mittlere Laufzeit',sum(times)/len(times) if times else None),
                            ('jitter','Laufzeitschwankung',sum(deltas)/len(deltas) if deltas else None)]:
        result.append(metric(key,label,value,'ms',warn=cfg[key+'_warn'],critical=cfg[key+'_crit'],
            message=('Mittlere absolute RTT-Differenz direkt aufeinanderfolgender Antworten.' if key=='jitter' and deltas else
                     'Zu wenige aufeinanderfolgende Antworten.' if key=='jitter' else 'Keine ICMP-Antwort.' if not times else '')))
    result.extend([metric('minimum','Kürzeste Laufzeit',min(times) if times else None,'ms'),
                   metric('maximum','Längste Laufzeit',max(times) if times else None,'ms')])
    return result


def quality_check(cfg, timeout):
    binary = shutil.which('ping')
    if not binary: raise CheckFailure('ping fehlt auf dem Monitoring-Server. Installer erneut ausführen.')
    # 0.2 seconds is supported for an unprivileged Linux user. Numeric output avoids reverse DNS.
    args = [binary,'-n','-c',str(cfg['packets']),'-i','0.2','-W','1','-w',str(max(2,timeout-1)),cfg['host']]
    try:
        proc = subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                              timeout=timeout,env={**os.environ,'LC_ALL':'C'})
    except subprocess.TimeoutExpired: raise CheckFailure('Ping-Antwortfrist überschritten. Adresse und ICMP-Freigabe prüfen.')
    if proc.returncode not in (0,1):
        raise CheckFailure('Ping konnte nicht ausgeführt werden. Adresse, ping-Version und ICMP-Berechtigung prüfen.')
    return quality_metrics(proc.stdout,cfg)
