# Entwicklung und Paketpflege

Der Quellcode von Qisutu Monitoring kann unter anderem in Eclipse bearbeitet
werden. Die Anwendung läuft unter Linux mit Python 3.9 oder neuer. Die
Verzeichnisstruktur und die Systemvoraussetzungen sind in [README.md](README.md)
beschrieben.

## Lokaler Entwicklungsstart

Im Projektverzeichnis ein separates Datenverzeichnis verwenden:

    python3 run.py init --data-dir ./dev-data --language de
    python3 run.py serve --data-dir ./dev-data --bind 127.0.0.1 --port 8787 --allow-http

Die Oberfläche ist unter `http://127.0.0.1:8787` erreichbar. Das Startpasswort
wird bei der Initialisierung ausgegeben. Für andere Oberflächensprachen den
passenden Sprachcode an `--language` übergeben. Unverschlüsseltes HTTP ist
ausschließlich auf der Loopback-Adresse `127.0.0.1` zulässig.

## Tests

Die Tests aus dem Projektverzeichnis starten:

    python3 -m unittest discover -s tests -v

Die gezielten Installer-Regressionstests laufen ohne echte Paketinstallation
oder Dienständerung mit isolierten Programm- und Paketmanager-Attrappen:

    python3 -m unittest discover -s tests -p test_installer_packages.py -v

Sie prüfen insbesondere vorhandene MariaDB-/MySQL-Clients bei fehlendem
PostgreSQL-Client, verweigerte Paketentfernungen, fehlende Paketquellen sowie
`--skip-packages` und den Staging-Modus.

Für die JavaScript-Tests wird Node.js benötigt. SSH-Transporttests verwenden
optional Paramiko. Diese Werkzeuge sind keine Betriebsabhängigkeiten der
installierten Anwendung.

## Dokumentation

Die deutsche Dokumentation steht in `README.md`. Die zehn Übersetzungen heißen
`README.cs.md`, `README.en.md`, `README.es.md`, `README.fr.md`, `README.it.md`,
`README.nl.md`, `README.pl.md`, `README.pt-BR.md`, `README.pt-PT.md` und
`README.tr.md`.

`CHANGELOG.md` enthält ausschließlich Hinweise zu öffentlichen Releases.

## Release-Paket

Das Release-Archiv heißt `qisutumonitoring-1.0.1.tar.gz` und enthält als oberste
Verzeichnisebene `qisutumonitoring-1.0.1/`. Direkt darin liegen `install.sh`,
`run.py`, `SHA256SUMS`, `LICENSE`, die README-Dateien und die Projektordner.
Diese Struktur entspricht den Installationsbefehlen in allen Sprachfassungen.
Beim Export aus Eclipse muss diese Verzeichnisstruktur erhalten bleiben.

Nach allen Änderungen die Prüfsummen im vollständigen Paketverzeichnis
erneut erzeugen und prüfen:

    python3 tools/update_checksums.py
    sha256sum -c SHA256SUMS

Erst anschließend das Archiv erstellen. Alle in `SHA256SUMS` aufgeführten
Dateien müssen im Archiv enthalten sein. Lokale Entwicklungsdaten,
Zugangsdaten, Sicherungen, Python-Caches und bereits erzeugte Archive gehören
nicht in das Release-Paket. `SHA256SUMS` dient der Integritätsprüfung und ist
keine digitale Signatur.

## Lizenz

Qisutu Monitoring steht unter `AGPL-3.0-or-later`; die vollständigen
Bedingungen stehen in [LICENSE](LICENSE). Copyright (C) 2026 Franziska Steps.
Mitgelieferte Fremdkomponenten behalten ihre eigenen Lizenzhinweise; siehe
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
