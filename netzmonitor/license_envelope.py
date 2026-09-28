"""Installation-specific encryption for binary .nmlic files.

The signed v1 document remains the authority. The v2 envelope protects its
contents in transit; all encryption material is generated locally.
"""
import base64
import binascii
from functools import lru_cache
import hashlib
import hmac
from pathlib import Path
import tempfile
from .license_format import openssl

MAGIC = b'NMLIC\x02\r\n'
TRANSPORT = 'NMLIC2:'
MAX_ENVELOPE_BYTES = 32768
WRAPPED_BYTES = 384
SALT_BYTES = 8
MAC_BYTES = 32
ITERATIONS = 100000
ERROR = 'Die Freischaltdatei ist beschädigt oder gehört zu einer anderen Installation. Bitte die passende Originaldatei erneut anfordern.'


def generate_recipient():
    with tempfile.TemporaryDirectory(prefix='netzmonitor-recipient-') as temp:
        path=Path(temp)/'private.pem'
        result=openssl(['genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:3072','-out',str(path)],timeout=30)
        if result.returncode:raise ValueError('Die Installationskennung konnte nicht vorbereitet werden. Bitte OpenSSL prüfen.')
        path.chmod(0o600)
        public=openssl(['pkey','-in',str(path),'-pubout'])
        if public.returncode:raise ValueError('Die Installationskennung konnte nicht vorbereitet werden.')
        return path.read_text(encoding='ascii'),public.stdout.decode('ascii')


@lru_cache(maxsize=1)
def salt_options():
    # OpenSSL 3.2 introduced configurable PBKDF2 salt length; older versions use 8.
    result=openssl(['enc','-help'])
    return ['-saltlen','8'] if b'-saltlen' in result.stdout+result.stderr else []


def decrypt_upload(raw, private_pem):
    if not isinstance(raw,str) or not raw.startswith(TRANSPORT) or len(raw)>len(TRANSPORT)+((MAX_ENVELOPE_BYTES+2)//3)*4:
        raise ValueError(ERROR)
    try:binary=base64.b64decode(raw[len(TRANSPORT):],validate=True)
    except (ValueError,binascii.Error):raise ValueError(ERROR) from None
    start=len(MAGIC);salt_start=start+WRAPPED_BYTES;cipher_start=salt_start+SALT_BYTES
    if (not binary.startswith(MAGIC) or len(binary)>MAX_ENVELOPE_BYTES or
            len(binary)<cipher_start+16+MAC_BYTES or (len(binary)-cipher_start-MAC_BYTES)%16):
        raise ValueError(ERROR)
    with tempfile.TemporaryDirectory(prefix='netzmonitor-unseal-') as temp:
        key=Path(temp)/'recipient.pem';password=Path(temp)/'secret'
        key.write_text(private_pem,encoding='ascii');key.chmod(0o600)
        result=openssl(['pkeyutl','-decrypt','-inkey',str(key),'-pkeyopt','rsa_padding_mode:oaep',
                        '-pkeyopt','rsa_oaep_md:sha256','-pkeyopt','rsa_mgf1_md:sha256'],binary[start:salt_start])
        if result.returncode or len(result.stdout)!=32:raise ValueError(ERROR)
        secret=result.stdout
        if not hmac.compare_digest(hmac.new(secret,binary[:-MAC_BYTES],hashlib.sha256).digest(),binary[-MAC_BYTES:]):
            raise ValueError(ERROR)
        # Pass the ephemeral secret through a private file, never process arguments.
        password.write_text(secret.hex()+'\n',encoding='ascii');password.chmod(0o600)
        salted=b'Salted__'+binary[salt_start:cipher_start]+binary[cipher_start:-MAC_BYTES]
        result=openssl(['enc','-d','-aes-256-cbc','-pbkdf2','-iter',str(ITERATIONS),'-md','sha256',
                        *salt_options(),'-pass','file:'+str(password)],salted)
        if result.returncode or len(result.stdout)>16384:raise ValueError(ERROR)
        try:return result.stdout.decode('utf-8')
        except UnicodeError:raise ValueError(ERROR) from None
