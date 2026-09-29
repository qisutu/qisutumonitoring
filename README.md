<!--
Qisutu Monitoring - Open Source Monitoring System
Copyright (C) 2026 Franziska Steps
https://monitoring.qisutu.de

This file is part of Qisutu Monitoring.

Qisutu Monitoring is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Qisutu Monitoring is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with Qisutu Monitoring. If not, see <https://www.gnu.org/licenses/>.

SPDX-FileCopyrightText: 2026 Franziska Steps
SPDX-License-Identifier: AGPL-3.0-or-later
-->

[Deutsch](README.md) | [English](README.en.md) | [Français](README.fr.md) | [Italiano](README.it.md) | [Português (Brasil)](README.pt-BR.md) | [Português (Portugal)](README.pt-PT.md) | [Español](README.es.md) | [Nederlands](README.nl.md) | [Polski](README.pl.md) | [Čeština](README.cs.md) | [Türkçe](README.tr.md)

# Qisutu Monitoring

## Erweiterter Paketstand

Dieses Paket erweitert Windows, Protokolle, SMART, VMware, Datenbanken,
Web-Abläufe, Herstellerprofile, Cloud-/Containerprüfungen, eigene Messwerte,
Langzeitdaten und verteilte Messsammler. Rohdaten bleiben standardmäßig 30 Tage,
stündliche Langzeitwerte 730 Tage gespeichert; beide Fristen sind einstellbar.
Die neuen Formulare sind in allen elf Sprachen verfügbar. Einrichtung,
Voraussetzungen und verbleibende Grenzen stehen in [Erweiterte Überwachung](docs/AUSBAU.md).
Eine vollständige Funktionsgleichheit mit Zabbix wird nicht behauptet.

Qisutu Monitoring ist ein eigenständig installierbares System zur Überwachung von
Geräten, Servern, Netzwerken und Diensten. Die Anwendung basiert auf Python, dem
mitgelieferten Tornado-Webserver und SQLite. Die Bedienung erfolgt über eine
browserbasierte Oberfläche; Konfiguration und Messdaten bleiben auf dem eigenen
Server.

Projektwebsite: https://monitoring.qisutu.de

## Release-Status

Version 1.0.1 ist die erste öffentliche Veröffentlichung von Qisutu Monitoring.
Das vollständige Installationspaket heißt `QisutuMonitoring-1.0.1.tar.gz` und
enthält das Programm, die Weboberfläche, alle elf Sprachdateien und die benötigte
Tornado-Bibliothek.

## Sprachen

Qisutu Monitoring enthält elf Oberflächensprachen: Deutsch (`de`), Englisch
(`en`), Französisch (`fr`), Italienisch (`it`), Brasilianisches Portugiesisch
(`pt-BR`), Europäisches Portugiesisch (`pt-PT`), Spanisch (`es`), Niederländisch
(`nl`), Polnisch (`pl`), Tschechisch (`cs`) und Türkisch (`tr`). Bei der
Installation wird die Ausgangssprache gewählt. Jeder Agent kann seine persönliche
Sprache anschließend selbst festlegen; die Auswahl bleibt nach erneuter Anmeldung
erhalten.

## Voraussetzungen

Die Installation erfolgt auf Linux mit Python 3.9 oder neuer einschließlich
`sqlite3` und `ssl`. Zusätzlich werden `sha256sum`, OpenSSL und `ping` benötigt.
Der Installer kann fehlende Systempakete über die Paketverwaltung installieren.
Für SSH-, SNMP- und Datenbankprüfungen werden die entsprechenden OpenSSH-,
Net-SNMP- und Datenbank-Clients benötigt. Docker, ein zusätzlicher Webserver und
ein externer Datenbankserver sind nicht erforderlich.

Vorhandene PostgreSQL- und MariaDB/MySQL-Clients werden weiterverwendet.
Fehlende Datenbank-Clients werden unabhängig voneinander installiert. Unter
Debian/Ubuntu verhindern alle APT-Installationsaufrufe mit `--no-remove` die
Entfernung bereits installierter Pakete. `--no-upgrade` vermeidet außerdem
Upgrades bereits installierter, ausdrücklich angeforderter Pakete. Erfordert ein
optionaler Datenbank-Client eine Paketentfernung, wird dieser Installationsschritt
mit einem Hinweis übersprungen. Die zugehörigen Datenbankprüfungen benötigen dann
ein manuell bereitgestelltes, kompatibles Clientpaket.

