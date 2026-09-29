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

## Extended package

This package adds Windows performance, logs, SMART details, VMware counters, database replication and SQL Server, web scenarios, vendor profiles, cloud/container checks, custom metrics, long-term trends and distributed collectors. Defaults are 30 days of raw data and 730 days of hourly trends; both are configurable. New forms are available in all eleven languages. See [setup and scope (German)](docs/AUSBAU.md) for requirements and remaining limits. This is not complete Zabbix feature parity.

Qisutu Monitoring is a standalone system for monitoring devices, servers, networks
and services. It uses Python, the bundled Tornado web server and SQLite. A
browser-based interface provides access to the application; configuration and
measurements remain on your own server.

Project website: https://monitoring.qisutu.de

## Release status

Version 1.0.1 is the first public release of Qisutu Monitoring. The complete
installation package, `QisutuMonitoring-1.0.1.tar.gz`, contains the application,
web interface, all eleven language files and the required Tornado library.

## Languages

Qisutu Monitoring provides eleven interface languages: German (`de`), English
(`en`), French (`fr`), Italian (`it`), Brazilian Portuguese (`pt-BR`), European
Portuguese (`pt-PT`), Spanish (`es`), Dutch (`nl`), Polish (`pl`), Czech (`cs`)
and Turkish (`tr`). The initial language is selected during installation. Each
agent can then choose a personal language, which is retained after signing in
again.

## Requirements

Installation requires Linux and Python 3.9 or later with `sqlite3` and `ssl`,
together with `sha256sum`, OpenSSL and `ping`. The installer can install missing
system packages through the package manager. SSH, SNMP and database checks require
the corresponding OpenSSH, Net-SNMP and database clients. Docker, an additional
web server and an external database server are not required.

Existing PostgreSQL and MariaDB/MySQL clients are reused. Missing database
clients are installed independently. On Debian/Ubuntu, all APT installation
commands use `--no-remove` to prevent removal of installed packages and
`--no-upgrade` to avoid upgrading explicitly requested packages that are already
installed. If an optional database client would require a package removal, its
installation is skipped with a warning. The corresponding database checks then
require a compatible client package to be provided manually.

Tornado and all web interface files are bundled locally. With the system packages
already installed, installation using `--skip-packages` and subsequent operation
are possible without internet access.

## Installation

Download the release package with `wget`, extract it and start the installation:

    wget https://ftp.qisutu.de/Monitoring/QisutuMonitoring-1.0.1.tar.gz
    tar xzf QisutuMonitoring-1.0.1.tar.gz
    cd QisutuMonitoring
    sudo sh install.sh

The installer places the application in `/opt/netzmonitor` and its data in
`/var/lib/netzmonitor`. It creates the Linux service account `netzmonitor` and
registers a background service with systemd, OpenRC or SysV where available. On
first installation it asks for the language and displays the initial password for
the `admin` account.

Open `https://SERVER:8787`, replacing `SERVER` with the monitoring server address,
and sign in as `admin`. Change the initial password in your personal settings. The
initial self-signed HTTPS certificate can be replaced with your own certificate.

You can also specify the language directly:

    sudo sh install.sh --language en

`--skip-packages` skips installation of system packages, which must already be
present. `--no-start` prevents the immediate service start. Package files are
verified against `SHA256SUMS` before installation.

## Updating

For future updates, extract the new complete release into a separate working
directory and run `sudo sh install.sh` there. Make a backup first. The installer
replaces application files while retaining existing accounts, languages, devices,
configuration and measurements. It does not create an automatic backup. Afterwards
reload the web interface with Ctrl+F5.

## Directory structure

- `netzmonitor/` – Python application and monitoring functions
- `netzmonitor/static/` – web interface, images and local JavaScript and CSS files
- `netzmonitor/languages/` – eleven interface language files
- `vendor/` – bundled Tornado web server
- `tests/` – automated tests
- `tools/` – package maintenance tools

## Device management and network discovery

Add devices individually or discover them in your own network ranges. Groups,
templates, search filters and bulk editing simplify management of larger
inventories. Use the device setup to select, test and save the required checks and
credentials. A connection test alone does not save a device configuration.

## Servers and network interfaces

Linux systems are monitored through SSH and suitable devices through SNMP.
Measurements include CPU, memory, file systems, Linux processes and services, disk
performance and network interfaces. Switch ports and other interfaces provide
traffic, utilisation, errors and history charts. Windows and Hyper-V connect
through WinRM over HTTPS; additional checks support VMware, Redfish, Synology and
UPS devices.

## Services, databases and printers

Qisutu Monitoring checks availability using ping, HTTP/HTTPS and TCP services, DNS
responses and TLS certificates. SMTP, IMAP and POP3 checks test protocol
connections without sending email or retrieving messages. MariaDB/MySQL and
PostgreSQL are monitored through read queries. Printers provide status, supplies
and counters through SNMP. Available measurements depend on the device and
configured access permissions.

