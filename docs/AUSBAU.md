# Erweiterte Überwachung

Dieses Paket erweitert den vorhandenen Stand von Qisutu Monitoring 1.0.1.
Es enthält die vollständige Anwendung einschließlich Installer, Oberfläche,
Sprachdateien und Tests. Die Erweiterungen sind unten konkret beschrieben;
eine vollständige Funktionsgleichheit mit Zabbix ist damit nicht erreicht.

## Funktionsumfang

| Bereich | In diesem Paket enthalten | Grenze des Umfangs |
|---|---|---|
| Windows | Datenträgerdurchsatz, IOPS, Warteschlangen, Lese-/Schreiblatenz, Netzwerkdurchsatz und Auslastung, CPU/RAM/I/O nach Prozess, weitere WMI-Leistungszähler | WinRM/WMI über HTTPS; kein Windows-Agent. Verfügbarkeit hängt von den WMI-Klassen des Zielsystems ab. |
| Protokolle | Windows-Ereignisse mit Kanal-, ID-, Quellen- und Textfilter; letzte Meldungen; Linux-systemd-Journal über SSH | Zeitfensterabfrage, kein persistenter Cursor für beliebige rotierende Logdateien; überlappende Fenster können dieselben Ereignisse erneut enthalten. |
| SMART | ATA-Einzelattribute, Sektorenfehler, Laufzeit, Temperatur; NVMe-Verschleiß, Reserve und Fehlerzähler | SSH mit lesendem smartctl-Zugriff erforderlich. Herstellerabhängige Rohwerte werden nicht als universelle Gesundheitswerte interpretiert. |
| VMware | Automatische Auswahl passender CPU-, Speicher-, Datenträger-, Datastore- und Netzwerkzähler; Instanzen und letzte Ereignistexte | Voreingestellt höchstens 50, einstellbar bis 200 Objekte je Prüfung. Fehlende Zähler bleiben sichtbar; keine automatische Aufteilung auf mehrere Prüfungen. |
| Datenbanken | PostgreSQL- und MySQL/MariaDB-Replikationswerte; SQL Server über ODBC: Sitzungen, Größen, wartende Anforderungen, Leistungszähler und eigene SELECT-Abfrage | Rollenabhängige Leserechte erforderlich. Kein vollständiger Satz von Datenbank- oder Replikationstopologie-Vorlagen. |
| Web | Mehrere GET-/POST-Schritte mit Cookies, Formulardaten, Inhaltsprüfung und extrahierten Sitzungsvariablen | HTTP-Szenarien, keine Ausführung von JavaScript im Browser. Weiterleitungen bleiben auf demselben Server. |
| Herstellerprofile | SNMP-Grundprofile für Cisco, FortiGate und MikroTik; eigene skalare OIDs und Tabellen, Skalierung, Sollwert und Grenzwerte | Kleine Startauswahl; keine umfassende Hersteller-/Modellbibliothek. Gerätespezifische OIDs müssen unterstützt und freigegeben sein. |
| Cloud und Container | Docker-Zustand und Leistungswerte, Kubernetes-Nodes/Pods und Metrics API, AWS CloudWatch, Azure Monitor | Abfrage vorhandener Schnittstellen mit expliziten Zugangsdaten; kein Cloud-Asset-Management und keine Übernahme aller Anbieter-Templates. |
| Eigene Messwerte | HTTP/JSON, SSH-Befehl, SNMP-OID, Prometheus-Textformat, berechnete Werte aus vorhandenen Messreihen | Begrenzte JSON-Pfade und arithmetische Formeln; keine vollständige Zabbix-Item-, Preprocessing- oder Trigger-Sprache. |
| Langzeitdaten | Einstellbare Rohdaten- und Trendaufbewahrung; stündliche Aggregation mit gewichteten Mittelwerten, Minima, Maxima und Zustandszählung; Diagramme bis zwei Jahre | SQLite bleibt die zentrale Datenbank. Stundenaggregate ersetzen keine Detailwerte; keine TimescaleDB- oder Clusterarchitektur. |
| Verteilte Erfassung | Linux-Messsammler mit Gerätezuordnung, HTTPS, individuellem Zugangsschlüssel, dauerhaftem lokalen Puffer, Wiederholung und Schutz vor doppelten Messungen; einstellbare zentrale Parallelität | Keine automatische Kollektorübernahme, keine Hochverfügbarkeit des zentralen Servers. NetFlow/IPFIX wird weiterhin zentral empfangen. |

