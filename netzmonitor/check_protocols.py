"""TLS validity, DNS queries and mail protocol checks. No messages are sent."""
import datetime
import hashlib
import imaplib
import ipaddress
import poplib
import secrets
import smtplib
import socket
import ssl
import struct
import tempfile
import time
from pathlib import Path
from .integration_common import CheckFailure, metric, tls_context, verify_pin

DNS_TYPES = {'A': 1, 'NS': 2, 'CNAME': 5, 'MX': 15, 'TXT': 16, 'AAAA': 28}


def read_name(data, offset):
    labels, visited, end = [], set(), None
    while True:
        if offset >= len(data) or offset in visited or len(visited) > 128:
            raise CheckFailure('Ungültige DNS-Namenskompression.')
        visited.add(offset)
        size = data[offset]
        if size & 0xc0 == 0xc0:
            if offset + 1 >= len(data):
                raise CheckFailure('Unvollständige DNS-Antwort.')
            if end is None:
                end = offset + 2
            offset = ((size & 0x3f) << 8) | data[offset + 1]
            continue
        if size & 0xc0 or size > 63 or offset + size + 1 > len(data):
            raise CheckFailure('Ungültiger DNS-Name.')
        offset += 1
        if not size:
            return '.'.join(labels).lower(), end or offset
        labels.append(data[offset:offset + size].decode('ascii', 'replace'))
        offset += size


def parse_dns(data, ident, name, qtype):
    if len(data) < 12:
        raise CheckFailure('Unvollständige DNS-Antwort.')
    rid, flags, qd, an, ns, ar = struct.unpack('!6H', data[:12])
    if rid != ident or not flags & 0x8000 or flags & 0x7800 or qd != 1:
        raise CheckFailure('DNS-Antwort passt nicht zur Anfrage.')
    qname, pos = read_name(data, 12)
    if pos + 4 > len(data) or qname != name.lower().rstrip('.') or struct.unpack('!HH', data[pos:pos+4]) != (qtype, 1):
        raise CheckFailure('DNS-Antwort enthält eine andere Frage.')
    pos += 4
    code = flags & 15
    if code:
        raise CheckFailure({1: 'DNS-Anfrage abgelehnt (Formatfehler).', 2: 'DNS-Serverfehler (SERVFAIL).',
                            3: 'DNS-Name existiert nicht (NXDOMAIN).', 5: 'DNS-Server verweigert die Anfrage.'}.get(code, 'DNS-Fehlercode %s.' % code))
    if flags & 0x0200:
        return None
    records, aliases = [], {}
    if an + ns + ar > 4096:
        raise CheckFailure('Zu viele DNS-Antworten.')
    for index in range(an + ns + ar):
        owner, pos = read_name(data, pos)
        if pos + 10 > len(data):
            raise CheckFailure('Unvollständiger DNS-Eintrag.')
        typ, cls, ttl, length = struct.unpack('!HHIH', data[pos:pos+10])
        pos += 10
        start, end = pos, pos + length
        if end > len(data):
            raise CheckFailure('Unvollständige DNS-Nutzdaten.')
        value = None
        if typ == 1 and length == 4:
            value = str(ipaddress.IPv4Address(data[pos:end]))
        elif typ == 28 and length == 16:
            value = str(ipaddress.IPv6Address(data[pos:end]))
        elif typ in (2, 5):
            value = read_name(data, pos)[0]
        elif typ == 15 and length >= 3:
            value = str(struct.unpack('!H', data[pos:pos+2])[0]) + ' ' + read_name(data, pos+2)[0]
        elif typ == 16:
            chunks = []
            while pos < end:
                n = data[pos]; pos += 1
                if pos + n > end:
                    raise CheckFailure('Ungültiger DNS-TXT-Eintrag.')
                chunks.append(data[pos:pos+n].decode('utf-8', 'replace')); pos += n
            value = ''.join(chunks)
        if index < an and cls == 1:
            if typ == 5 and value is not None:
                aliases[owner] = value
            if typ == qtype and value is not None:
                records.append((owner, value))
        pos = end
    owners = {name.lower().rstrip('.')}
    for _ in range(32):
        more = {aliases[n] for n in owners if n in aliases}
        if more <= owners:
            break
        owners |= more
    return [value for owner, value in records if owner in owners]


