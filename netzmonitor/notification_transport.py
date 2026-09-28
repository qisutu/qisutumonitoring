"""Bounded subprocess for SMTP and authenticated Qisutu events; no network redirects."""
import json
import smtplib
import socket
import ssl
import sys
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def tls_context(cfg):
    context = ssl.create_default_context()
    if cfg.get('ca'):
        context.load_verify_locations(cadata=cfg['ca'])
    return context


def smtp(cfg, event, test):
    context = tls_context(cfg)
    client = (smtplib.SMTP_SSL(cfg['host'],cfg['port'],timeout=8,context=context)
              if cfg['security']=='tls' else smtplib.SMTP(cfg['host'],cfg['port'],timeout=8))
    try:
        client.ehlo_or_helo_if_needed()
        if cfg['security']=='starttls':
            client.starttls(context=context)
            client.ehlo()
        if cfg['username']:
            client.login(cfg['username'],cfg['password'])
        if test:
            code, _ = client.noop()
            if code != 250:
                raise smtplib.SMTPException()
            return dict(ok=True,message='Mailserver erreichbar; Verbindung und gegebenenfalls Anmeldung erfolgreich. Es wurde keine E-Mail versendet. Die Zustellung an den Empfänger ist damit noch nicht geprüft.')
        msg = EmailMessage()
        msg['From'],msg['To'] = cfg['sender'],cfg['recipient']
        msg['Subject'] = '[Monitoring] ' + event['summary']
        msg['Date'] = format_datetime(datetime.fromisoformat(event['occurred_at']))
        msg['Message-ID'] = '<' + event['event_id'] + '@netzmonitor.local>'
        text = event['details'] + '\nZeitpunkt: ' + event['occurred_at']
        if event.get('event_url'):
            text += '\nMonitoring öffnen: ' + event['event_url']
        msg.set_content(text + '\n',charset='utf-8')
        client.send_message(msg)
        return dict(ok=True,message='Vom Mailserver angenommen.')
    finally:
        # A failed QUIT after SMTP acceptance must not turn a successful send into a retry.
        client.close()


def qisutu(cfg, event, test):
    url = cfg['url'] + ('/test' if test else '')
    req = Request(url, data=None if test else json.dumps(event,ensure_ascii=False).encode('utf-8'),
        method='GET' if test else 'POST',
        headers={'Authorization':'Bearer '+cfg['token'],'Content-Type':'application/json','Accept':'application/json'})
    opener = build_opener(ProxyHandler({}),HTTPSHandler(context=tls_context(cfg)),NoRedirect())
    with opener.open(req, timeout=8) as response:
        body = response.read(131073)
        if len(body)>131072:
            raise ValueError()
        result = json.loads(body).get('data',{})
        if test:
            if result.get('connected') is not True or result.get('source_type') != 'qisutu':
                return dict(ok=False,message='Die Verbindung gehört nicht zum Systemtyp „Qisutu Monitoring“. Im Add-on die passende Verbindung auswählen.')
            return dict(ok=True,message='Qisutu erreichbar, Zugangsschlüssel gültig und Verbindung aktiv. Es wurde kein Ticket angelegt.')
        if response.status != 202 or result.get('accepted') != 1 or not result.get('results') or result['results'][0].get('accepted') is not True or result['results'][0].get('status') not in ('processed','ignored','suppressed','stale'):
            raise ValueError()
        return dict(ok=True,message='Von Qisutu angenommen.')


def run(data):
    try:
        return (smtp if data['channel']=='email' else qisutu)(data['config'],data.get('payload'),data.get('test',False))
    except HTTPError as exc:
        messages={401:'Qisutu hat den Zugangsschlüssel abgelehnt.',403:'Der Zugangsschlüssel passt nicht zu dieser Verbindung oder besitzt keine Berechtigung.',
                  404:'Qisutu-Verbindung nicht gefunden. Adresse, aktiven Zustand und Add-on-Version 1.1.0 prüfen.',
                  429:'Qisutu begrenzt die Anfragen. Die Meldung wird später erneut übertragen.'}
        message=messages.get(exc.code,'Qisutu hat die Anfrage abgelehnt (HTTP %s). Adresse und Add-on prüfen.' % exc.code)
    except smtplib.SMTPAuthenticationError:
        message='Anmeldung am Mailserver abgelehnt. Benutzername und Passwort prüfen.'
    except smtplib.SMTPRecipientsRefused:
        message='Der Mailserver hat den Empfänger abgelehnt. Empfängeradresse und Relay-Freigabe prüfen.'
    except smtplib.SMTPSenderRefused:
        message='Der Mailserver hat den Absender abgelehnt. Absenderadresse und Relay-Freigabe prüfen.'
    except ssl.SSLCertVerificationError:
        message='Das Serverzertifikat ist nicht vertrauenswürdig oder passt nicht zum Servernamen. Bei interner CA ihr Zertifikat hochladen.'
    except URLError as exc:
        message=('Das Qisutu-Zertifikat ist nicht vertrauenswürdig oder passt nicht zum Servernamen. Bei interner CA ihr Zertifikat hochladen.'
            if isinstance(exc.reason,ssl.SSLCertVerificationError) else 'Qisutu nicht erreichbar. Serveradresse, DNS und Firewall prüfen.')
    except (TimeoutError,socket.timeout):
        message='Verbindungszeit überschritten. Serveradresse und Firewall prüfen.'
    except (ssl.SSLError,smtplib.SMTPException):
        message='Mailserver-Verbindung fehlgeschlagen. Port, Verschlüsselung und Relay-Freigabe prüfen.'
    except OSError:
        message='Server nicht erreichbar. Serveradresse, DNS und Firewall prüfen.'
    except Exception:
        message='Unerwartete Serverantwort. Serveradresse und Schnittstellenversion prüfen.'
    return dict(ok=False,message=message)


if __name__=='__main__':
    print(json.dumps(run(json.load(sys.stdin)),ensure_ascii=False))