## Network quality and traffic

Network quality is evaluated using packet loss, response times and their
variation. An integrated collector processes NetFlow v5/v9 and IPFIX, displaying
traffic by IP address and port. A suitable network device must export its flow
data to the monitoring server. When configured, collection uses UDP port 2055 by
default.

## History and device connections

History charts show how measurements develop over time. Measurements and events
are normally retained for 30 days. Device dependencies and manually recorded wired
or Wi-Fi connections can be displayed and managed graphically.

## Agents and personal settings

Create additional accounts under Agents with a username, name, password and
language. All agents have equal permissions. Accounts can be edited, disabled and
deleted; you cannot disable or delete your own account. Passwords must contain 12
to 256 characters.

The gear at the bottom left opens personal settings for language and password. In
the collapsed sidebar the avatar opens the user menu. The language is stored with
the account and also applies in other browsers. User input and responses from
monitored devices are not translated automatically.

## Email notifications and Qisutu integration

Email and the connection to the Qisutu ticket system can be enabled independently
under Notifications. For email, configure the SMTP server, port, encryption,
sender and recipient. A username and password are needed only when authentication
is required. The connection test does not send a test email.

Qisutu integration requires the compatible Monitoring add-on to be installed
separately in the ticket system. Enter the connection URL and access key shown
there into Qisutu Monitoring. The connection test creates no ticket. The add-on is
not included in this package.

Notifications can be limited to groups and individual devices. State changes and
recovery are reported; unchanged incidents are not sent again after every check.
Pending notifications persist and are retried after connection failures. Disabling
a delivery channel or changing its destination or device scope discards its
pending notifications.

## Device activation

Up to ten devices can be used free of charge. An installation-specific activation
file enables 100, 500 or unlimited devices. Every tier includes all measurement
functions. The Activation page shows the installation identifier. To request
activation, contact the manufacturer through
[monitoring.qisutu.de](https://monitoring.qisutu.de) and provide this identifier;
upload, validate and apply the received `.nmlic` file. The monitoring server does
not need internet access for this.

After the contract expires, no more than ten selected devices can continue to be
monitored. If more devices are stored and no selection exists, device checks are
blocked until a selection is saved. Existing data remains subject to normal
retention. Checks and switch ports do not count separately; an activated device
still occupies a place while paused.

## Operation and data storage

The database is stored in `/var/lib/netzmonitor/monitoring.sqlite3` and server
configuration in `/var/lib/netzmonitor/config.json`. The web interface defaults to
TCP port 8787. Change the bind address and port in `config.json`, then restart the
service. Replace `server.crt` and `server.key` in the data directory to use your
own HTTPS certificate and restart the service to apply it. Only the service user
should be able to read the private key.

The management command is installed as `/usr/local/bin/netzmonitor`:

    sudo netzmonitor status
    sudo netzmonitor restart
    sudo netzmonitor stop
    sudo netzmonitor start
    sudo netzmonitor doctor

Application logs are stored in `/var/lib/netzmonitor/netzmonitor.log` and, with
systemd, also in the journal. Reset a forgotten password using
`sudo netzmonitor password` for `admin`, or `sudo netzmonitor password USERNAME`
for another account. The installer does not change the global firewall.

## Backups

Create a consistent database backup while the application is running:

    sudo netzmonitor backup /root/netzmonitor-backup.sqlite3

An existing destination file will not be overwritten. Also back up `config.json`,
`server.crt` and `server.key`. Stop the service before copying the entire data
directory, then restart it. Backups contain credentials and must be stored
securely.

## Uninstallation

    sudo netzmonitor uninstall

Confirm deletion by entering `JA`. This removes the application, monitoring data,
agent accounts, activation, certificates, application logs, service and dedicated
Linux service account. Alternatively run `sudo sh uninstall.sh` from the extracted
package. Shared operating-system packages, the system journal, external backups
and separately extracted packages remain.

## Project documentation

- [CHANGELOG.md](CHANGELOG.md) – notes for published releases
- [DEVELOPMENT.md](DEVELOPMENT.md) – development, tests and generation of package checksums
- [docs/LICENSE-FORMAT.md](docs/LICENSE-FORMAT.md) – technical activation file specification
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) – bundled third-party software and licence notices

## Licence

Qisutu Monitoring is licensed under the GNU Affero General Public License, version
3 or any later version (`AGPL-3.0-or-later`). The full licence terms are in
[LICENSE](LICENSE).

Copyright (C) 2026 Franziska Steps.

## Third-party software

Bundled third-party files retain their original copyright and licence notices.
Tornado is included under the Apache License 2.0. Full notices and a link to the
licence text are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). These
licences apply to the respective third-party components.
