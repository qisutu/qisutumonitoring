"""Bounded, read-only transports shared by the optional monitoring checks."""
import base64
import hashlib
import http.client
import json
import math
import socket
import ssl
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit


class CheckFailure(Exception):
    pass


def numeric(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def metric(key, label, value=None, unit='', status=None, message='', warn=None, critical=None, low=False):
    value = numeric(value)
    if status is None:
        status = 'unknown' if value is None else 'up'
        if value is not None:
            if critical is not None and (value <= critical if low else value >= critical):
                status = 'critical'
            elif warn is not None and (value <= warn if low else value >= warn):
                status = 'warning'
    return dict(key=str(key)[:500], label=str(label)[:300], value=value, unit=unit,
                status=status, message=str(message)[:1000], warn=warn, critical=critical, low=low)


def tls_context(config):
    return ssl._create_unverified_context() if config.get('fingerprint') else ssl.create_default_context()


def verify_pin(sock, config):
    wanted = config.get('fingerprint', '')
    if wanted and hashlib.sha256(sock.getpeercert(binary_form=True)).hexdigest() != wanted:
        raise CheckFailure('Server-Zertifikat wurde geändert. Fingerabdruck erneut prüfen und bestätigen.')


def certificate_fingerprint(host, port, timeout=8):
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with ssl._create_unverified_context().wrap_socket(raw, server_hostname=host) as secure:
            return hashlib.sha256(secure.getpeercert(binary_form=True)).hexdigest()


class HTTPS:
    """Credentials are sent only after CA validation or an explicit certificate pin."""
    def __init__(self, config, timeout=10):
        self.config, self.timeout = config, timeout
        self.cookie = ''

    def request(self, path, method='GET', body=None, headers=None, allow_missing=False):
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or not path.startswith('/') or path.startswith('//') or '\\' in path:
            raise CheckFailure('Die Schnittstelle liefert einen ungültigen Verweis auf einen anderen Server.')
        connection = http.client.HTTPSConnection(self.config['host'], self.config['port'],
                     timeout=self.timeout, context=tls_context(self.config))
        try:
            connection.connect()
            verify_pin(connection.sock, self.config)
            request_headers = {'Accept': 'application/json', 'User-Agent': 'QisutuMonitoring/1.0.1'}
            if self.config.get('username'):
                credentials = (self.config['username'] + ':' + self.config['password']).encode('utf-8')
                request_headers['Authorization'] = 'Basic ' + base64.b64encode(credentials).decode('ascii')
            if self.cookie:
                request_headers['Cookie'] = self.cookie
            request_headers.update(headers or {})
            connection.request(method, path, body, request_headers)
            response = connection.getresponse()
            data = response.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise CheckFailure('Antwort zu groß. Auswahl der überwachten Objekte begrenzen.')
            cookie = response.getheader('Set-Cookie')
            if cookie:
                self.cookie = cookie.split(';', 1)[0]
            if allow_missing and response.status in (404, 501):
                return None
            if response.status in (401, 403):
                raise CheckFailure('Zugang abgelehnt. Benutzer, Passwort und Leserechte prüfen.')
            if response.status >= 300:
                # SOAP faults are parsed without returning request contents or credentials.
                if response.status == 500 and data.lstrip().startswith(b'<'):
                    return data
                raise CheckFailure('Schnittstelle antwortet mit HTTP %s.' % response.status)
            return data
        finally:
            connection.close()

    def json(self, path, allow_missing=False):
        data = self.request(path, allow_missing=allow_missing)
        if data is None:
            return None
        try:
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, UnicodeError):
            raise CheckFailure('Schnittstelle liefert keine gültige JSON-Antwort.')


def xml(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise CheckFailure('XML-Antwort enthält nicht zulässige Dokumentdefinitionen.')
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise CheckFailure('Schnittstelle liefert keine gültige XML-Antwort.')
    if any(local(node.tag) == 'Fault' for node in root.iter()):
        codes = ' '.join((node.text or '') for node in root.iter() if local(node.tag) in ('Value', 'faultcode'))
        if 'AccessDenied' in codes or 'NotAuthenticated' in codes or 'InvalidLogin' in codes:
            raise CheckFailure('Anmeldung oder Leserechte abgelehnt.')
        raise CheckFailure('Schnittstellenabfrage abgelehnt. Freigaben und unterstützte Geräteversion prüfen.')
    return root


def local(tag):
    return tag.rsplit('}', 1)[-1]


def child(node, name):
    return next((n for n in node if local(n.tag) == name), None)


def text_at(node, path, default=None):
    for name in path.split('.'):
        node = child(node, name) if node is not None else None
    return node.text if node is not None and node.text is not None else default
