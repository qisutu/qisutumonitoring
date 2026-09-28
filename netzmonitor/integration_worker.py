"""Subprocess entry point: total deadlines include DNS and all protocol steps."""
import imaplib
import json
import poplib
import smtplib
import socket
import ssl
import sys
from .integration_common import CheckFailure


def run(data):
    cfg,kind=data['config'],data['kind'];timeout=min(data['timeout'],10);inventory=[]
    try:
        if kind=='fingerprint':
            from .check_protocols import inspect_certificate
            return dict(kind='ok',fingerprint=inspect_certificate(cfg,timeout))
        if kind in ('tls','dns','smtp','imap','pop3'):
            from .check_protocols import tls_check,dns_check,mail_check
            metrics=tls_check(cfg,timeout) if kind=='tls' else dns_check(cfg,timeout) if kind=='dns' else mail_check(kind,cfg,timeout)
        elif kind in ('windows','hyperv'):
            from .check_windows import windows_check,hyperv_check
            if kind=='windows':metrics=windows_check(cfg,timeout)
            else:metrics,inventory=hyperv_check(cfg,timeout)
        elif kind=='vmware':
            from .check_vmware import vmware_check
            metrics,inventory=vmware_check(cfg,timeout)
        elif kind=='printer':
            from .check_printer import printer_check
            return printer_check(cfg,data['timeout'],diagnostic=data.get('diagnostic',False))
        elif kind in ('redfish','synology','ups'):
            from .check_hardware import redfish_check,snmp_profile
            metrics=redfish_check(cfg,timeout) if kind=='redfish' else snmp_profile(kind,cfg,data['timeout'])
        elif kind=='database':
            from .check_database import database_check
            metrics=database_check(cfg,data['timeout'])
        elif kind=='quality':
            from .check_quality import quality_check
            metrics=quality_check(cfg,data['timeout'])
        else:raise CheckFailure('Unbekannte Prüfungsart.')
        if not metrics:raise CheckFailure('Keine Messwerte geliefert. Auswahl und Leserechte prüfen.')
        return dict(kind='ok',metrics=metrics,inventory=inventory,message='')
    except CheckFailure as exc:message=str(exc)
    except ssl.SSLCertVerificationError:message='Server-Zertifikat nicht vertrauenswürdig oder abgelaufen. Zertifikat prüfen; bei eigener CA den Fingerabdruck bestätigen.'
    except ssl.SSLError:message='TLS-Verbindung fehlgeschlagen. Port, Verschlüsselung und Zertifikat prüfen.'
    except socket.gaierror:message='Servername konnte nicht aufgelöst werden.'
    except (TimeoutError,socket.timeout):message='Antwortfrist überschritten. Adresse, Port und Firewall prüfen.'
    except (smtplib.SMTPAuthenticationError,imaplib.IMAP4.error,poplib.error_proto):message='Mail-Protokoll oder Anmeldung abgelehnt. Zugang und gewünschte Verschlüsselung prüfen.'
    except (OSError,smtplib.SMTPException):message='Verbindung oder Protokoll fehlgeschlagen. Adresse, Port und Freigabe prüfen.'
    except Exception:message='Antwortformat wird nicht unterstützt. Geräteversion und Schnittstellenfreigabe prüfen.'
    return dict(kind='error',metrics=[],message=message,inventory=[])


if __name__=='__main__':
    print(json.dumps(run(json.load(sys.stdin)),ensure_ascii=False))