Tornado und alle Dateien der Weboberfläche werden lokal mitgeliefert. Sind die
Systempakete bereits vorhanden, ist die Installation mit `--skip-packages` und der
anschließende Betrieb ohne Internetzugang möglich.

## Installation

Das Release-Paket mit `wget` herunterladen, entpacken und die Installation starten:

    wget https://ftp.qisutu.de/Monitoring/QisutuMonitoring-1.0.1.tar.gz
    tar xzf QisutuMonitoring-1.0.1.tar.gz
    cd QisutuMonitoring
    sudo sh install.sh

Der Installer legt das Programm unter `/opt/netzmonitor` und die Daten unter
`/var/lib/netzmonitor` ab. Er erstellt das Linux-Dienstkonto `netzmonitor` und
richtet den Hintergrunddienst über systemd, OpenRC oder SysV ein, soweit
verfügbar. Bei der Erstinstallation fragt er nach der Sprache und gibt das
Startpasswort für das Konto `admin` aus.

Anschließend `https://SERVER:8787` öffnen, `SERVER` durch die Adresse des
Monitoring-Servers ersetzen und als `admin` anmelden. Das ausgegebene
Startpasswort danach in den persönlichen Einstellungen ändern. Das zunächst
selbstsignierte HTTPS-Zertifikat kann durch ein eigenes Zertifikat ersetzt werden.

Die Sprache kann auch direkt beim Aufruf angegeben werden:

    sudo sh install.sh --language de

`--skip-packages` überspringt die Installation von Systempaketen; diese müssen
bereits vorhanden sein. `--no-start` verhindert den unmittelbaren Dienststart. Vor
der Installation werden die Paketdateien anhand von `SHA256SUMS` geprüft.

## Update

Für spätere Updates das neue vollständige Release-Paket in ein separates
Arbeitsverzeichnis entpacken und dort erneut `sudo sh install.sh` ausführen.
Vorher eine Datensicherung erstellen. Der Installer übernimmt die Programmdateien
und erhält vorhandene Konten, Sprachen, Geräte, Konfiguration und Messwerte. Er
erstellt keine automatische Sicherung. Anschließend die Weboberfläche mit Strg+F5
neu laden.

## Verzeichnisstruktur

- `netzmonitor/` – Python-Anwendung und Überwachungsfunktionen
- `netzmonitor/static/` – Weboberfläche, Bilder und lokale JavaScript- und CSS-Dateien
- `netzmonitor/languages/` – elf Sprachdateien der Weboberfläche
- `vendor/` – mitgelieferter Tornado-Webserver
- `tests/` – automatisierte Tests
- `tools/` – Werkzeuge für die Paketpflege

## Geräteverwaltung und Netzwerksuche

Geräte werden einzeln angelegt oder über die Gerätesuche aus eigenen
Netzwerkbereichen übernommen. Gruppen, Vorlagen, Suchfilter und
Mehrfachbearbeitung erleichtern die Verwaltung größerer Bestände. Unter
„Einrichten“ werden die benötigten Prüfungen und Zugangsdaten ausgewählt, getestet
und gespeichert. Ein Verbindungstest allein speichert noch keine
Gerätekonfiguration.

## Server und Netzwerkschnittstellen

Linux-Systeme werden über SSH und geeignete Geräte über SNMP überwacht. Erfasst
werden unter anderem CPU, Arbeitsspeicher, Dateisysteme, Linux-Prozesse und
Dienste, Festplattenleistung sowie Netzwerkschnittstellen. Für Switch-Ports und
andere Schnittstellen stehen Datenverkehr, Auslastung, Fehler und
Verlaufsdiagramme zur Verfügung. Windows und Hyper-V werden über WinRM mit HTTPS
angebunden; weitere Prüfungen unterstützen VMware, Redfish, Synology und USV.

## Dienste, Datenbanken und Drucker

