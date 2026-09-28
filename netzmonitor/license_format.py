"""Offline license format. RSA-PSS/SHA-256 is implemented by system OpenSSL."""
import base64
import binascii
from datetime import date, datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

MAX_FILE_BYTES = 16384
FORMAT = 'netzmonitor-license-v1'
PLANS = {'service-100': (100, 'Servicevertrag 1'),
         'service-500': (500, 'Servicevertrag 2'),
         'service-unlimited': (None, 'Servicevertrag 3')}
SIGN_OPTIONS = ['-sigopt', 'rsa_padding_mode:pss', '-sigopt', 'rsa_pss_saltlen:digest']


def today():
    return datetime.now(timezone.utc).date()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Die Datei enthält doppelte Felder.')
        result[key] = value
    return result


def read_json(raw):
    try:
        if not isinstance(raw, str) or not 1 <= len(raw.encode('utf-8')) <= MAX_FILE_BYTES:
            raise ValueError('Datei muss zwischen 1 Byte und 16 KiB groß sein.')
        return json.loads(raw, object_pairs_hook=_unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Ungültige Zahl.')))
    except (UnicodeError, RecursionError, json.JSONDecodeError):
        raise ValueError('Die Datei ist keine gültige UTF-8-JSON-Datei.') from None


def installation_id(value):
    if not isinstance(value, str):
        raise ValueError('Die Installationskennung fehlt oder ist ungültig.')
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise ValueError('Die Installationskennung fehlt oder ist ungültig.') from None
    if str(parsed) != value or parsed.version != 4:
        raise ValueError('Die Installationskennung fehlt oder ist ungültig.')
    return value


def iso_date(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError(label + ': Datum als JJJJ-MM-TT angeben.')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(label + ': Ungültiges Datum.') from None


def validate_payload(value):
    fields = {'product', 'license_id', 'installation_id', 'customer', 'contract_id',
              'plan', 'device_limit', 'issued_at', 'valid_from', 'valid_until'}
    if not isinstance(value, dict) or set(value) != fields or value.get('product') != 'netzmonitor':
        raise ValueError('Die Datei ist keine unterstützte Qisutu Monitoring-Freischaltung.')
    installation_id(value['installation_id'])
    installation_id(value['license_id'])
    for name, label, required in [('customer', 'Kunde', True), ('contract_id', 'Vertragsnummer', False)]:
        text = value[name]
        if not isinstance(text, str) or len(text) > 200 or (required and not text.strip()) or any(ord(c) < 32 or ord(c) == 127 for c in text):
            raise ValueError(label + ': Ungültige Angabe (höchstens 200 Zeichen).')
    plan = value['plan']
    if not isinstance(plan, str) or plan not in PLANS:
        raise ValueError('Unbekannte Vertragsstufe.')
    limit = value['device_limit']
    if limit != PLANS[plan][0] or (limit is not None and type(limit) is not int):
        raise ValueError('Gerätezahl und Vertragsstufe passen nicht zusammen.')
    issued = value['issued_at']
    if type(issued) is not int or not 0 < issued < 253402300800:
        raise ValueError('Ungültiges Ausstellungsdatum.')
    start = iso_date(value['valid_from'], 'Vertragsbeginn')
    end = iso_date(value['valid_until'], 'Vertragsende')
    if end < start:
        raise ValueError('Das Vertragsende liegt vor dem Vertragsbeginn.')
    return value


def public_key_id(pem):
    try:
        lines = pem.strip().splitlines()
        if lines[0] != '-----BEGIN PUBLIC KEY-----' or lines[-1] != '-----END PUBLIC KEY-----':
            raise ValueError()
        der = base64.b64decode(''.join(lines[1:-1]), validate=True)
        if not 128 <= len(der) <= 4096:
            raise ValueError()
        return hashlib.sha256(der).hexdigest()
    except (IndexError, ValueError, binascii.Error):
        raise ValueError('Der öffentliche Prüfschlüssel ist ungültig. Bitte das Programmpaket prüfen.') from None


def openssl(args, data=None, timeout=10):
    executable = shutil.which('openssl')
    if not executable:
        raise ValueError('OpenSSL fehlt. Bitte auf diesem Rechner das Systempaket openssl bereitstellen.')
    try:
        return subprocess.run([executable, *args], input=data, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('OpenSSL konnte die Freischaltdatei nicht verarbeiten.') from None


@lru_cache(maxsize=32)
def verify_document(raw, public_pem):
    """Cache signature checks only. Contract dates are evaluated on every use."""
    document = read_json(raw)
    if not isinstance(document, dict) or set(document) != {'format', 'key_id', 'payload', 'signature'} or document.get('format') != FORMAT:
        raise ValueError('Bitte die vom Hersteller erhaltene Freischaltdatei auswählen.')
    if document['key_id'] != public_key_id(public_pem):
        raise ValueError('Die Freischaltdatei stammt nicht vom hinterlegten Hersteller. Bitte die passende Datei bzw. Programmversion anfordern.')
    validate_payload(document['payload'])
    try:
        signature = base64.b64decode(document['signature'], validate=True)
    except (ValueError, TypeError, binascii.Error):
        raise ValueError('Die Signatur der Freischaltdatei ist ungültig.') from None
    if len(signature) != 384:
        raise ValueError('Die Signatur der Freischaltdatei ist ungültig.')
    with tempfile.TemporaryDirectory(prefix='netzmonitor-license-') as directory:
        key = Path(directory) / 'public.pem'
        sig = Path(directory) / 'signature.bin'
        key.write_text(public_pem, encoding='ascii')
        sig.write_bytes(signature)
        result = openssl(['dgst', '-sha256', '-verify', str(key), '-signature', str(sig), *SIGN_OPTIONS], canonical(document['payload']))
    if result.returncode != 0:
        raise ValueError('Die Signatur ist ungültig. Die Freischaltdatei wurde verändert oder beschädigt.')
    return document


def sign_document(payload, private_key, public_pem):
    validate_payload(payload)
    result = openssl(['dgst', '-sha256', '-sign', str(Path(private_key).resolve()), *SIGN_OPTIONS], canonical(payload))
    if result.returncode != 0:
        raise ValueError('Der private Herstellerschlüssel konnte nicht zum Signieren verwendet werden.')
    document = dict(format=FORMAT, key_id=public_key_id(public_pem), payload=payload,
                    signature=base64.b64encode(result.stdout).decode('ascii'))
    raw = json.dumps(document, ensure_ascii=False, indent=2) + '\n'
    verify_document(raw, public_pem)
    return raw