Die bereits vorhandene Vorlagenverwaltung unterstützt dauerhafte Zuordnungen
zwischen Vorlagen und Geräten, Vorlagenrevisionen und die Anzeige von Geräten
mit älterem Vorlagenstand. Über **Zugeordnete aktualisieren** lassen sich
Dienstprüfungen, Ressourcenregeln und zusätzliche Prüfungen nach einer Vorschau
gemeinsam auf die zugeordneten Geräte übertragen. Bestehende Prüfungen werden
über ihre Zuordnung wiederverwendet; lokale Zusatzprüfungen bleiben erhalten.
Diese Funktion war schon vor den hier beschriebenen Erweiterungen vorhanden.

Die konkreten Grenzen sind fehlende Verknüpfungen von Vorlage zu Vorlage
(mehrstufige Vererbung) und die fehlende automatische Übertragung neuer
Vorlagenrevisionen ohne den vorhandenen Vorschau-/Übernahmeschritt. Aus einer
Vorlage entfernte Prüfungen werden auf den Geräten nicht automatisch gelöscht.
Die pauschale Aussage, Template-Vererbung fehle insgesamt, wäre deshalb falsch.

Weitere Zabbix-Funktionen wie allgemeine Triggerausdrücke über Zeitfenster und
vollständige Low-Level-Discovery-Regeln sind mit den oben genannten Erweiterungen
nicht nachgebaut. Die Spalte mit Grenzen gehört zum Funktionsumfang dieses Pakets
und darf bei einem Vergleich nicht weggelassen werden.

## Installation und Update

Das ZIP entpacken, in das Verzeichnis `Monitoring` wechseln und den vorhandenen
Installer ausführen:

```sh
sudo sh install.sh
```

Vor einem Update eine Sicherung erstellen. Der Installer erhält die bestehenden
Konfigurations- und Messdaten. Neue Tabellen und stündliche Trends werden beim
Start angelegt; vorhandene Rohdaten werden einmalig in Trends übernommen.
Bei einer großen bestehenden Datenbank kann dieser erste Start länger dauern.
Konten, Freischaltungen und Gerätegrenzen bleiben Bestandteil der Anwendung.

Unter **Geräte → Einrichten → Weitere Prüfungen** lassen sich die neuen
Prüfungsarten hinzufügen. Die Windows-, VMware- und Datenbankformulare enthalten
zusätzliche auswählbare Messbereiche. Vorhandene Prüfungen erhalten diese
zusätzlichen Abfragen erst, wenn die entsprechenden Optionen eingeschaltet werden.
Prüfungen können vor dem Speichern mit **Verbindung prüfen** getestet werden.

## Windows und Protokolle

Das mitgelieferte `netzmonitor/static/Windows-Einrichtung.ps1` richtet WinRM über
HTTPS sowie die erforderlichen lesenden WMI-Rechte ein. Es nimmt das vorhandene
Monitoring-Konto zusätzlich in die sprachunabhängig bestimmten Gruppen für
Remoteverwaltung, Ereignisprotokolle und Leistungsüberwachung auf. Nach einer
Erweiterung der Gruppenmitgliedschaft eine neue Sitzung verwenden. Bei einem
entfernten Messsammler muss dessen IP-Adresse als `MonitorAddress` freigegeben sein.