Qisutu Monitoring prüft Erreichbarkeit per Ping, HTTP/HTTPS- und TCP-Dienste,
DNS-Antworten und TLS-Zertifikate. SMTP-, IMAP- und POP3-Prüfungen testen die
Protokollverbindung, ohne E-Mails zu versenden oder Nachrichten abzurufen.
MariaDB/MySQL und PostgreSQL werden über Leseabfragen überwacht. Drucker liefern
Status, Verbrauchsmaterial und Zähler über SNMP. Die verfügbaren Messwerte hängen
vom jeweiligen Gerät und den eingerichteten Zugriffsrechten ab.

## Netzwerkqualität und Datenverkehr

Die Netzwerkqualität wird anhand von Paketverlust, Antwortzeiten und deren
Schwankungen ausgewertet. Ein integrierter Empfänger verarbeitet NetFlow v5/v9 und
IPFIX und zeigt Datenverkehr nach IP-Adressen und Ports. Dazu muss ein geeignetes
Netzwerkgerät seine Flow-Daten an den Monitoring-Server senden. Der Empfang
verwendet bei entsprechender Einrichtung standardmäßig UDP-Port 2055.

## Verläufe und Geräteverbindungen

Verlaufsdiagramme zeigen die Entwicklung der Messwerte. Messwerte und Ereignisse
werden regulär 30 Tage aufbewahrt. Geräteabhängigkeiten sowie manuell eingetragene
Kabel- und WLAN-Verbindungen lassen sich grafisch darstellen und verwalten.

## Agenten und persönliche Einstellungen

Unter „Agenten“ werden weitere Benutzerkonten mit Benutzername, Name, Passwort und
Sprache angelegt. Alle Agenten besitzen dieselben Rechte. Konten können
bearbeitet, deaktiviert und gelöscht werden; das eigene Konto kann nicht
deaktiviert oder gelöscht werden. Passwörter müssen 12 bis 256 Zeichen lang sein.

Das Zahnrad unten links öffnet die persönlichen Einstellungen für Sprache und
Passwort. Bei eingeklappter Navigation ist das Benutzermenü über den Avatar
erreichbar. Die Sprache wird am Konto gespeichert und gilt auch in anderen
Browsern. Benutzereingaben und Antworten der überwachten Geräte werden nicht
automatisch übersetzt.

## E-Mail-Meldungen und Qisutu-Anbindung

Unter „Meldungen“ können E-Mail und die Verbindung zum Qisutu-Ticketsystem
getrennt aktiviert werden. Für E-Mail werden SMTP-Server, Port, Verschlüsselung,
Absender und Empfänger eingerichtet. Benutzername und Passwort werden nur bei
erforderlicher Anmeldung benötigt. Der Verbindungstest verschickt keine Testmail.

Für die Qisutu-Anbindung wird das passende Monitoring-Add-on separat im
Ticketsystem installiert. Die dort angezeigte Verbindungsadresse und der
Zugangsschlüssel werden in Qisutu Monitoring eingetragen. Der Verbindungstest
erzeugt kein Ticket. Das Add-on gehört nicht zu diesem Paket.

Meldungen können auf Gruppen und einzelne Geräte begrenzt werden. Zustandswechsel
und Entwarnungen werden übermittelt; eine unveränderte Störung wird nicht bei
jeder Prüfung erneut gemeldet. Wartende Meldungen bleiben gespeichert und werden
bei Verbindungsfehlern erneut versucht. Das Abschalten eines Versandwegs oder eine
Änderung seines Ziels beziehungsweise Gerätebereichs verwirft dessen wartende
Meldungen.

## Gerätefreischaltung