def receive_exact(sock, length):
    data = b''
    while len(data) < length:
        block = sock.recv(length-len(data))
        if not block:
            raise CheckFailure('DNS-Verbindung vorzeitig beendet.')
        data += block
    return data


def dns_check(config, timeout):
    name = config['query'].encode('idna').decode('ascii').rstrip('.')
    ident, qtype = secrets.randbelow(65536), DNS_TYPES[config['record_type']]
    encoded = b''.join(bytes([len(p)]) + p.encode('ascii') for p in name.split('.')) + b'\0'
    packet = struct.pack('!6H', ident, 0x0100, 1, 0, 0, 0) + encoded + struct.pack('!HH', qtype, 1)
    family, _, _, _, server = socket.getaddrinfo(config['host'], config['port'], type=socket.SOCK_DGRAM)[0]
    started = time.monotonic()
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout); sock.connect(server); sock.send(packet)
        response = sock.recv(65535)
    values = parse_dns(response, ident, name, qtype)
    if values is None:
        with socket.create_connection((config['host'], config['port']), timeout=timeout) as sock:
            sock.sendall(struct.pack('!H', len(packet)) + packet)
            size = struct.unpack('!H', receive_exact(sock, 2))[0]
            values = parse_dns(receive_exact(sock, size), ident, name, qtype)
        if values is None:
            raise CheckFailure('Auch die DNS-TCP-Antwort ist abgeschnitten.')
    if not values:
        raise CheckFailure('Keine %s-Antwort für %s.' % (config['record_type'], name))
    expected = config.get('expected', '')
    def normalized(v):
        if qtype in (1, 28):
            return str(ipaddress.ip_address(v))
        return v if qtype == 16 else v.rstrip('.').lower()
    matches = not expected or any(normalized(v) == normalized(expected) for v in values)
    return [metric('dns-answer', 'DNS-Antwort', len(values), 'Einträge', 'up' if matches else 'critical',
                   ('Antwort: ' if matches else 'Erwartete Antwort fehlt: ') + ' · '.join(values)[:900]),
            metric('latency', 'Antwortzeit', (time.monotonic()-started)*1000, 'ms')]


def mail_connect(kind, config, timeout, inspect=False):
    mode = config['security']; context = ssl._create_unverified_context() if inspect else tls_context(config)
    host, port = config['host'], config['port']
    client = None
    try:
        if kind == 'smtp':
            client = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) if mode == 'tls' else smtplib.SMTP(host, port, timeout=timeout)
            if mode == 'tls': verify_pin(client.sock, {} if inspect else config)
            code, _ = client.ehlo()
            if code != 250:
                raise CheckFailure('SMTP-Server beantwortet EHLO nicht erfolgreich.')
            if mode == 'starttls':
                client.starttls(context=context); verify_pin(client.sock, {} if inspect else config)
                if client.ehlo()[0] != 250: raise CheckFailure('SMTP-EHLO nach STARTTLS fehlgeschlagen.')
        elif kind == 'imap':
            client = imaplib.IMAP4_SSL(host, port, ssl_context=context, timeout=timeout) if mode == 'tls' else imaplib.IMAP4(host, port, timeout=timeout)
            if mode == 'tls': verify_pin(client.sock, {} if inspect else config)
            if mode == 'starttls': client.starttls(context); verify_pin(client.sock, {} if inspect else config)
        else:
            client = poplib.POP3_SSL(host, port, timeout=timeout, context=context) if mode == 'tls' else poplib.POP3(host, port, timeout=timeout)
            if mode == 'tls': verify_pin(client.sock, {} if inspect else config)
            if mode == 'starttls': client.stls(context); verify_pin(client.sock, {} if inspect else config)
        return client
    except BaseException:
        if client:
            try: client.close() if kind != 'imap' else client.shutdown()
            except Exception: pass
        raise