Unter Windows lassen sich Prozessnamen zeilenweise angeben, zum Beispiel
`sqlservr.exe` oder `w3wp`. Gleichnamige Instanzen werden zusammengefasst;
der CPU-Wert wird auf die Zahl logischer Prozessoren normiert. Ein ausdrücklich
ausgewählter, fehlender Prozess meldet einen kritischen Zustand.

Weitere Zähler werden als WMI-Klasse und Eigenschaft eingetragen, zum Beispiel:

```text
Win32_PerfFormattedData_PerfOS_Processor.PercentProcessorTime
```

Leistungszähler für Datenträgerlatenzen benötigen zwei Rohdatenstände. Ohne
abgeschlossene I/O-Vorgänge im Messfenster ist die Latenz unbekannt und nicht null.

Für Ereignisse **Fehlerereignisse** einschalten und die gewünschten Kanäle wählen.
Ohne Ereignis-IDs werden Fehlerereignisse gelesen; mit IDs werden genau diese IDs
unabhängig vom Schweregrad geprüft. WMI stellt nicht sämtliche Windows-Kanäle
bereit. Maximal 1.000 Ereignisse je Kanal werden gelesen und bis zu fünf Texte
angezeigt; eine erreichte Grenze wird ausgewiesen.

Die Linux-Protokollprüfung benötigt einen SSH-Benutzer mit Leserechten auf das
systemd-Journal. Sie liest bis zu 5.000 Einträge im gewählten Zeitfenster und
filtert optional nach Systemd-Dienst und Text. `Schweregrad bis` entspricht den
systemd-Prioritäten: 0 ist emergency, 3 error, 4 warning, 6 info, 7 debug.

## Hersteller und eigene Messwerte

Die Herstellerprofile ergänzen den bisherigen allgemeinen SNMP-Zugang:

- Cisco: CPU über fünf Minuten sowie belegter/freier Speicher nach Instanz.
- FortiGate: CPU, RAM, Sitzungen und IPsec-Phase-2-Tunnelzustand; Status 2 bedeutet
  aktiv. Nicht vorhandene Tunnel-OIDs werden als fehlend gemeldet.
- MikroTik: Temperatur und Spannung bei Geräten, die diese Health-OIDs anbieten.

Eigene OIDs können einen Faktor, eine Einheit, Warn-/Kritisch-Grenzen, einen
erwarteten Wert oder eine Änderung pro Sekunde erhalten. Bei Zählern wird nach
einem Reset oder einer längeren Lücke zunächst eine neue Ausgangsmessung
abgewartet. Ein kompletter Zählerüberlauf wird nicht automatisch rekonstruiert.

HTTP/JSON und eigene SSH-Prüfungen verwenden beispielsweise `$.queue.length`,
`$.volumes[0].used` oder `$.volumes[*].used`. Filterausdrücke und ausführbarer Code
in JSON-Pfaden werden nicht unterstützt. Der SSH-Befehl läuft ausdrücklich mit
den Rechten des hinterlegten Kontos; dafür nur notwendige Leserechte vergeben.
Seine Ausgabe muss eine Zahl oder das konfigurierte JSON enthalten.

Prometheus-Exporter werden im Textformat gelesen; optional begrenzen Namen die
Auswahl. Serien behalten ihre Labels. Dies ersetzt keinen PromQL-Server und
berechnet aus einem Prometheus-Counter nicht automatisch eine Rate.

Berechnete Messwerte erlauben `+`, `-`, `*`, `/`, `%`, Klammern sowie `min`, `max`,
`abs` und `round`. Beispiel: `100 * used / total`. Quellen werden über die
Messreihenauswahl zugeordnet. Fehlende, pausierte oder veraltete Quellen ergeben
einen Prüffehler. Das Höchstalter wird zusätzlich durch Prüfintervall und
Antwortfrist begrenzt. Zyklen und zeitbezogene Triggerlogik sind nicht vorgesehen.

