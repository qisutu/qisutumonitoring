"""Independent OpenSSL producer for interoperability tests (no manufacturer keys)."""
import base64
import hashlib
import hmac
import os
from pathlib import Path
import tempfile
from netzmonitor.license_format import openssl
from netzmonitor.license_envelope import MAGIC, TRANSPORT, salt_options


def encrypted(raw,public):
    secret=os.urandom(32)
    with tempfile.TemporaryDirectory() as temp:
        key=Path(temp)/'public.pem';password=Path(temp)/'password'
        key.write_text(public);password.write_text(secret.hex()+'\n');password.chmod(0o600)
        wrapped=openssl(['pkeyutl','-encrypt','-pubin','-inkey',str(key),'-pkeyopt','rsa_padding_mode:oaep','-pkeyopt','rsa_oaep_md:sha256','-pkeyopt','rsa_mgf1_md:sha256'],secret)
        assert wrapped.returncode==0,wrapped.stderr
        sealed=openssl(['enc','-aes-256-cbc','-pbkdf2','-iter','100000','-md','sha256',*salt_options(),'-pass','file:'+str(password)],raw.encode('utf-8'))
        assert sealed.returncode==0,sealed.stderr
        assert sealed.stdout.startswith(b'Salted__')
        body=MAGIC+wrapped.stdout+sealed.stdout[8:]
        binary=body+hmac.new(secret,body,hashlib.sha256).digest()
        return TRANSPORT+base64.b64encode(binary).decode('ascii')