def mail_check(kind, config, timeout):
    started = time.monotonic()
    client = mail_connect(kind, config, timeout)
    try:
        username = config.get('username', '')
        if username:
            if kind == 'smtp': client.login(username, config['password'])
            elif kind == 'imap':
                if client.login(username, config['password'])[0] != 'OK':
                    raise CheckFailure('IMAP-Anmeldung fehlgeschlagen.')
            else:
                client.user(username); client.pass_(config['password'])
        if kind == 'smtp':
            if client.noop()[0] != 250: raise CheckFailure('SMTP-Protokollprüfung fehlgeschlagen.')
        elif kind == 'imap':
            if client.noop()[0] != 'OK': raise CheckFailure('IMAP-Protokollprüfung fehlgeschlagen.')
        else:
            # CAPA is valid before login; NOOP is only used after authentication.
            client.noop() if username else client.capa()
        return [metric('protocol', kind.upper() + '-Funktion', 1, '', 'up',
                       'Protokoll und Anmeldung erfolgreich.' if username else 'Protokoll erfolgreich; keine Anmeldung eingerichtet.'),
                metric('latency', 'Antwortzeit', (time.monotonic()-started)*1000, 'ms')]
    finally:
        try:
            if kind == 'imap': client.logout()
            else: client.quit()
        except Exception: pass


def tls_check(config, timeout):
    # Read certificate even if it has expired; expiry must remain a numeric measurement.
    with socket.create_connection((config['host'], config['port']), timeout=timeout) as raw:
        with ssl._create_unverified_context().wrap_socket(raw, server_hostname=config.get('server_name') or config['host']) as sock:
            der = sock.getpeercert(binary_form=True)
    with tempfile.TemporaryDirectory(prefix='netzmonitor-cert-') as directory:
        path = Path(directory) / 'cert.pem'
        path.write_text(ssl.DER_cert_to_PEM_cert(der), encoding='ascii')
        certificate = ssl._ssl._test_decode_cert(str(path))
    expires = ssl.cert_time_to_seconds(certificate['notAfter'])
    starts = ssl.cert_time_to_seconds(certificate['notBefore'])
    days = (expires-time.time())/86400
    date = datetime.datetime.fromtimestamp(expires, datetime.timezone.utc).strftime('%d.%m.%Y %H:%M UTC')
    measurements = [metric('days', 'Zertifikat gültig für', days, 'Tage', warn=config['warn_days'],
                           critical=config['critical_days'], low=True, message='Ablauf: ' + date)]
    if starts > time.time():
        measurements.append(metric('trust', 'Zertifikatsprüfung', 0, '', 'critical', 'Zertifikat ist noch nicht gültig.'))
    elif config.get('fingerprint'):
        ok = hashlib.sha256(der).hexdigest() == config['fingerprint']
        measurements.append(metric('trust', 'Zertifikatsprüfung', int(ok), '', 'up' if ok else 'critical',
                                   'Bestätigter Fingerabdruck.' if ok else 'Zertifikat geändert. Fingerabdruck erneut prüfen.'))
    else:
        try:
            with socket.create_connection((config['host'], config['port']), timeout=timeout) as raw:
                with ssl.create_default_context().wrap_socket(raw, server_hostname=config.get('server_name') or config['host']):
                    pass
            measurements.append(metric('trust', 'Zertifikatsprüfung', 1, '', 'up', 'Zertifikatskette und Servername gültig.'))
        except ssl.SSLCertVerificationError:
            measurements.append(metric('trust', 'Zertifikatsprüfung', 0, '', 'critical',
                'Zertifikatskette, Servername oder Gültigkeit ungültig. Bei eigener CA deren Zertifikat auf dem Monitoring-Server installieren.'))
    return measurements


def inspect_certificate(config, timeout):
    if config['protocol'] in ('smtp','imap','pop3'):
        client=mail_connect(config['protocol'], config, timeout, inspect=True)
        try: return hashlib.sha256(client.sock.getpeercert(binary_form=True)).hexdigest()
        finally:
            try: client.shutdown() if config['protocol']=='imap' else client.close()
            except Exception: pass
    with socket.create_connection((config['host'],config['port']),timeout=timeout) as raw:
        with ssl._create_unverified_context().wrap_socket(raw,server_hostname=config.get('server_name') or config['host']) as secure:
            return hashlib.sha256(secure.getpeercert(binary_form=True)).hexdigest()