## Web-Szenarien

Ein Ablauf kann bis zu 20 Schritte enthalten. Cookies bleiben zwischen den
Schritten erhalten. GET und Formular-POST, erlaubte HTTP-Codes und erwarteter
Text werden je Schritt festgelegt. Ein regulärer Ausdruck kann einen Wert für
einen späteren Schritt extrahieren; die erste Capture-Gruppe wird verwendet.

`{{username}}`, `{{password}}`, `{{token}}` und zuvor definierte Variablen werden
in Pfad oder Formularinhalt URL-kodiert eingesetzt. Beispiel:
`user={{username}}&password={{password}}&csrf={{csrf}}`.
Zugangsdaten erfordern HTTPS. Bei einem fehlgeschlagenen Schritt endet der Ablauf.
Die Gesamtantwortfrist umfasst alle Schritte. JavaScript-Logins benötigen eine
anderweitig erreichbare API oder ein künftig zusätzliches Browser-Monitoring.

## Datenbanken, Cloud und Container

SQL Server benötigt `python3-pyodbc` und **Microsoft ODBC Driver 18 for SQL Server**
auf dem ausführenden zentralen Server bzw. Messsammler. Die Microsoft-Paketquelle
muss zur Linux-Distribution passen; die Anwendung installiert sie nicht selbst.
Der Treiber prüft das TLS-Serverzertifikat. Der Monitoring-Benutzer benötigt
passende Leserechte, insbesondere `VIEW SERVER STATE` bzw. bei neueren
SQL-Server-Versionen `VIEW SERVER PERFORMANCE STATE`. `ApplicationIntent=ReadOnly`
ersetzt keine eingeschränkten Datenbankrechte. Eigene Abfragen sind auf eine
SELECT-Anweisung beschränkt; Kommentare, Mehrfachanweisungen und SELECT INTO
werden abgelehnt.

Bei PostgreSQL benötigt die Statistikabfrage beispielsweise `pg_read_all_stats`.
Ein Primärserver liefert Anzahl der verbundenen Replikate und deren gemeldeten
Replay-Lag; ein Standby liefert unter anderem ausstehende WAL-Bytes. Nicht
verfügbare Lag-Werte bleiben unbekannt. MySQL/MariaDB liest die Replikationsansicht
mit den dafür nötigen Replikations-/Monitor-Leserechten; die Benennung unterscheidet
sich nach Version. Die bisherige TLS-Konfiguration der Datenbankprüfung gilt weiter.

Docker wird über eine HTTPS-API abgefragt, optional mit Client-Zertifikat und
privatem Schlüssel im PEM-Format. Eine entsprechend eingeschränkte API-Freigabe
ist Voraussetzung. Der Server selbst benötigt keine Docker-Installation.
CPU wird als Prozent pro Kern dargestellt: 200 % entspricht zwei ausgelasteten
Kernen. Netzwerk- und I/O-Raten benötigen zwei gültige Zählerstände. Bis zu 100
Container je Prüfung; ausdrücklich erwartete, fehlende Container sind kritisch.

Kubernetes benötigt einen Service-Account-Token mit lesenden Rechten auf die
ausgewählten Pods und gegebenenfalls Nodes. CPU/RAM erfordern die Metrics API und
entsprechende Leserechte. Eine Namespace-Auswahl beschränkt die Pod-Abfragen und
lässt clusterweite Nodes aus. Es werden maximal 2.000 Objekte je Listenabfrage
verarbeitet. Das Fehlen der Metrics API wird ausdrücklich angezeigt.

AWS benötigt Region, Access Key und Secret Key, bei temporären Zugangsdaten
zusätzlich Session-Token. Rechte: `cloudwatch:ListMetrics` und
`cloudwatch:GetMetricData`. Namensraum, Namen und Dimensionen begrenzen die Auswahl
auf maximal 200 Reihen. Die Abfrage liest den jüngsten verfügbaren Punkt aus
einem 15-Minuten-Fenster; der Anbieter-Zeitstempel steht im Messwerttext.
Die aktuelle Anbindung verwendet die regulären regionalen AWS-Endpunkte.