Bis zu zehn Geräte sind kostenlos nutzbar. Eine installationsgebundene
Freischaltdatei ermöglicht 100, 500 oder unbegrenzt viele Geräte. Alle
Messfunktionen stehen in jeder Stufe zur Verfügung. Unter „Freischaltung“ wird die
Installationskennung angezeigt. Für eine Freischaltung den Hersteller über
[monitoring.qisutu.de](https://monitoring.qisutu.de) kontaktieren und die Kennung
angeben; die erhaltene `.nmlic`-Datei anschließend hochladen, prüfen und
übernehmen. Der Monitoring-Server benötigt dafür keinen Internetzugang.

Nach Vertragsablauf können höchstens zehn ausgewählte Geräte weiter überwacht
werden. Sind mehr Geräte vorhanden und fehlt eine Auswahl, sind die
Geräteprüfungen bis zur Auswahl gesperrt. Vorhandene Daten bleiben im Rahmen der
regulären Aufbewahrungsfrist erhalten. Prüfungen und Switch-Ports zählen nicht
zusätzlich; ein pausiertes freigeschaltetes Gerät belegt weiterhin einen Platz.

## Betrieb und Datenhaltung

Die Datenbank liegt unter `/var/lib/netzmonitor/monitoring.sqlite3`, die
Serverkonfiguration unter `/var/lib/netzmonitor/config.json`. Die Weboberfläche
verwendet standardmäßig TCP-Port 8787. Bind-Adresse und Port können in
`config.json` geändert werden; danach den Dienst neu starten. Eigene
HTTPS-Zertifikate ersetzen `server.crt` und `server.key` im Datenverzeichnis und
werden nach einem Neustart aktiv. Der private Schlüssel darf nur für den
Dienstbenutzer lesbar sein.

Der Verwaltungsbefehl wird als `/usr/local/bin/netzmonitor` installiert:

    sudo netzmonitor status
    sudo netzmonitor restart
    sudo netzmonitor stop
    sudo netzmonitor start
    sudo netzmonitor doctor

Anwendungsprotokolle stehen in `/var/lib/netzmonitor/netzmonitor.log`, unter
systemd zusätzlich im Journal. Ein vergessenes Passwort wird mit
`sudo netzmonitor password` für `admin` oder mit
`sudo netzmonitor password BENUTZERNAME` für ein anderes Konto zurückgesetzt. Der
Installer verändert keine globale Firewall.

## Datensicherung

Eine konsistente Sicherung der Datenbank ist auch im laufenden Betrieb möglich:

    sudo netzmonitor backup /root/netzmonitor-backup.sqlite3

Eine vorhandene Zieldatei wird nicht überschrieben. Zusätzlich `config.json`,
`server.crt` und `server.key` sichern. Für eine vollständige Kopie des
Datenverzeichnisses den Dienst vorher stoppen und anschließend wieder starten.
Sicherungen enthalten Zugangsdaten und müssen geschützt aufbewahrt werden.

## Deinstallation

    sudo netzmonitor uninstall

Die Löschung wird mit `JA` bestätigt. Entfernt werden Programm, Monitoring-Daten,
Agentenkonten, Freischaltung, Zertifikate, eigene Protokolle, Dienst und das
dedizierte Linux-Dienstkonto. Alternativ kann `sudo sh uninstall.sh` aus dem
entpackten Paket ausgeführt werden. Gemeinsam genutzte Betriebssystempakete, das
Systemjournal, externe Sicherungen und separat entpackte Pakete bleiben erhalten.

## Projektdokumentation

- [CHANGELOG.md](CHANGELOG.md) – Versionshinweise zu veröffentlichten Releases
- [DEVELOPMENT.md](DEVELOPMENT.md) – Entwicklung, Tests und Erstellen der Paketprüfsummen
- [docs/LICENSE-FORMAT.md](docs/LICENSE-FORMAT.md) – technische Beschreibung der Freischaltdateien
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) – mitgelieferte Fremdsoftware und Lizenzhinweise

## Lizenz

Qisutu Monitoring ist unter der GNU Affero General Public License, Version 3 oder
einer späteren Version (`AGPL-3.0-or-later`), lizenziert. Die vollständigen
Lizenzbedingungen stehen in [LICENSE](LICENSE).

Copyright (C) 2026 Franziska Steps.

## Drittanbieter-Software

Mitgelieferte Drittanbieterdateien behalten ihre ursprünglichen Copyright- und
Lizenzhinweise. Tornado wird unter der Apache License 2.0 mitgeliefert. Die
vollständigen Hinweise und der Verweis auf den Lizenztext stehen in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Diese Lizenzen betreffen die
jeweiligen Fremdkomponenten.
