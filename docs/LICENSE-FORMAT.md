# Freischaltdateiformat

Technische Referenz für Qisutu Monitoring 1.0.1. Bedienung und Geräteauswahl sind in den READMEs beschrieben: [Deutsch](../README.md) · [English](../README.en.md).

## Bedienung

Hersteller erstellt die .nmlic-Datei mit dem lokalen HTML-Formular und
versendet sie als E-Mail-Anhang. Der Kunde lädt sie im internen Monitoring
unter „Freischaltung“ hoch. Kein externer Dienst wird aufgerufen.
Die READMEs beschreiben den Ablauf ohne technische Schlüsselbedienung.

## Verschlüsselte Hülle (Version 2)

Die Datei besteht aus folgenden Binärfeldern in dieser Reihenfolge:

- 8 Bytes: Magic 4E 4D 4C 49 43 02 0D 0A (NMLIC, Version, CR, LF).
- 384 Bytes: RSA-OAEP/SHA-256/MGF1-SHA-256-verschlüsseltes Dateigeheimnis.
- 8 Bytes: zufälliges PBKDF2-Salt.
- n Bytes: AES-256-CBC/PKCS#7-verschlüsseltes, signiertes JSON-Dokument.
- 32 Bytes: HMAC-SHA-256 über alle vorhergehenden Bytes.

Für jede Datei werden ein zufälliges 32-Byte-Geheimnis und ein neues Salt
erzeugt. PBKDF2-HMAC-SHA-256 mit 100.000 Iterationen und dem kleingeschriebenen
ASCII-Hextext des Geheimnisses ergibt 48 Bytes: 32 Bytes AES-Schlüssel,
16 Bytes IV. Der HMAC verwendet das rohe 32-Byte-Geheimnis als Schlüssel.
Die HMAC wird vor der AES-Entschlüsselung zeitkonstant geprüft.
Maximale Dateigröße: 32 KiB; inneres signiertes Dokument: maximal 16 KiB.

Das innere Format ist netzmonitor-license-v1 mit RSA-3072-PSS,
SHA-256 und 32 Bytes PSS-Salt. Die Signatur wird mit dem mitgelieferten
Hersteller-Prüfschlüssel geprüft. Verschlüsselung allein ersetzt die
Signaturprüfung nicht. Nach der Entschlüsselung werden Signatur,
Installationsbindung, Vertragsstufe und Gültigkeitszeitraum geprüft.

## Installationsspezifischer Empfang

Bei der ersten Anforderung einer Kennung wird automatisch ein RSA-3072-
Empfangspaar erzeugt und in license_recipient in der lokalen Datenbank
gespeichert. Parallele Anforderungen verwenden dasselbe gespeicherte Paar.
Nur der öffentliche Teil erscheint in netzmonitor-request-v2. Die kopierbare
Kennung ist NMREQ2. gefolgt von URL-sicherem Base64 des UTF-8-Anfrage-JSON.
Sie enthält weder einen privaten Schlüssel noch Zugangsdaten zu Geräten.

Der Browser des Herstellers signiert und verschlüsselt lokal über Web Crypto.
Das Monitoring entschlüsselt über sein bereits benötigtes OpenSSL. Keine
neuen Python-Zusatzpakete erforderlich. Temporäre Geheimnisse werden über
private Dateien innerhalb eines geschützten temporären Verzeichnisses
übergeben, nicht über Prozessargumente. Kein Schlüssel wird protokolliert.

Der Datei-Upload überträgt die Binärdaten intern als NMLIC2: plus Standard-
Base64 innerhalb der bestehenden authentifizierten, CSRF-geschützten API.
Nach Annahme wird das geprüfte signierte Dokument wie bisher lokal gespeichert.
Bestehende gültige JSON-Dateien bleiben kompatibel. Die Empfängerinformationen
werden zusammen mit der vollständigen Datenbank gesichert bzw. migriert.

## Schutzumfang

Die Kundendatei enthält keine lesbaren Vertragsdaten und kann nur mit den
Empfangsdaten der vorgesehenen Installation entschlüsselt werden. Nach dem
Upload zeigt die authentifizierte Monitoring-Oberfläche Vertragsdaten bewusst
an. Ein Administrator mit vollständigem Zugriff auf Quellcode und Datenbank
kann die eigene Entschlüsselung nachvollziehen; die Daten sind nicht vor dem
Betreiber seiner eigenen Installation geheim. Hersteller-Signaturen kann er
mit dem öffentlichen Prüfschlüssel nicht selbst ausstellen.

Referenzen der verwendeten Standardfunktionen:
https://www.w3.org/TR/2017/REC-WebCryptoAPI-20170126/
https://docs.openssl.org/3.0/man1/openssl-enc/
https://docs.openssl.org/master/man1/openssl-enc/