Azure benötigt Tenant-ID, Client-ID, Client-Secret, Subscription-ID und eine
geeignete Rolle wie **Monitoring Reader**. Ressourcengruppe oder Ressourcen-ID
sowie Metriknamen können einschränken. Höchstens 100 Ressourcen und 50 Metriken
je Ressource; große Auswahlen können die Gesamtantwortfrist überschreiten und
sollten auf Prüfungen aufgeteilt werden. Anbindung an die öffentliche Azure-Cloud.

## Langzeitdaten und Parallelität

Unter **Einstellungen → Messwertaufbewahrung und Leistung**:

- Einzelmessungen: standardmäßig 30, einstellbar 1–365 Tage.
- Stündliche Langzeitwerte: standardmäßig 730, einstellbar 30–3.650 Tage;
  mindestens so lange wie Einzelmessungen.
- Gleichzeitige Dienstprüfungen: 1–64, Ressourcen- und zusätzliche Prüfungen: 1–32.

Die zentrale Parallelität gilt nach Neustart. Kürzere Aufbewahrung löscht ältere
Daten bei der nächsten Bereinigung. Zeiträume ab sieben Tagen verwenden
gewichtete Stundenaggregate, einschließlich Minima und Maxima; die laufende Stunde
kommt aus Rohdaten. Der Beginn wird auf die Stundengrenze abgerundet. Dadurch
ist der gewichtete Durchschnitt kein ungewichteter Durchschnitt von Durchschnitten.
Die Oberfläche bietet bis zu zwei Jahre, auch wenn längere Trends gespeichert sind.

## Verteilte Messsammler

1. Unter **Einstellungen → Verteilte Messsammler** einen Messsammler anlegen.
2. Seine ID und den nur einmal angezeigten Zugangsschlüssel übernehmen.
3. Das vollständige Paket auf den entfernten Linux-Server kopieren und dort
   `sudo sh install-collector.sh` ausführen.
4. HTTPS-Adresse der Zentrale, ID, Zugangsschlüssel und gegebenenfalls den zuvor
   unabhängig geprüften SHA-256-Fingerabdruck des Zertifikats eingeben.
5. Unter **Geräte → Einrichten → Messsammler** Geräte zuordnen und speichern.

Der zusätzliche Installer benötigt Linux mit systemd, Python ab 3.9 und
`sha256sum`. Er installiert Programmdateien unter `/opt/netzmonitor-collector`,
private Konfiguration und Puffer unter `/var/lib/netzmonitor-collector` und
verwendet das Dienstkonto `netzmonitor-collector`. Benötigte Programme wie `ping`,
OpenSSH, Net-SNMP, `psql`, MariaDB/MySQL-Client und gegebenenfalls ODBC werden
passend zu den tatsächlich zugewiesenen Prüfungen separat installiert.

```sh
sudo systemctl status netzmonitor-collector
sudo journalctl -u netzmonitor-collector
```

Der Messsammler baut die Verbindung zur Zentrale auf; auf dem Messsammler wird
kein Webport geöffnet. Die Zentrale muss über HTTPS erreichbar sein. Der
Zugangsschlüssel berechtigt zum Abruf der Konfiguration inklusive der benötigten
Zielzugänge für die zugewiesenen Geräte. Datenverzeichnis und Sicherungen daher
wie Zugangsdaten behandeln. Schlüssel können in der Oberfläche erneuert werden;
der neue Schlüssel muss dann auch beim Messsammler hinterlegt werden.

Die Konfiguration wird alle 30 Sekunden abgeglichen. Ohne Verbindung bleibt die
zuletzt erhaltene Konfiguration bis zu 24 Stunden gültig. Ergebnisse werden in
SQLite gepuffert und mit ihrer ursprünglichen Messzeit übertragen. Standardmäßig
passen 100.000 Messungen in den Puffer; beim Erreichen der Grenze starten keine
weiteren Prüfungen. Acht lokale Worker sind voreingestellt. `workers` und
`max_buffer_records` können in `collector.json` geändert werden; Dienst neu starten.
Die Uhren müssen synchron sein (höchstens 60 Sekunden Abweichung).

Bestätigungen und Messungen werden zentral gemeinsam gespeichert. Ein nach einem
Verbindungsabbruch erneut gesendetes Ergebnis wird nicht doppelt übernommen.
Ergebnisse alter Gerätekonfigurationen werden verworfen. Bereits durch eine neuere
Messung überholte Ergebnisse ersetzen keinen aktuellen Zustand. Ergebnisse, die
älter als 30 Tage sind, werden aus dem Puffer entfernt und im Dienstprotokoll
vermerkt. Stark verspätete Messungen erzeugen keine nachträglichen Benachrichtigungen.

Ein pausierter Messsammler darf keine Daten mehr abrufen oder übertragen. War er
bereits offline, erfährt er davon erst bei der nächsten erfolgreichen Kommunikation
oder nach Ablauf seiner Konfigurationsgültigkeit. Die Zentrale übernimmt seine
Prüfungen nicht automatisch. Für eine Rückverlagerung das Gerät dem zentralen
Server zuordnen. Berechnete Messwerte werden immer zentral ausgewertet.

NetFlow/IPFIX bleibt beim zentralen Empfänger. Ein Gerät mit aktivem Flow-Empfang
kann deshalb keinem entfernten Messsammler zugeordnet werden; dafür ein separates
zentral überwachtes Gerät verwenden.

## Prüfung dieses Paketstands

Automatisierte Tests prüfen Konfigurationsvalidierung, Protokollantworten anhand
von Fixtures, tatsächliche lokale HTTP-Sitzungen, Messwertberechnung, Migration,
Aufbewahrung, Pufferung, erneute Zustellung und bestehende Anwendungsfunktionen.
Browserprüfungen kontrollieren die neuen Formulare und den Speicherablauf.
Der Abschlusstest dieses Paketstands umfasst 220 Tests: 215 bestanden und fünf
optionale SSH-Transporttests mangels Paramiko-Testbibliothek übersprungen.
Im Browser wurden 15 neue bzw. erweiterte Prüfungsformulare gespeichert und
erneut geöffnet, der Erhalt hinterlegter Zugangsdaten geprüft und alle elf
Oberflächensprachen aufgerufen. Python-3.9-Syntax und Shell-/JavaScript-Syntax
wurden ebenfalls geprüft.

Es wurden keine Verbindungen zu produktiven Windows-/VMware-Systemen, Cloudkonten,
SNMP-Geräten oder SQL-Servern des Nutzers hergestellt. Fixture-Tests belegen nicht
die Kompatibilität jeder Geräte-, Treiber- oder Serverversion. Für die Inbetriebnahme
je Zieltyp zunächst **Verbindung prüfen** verwenden und Einheiten, Grenzwerte und
Berechtigungen mit den tatsächlich eingesetzten Systemen abgleichen.

## Technische Referenzen

- [Net-SNMP: snmpbulkwalk](https://www.net-snmp.org/docs/man/snmpbulkwalk.html)
- [Fortinet: IPsec-Tunnelzustand](https://community.fortinet.com/fortigate-3/technical-tip-monitor-ipsec-phase-1-tunnel-status-via-snmp-181367)
- [Microsoft: ODBC Driver auf Linux](https://learn.microsoft.com/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server)
- [AWS: GetMetricData](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_GetMetricData.html)
- [Azure: Metrics API](https://learn.microsoft.com/rest/api/monitor/metrics/list)
