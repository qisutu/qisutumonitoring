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

## Uitgebreid pakket

Dit pakket voegt Windows-prestaties, logboeken, SMART-details, VMware-tellers, databasereplicatie en SQL Server, webscenario’s, fabrikantprofielen, cloud/containercontroles, eigen meetwaarden, langetermijngegevens en gedistribueerde collectors toe. Standaard: 30 dagen ruwe gegevens en 730 dagen uurwaarden; beide instelbaar. De nieuwe formulieren zijn beschikbaar in alle elf talen. Zie [inrichting en reikwijdte (Duits)](docs/AUSBAU.md) voor vereisten en resterende beperkingen. Volledige gelijkwaardigheid met Zabbix is niet bereikt.

Qisutu Monitoring is een zelfstandig te installeren systeem voor het bewaken van
apparaten, servers, netwerken en diensten. Het gebruikt Python, de meegeleverde
Tornado-webserver en SQLite. De bediening verloopt via een browser; configuratie
en meetgegevens blijven op uw eigen server.

Projectwebsite: https://monitoring.qisutu.de

## Releasestatus

Versie 1.0.1 is de eerste openbare release van Qisutu Monitoring. Het volledige
installatiepakket `qisutumonitoring-1.0.1.tar.gz` bevat de toepassing,
webinterface, alle elf taalbestanden en de benodigde Tornado-bibliotheek.

## Talen

Qisutu Monitoring biedt elf interfacetalen: Duits (`de`), Engels (`en`), Frans
(`fr`), Italiaans (`it`), Braziliaans Portugees (`pt-BR`), Europees Portugees
(`pt-PT`), Spaans (`es`), Nederlands (`nl`), Pools (`pl`), Tsjechisch (`cs`) en
Turks (`tr`). De begintaal wordt tijdens de installatie gekozen. Iedere agent kan
daarna een persoonlijke taal kiezen; deze blijft na opnieuw aanmelden behouden.

## Vereisten

Installatie vereist Linux en Python 3.9 of hoger met `sqlite3` en `ssl`, plus
`sha256sum`, OpenSSL en `ping`. Het installatieprogramma kan ontbrekende
systeempakketten via de pakketbeheerder installeren. SSH-, SNMP- en
databasecontroles vereisen de bijbehorende OpenSSH-, Net-SNMP- en databaseclients.
Docker, een aanvullende webserver en een externe databaseserver zijn niet nodig.

Bestaande PostgreSQL- en MariaDB/MySQL-clients worden hergebruikt. Ontbrekende
databaseclients worden onafhankelijk van elkaar geïnstalleerd. Op Debian/Ubuntu
gebruiken alle APT-installatieopdrachten `--no-remove` om het verwijderen van
geïnstalleerde pakketten te voorkomen en `--no-upgrade` om expliciet aangevraagde
pakketten die al geïnstalleerd zijn niet te upgraden. Als de installatie van een
optionele databaseclient het verwijderen van een pakket vereist, wordt deze stap
met een waarschuwing overgeslagen. Voor de bijbehorende databasecontroles moet dan
handmatig een compatibel clientpakket worden geïnstalleerd.

Tornado en alle interfacebestanden worden lokaal meegeleverd. Wanneer de
systeempakketten al aanwezig zijn, zijn installatie met `--skip-packages` en
verder gebruik zonder internettoegang mogelijk.

## Installatie

Download `qisutumonitoring-1.0.1.tar.gz` en voer de volgende opdrachten uit in de
downloadmap:

    tar xzf qisutumonitoring-1.0.1.tar.gz
    cd qisutumonitoring-1.0.1
    sudo sh install.sh

Het installatieprogramma plaatst de toepassing in `/opt/netzmonitor` en de
gegevens in `/var/lib/netzmonitor`. Het maakt het Linux-dienstaccount
`netzmonitor` aan en registreert de achtergronddienst via systemd, OpenRC of SysV
indien beschikbaar. Bij de eerste installatie vraagt het om de taal en toont het
startwachtwoord voor `admin`.

Open `https://SERVER:8787`, vervang `SERVER` door het adres van de
monitoringserver en meld u aan als `admin`. Wijzig het startwachtwoord in uw
persoonlijke instellingen. Het aanvankelijke zelfondertekende HTTPS-certificaat
kan door een eigen certificaat worden vervangen.

U kunt de taal ook direct opgeven:

    sudo sh install.sh --language nl

`--skip-packages` slaat de installatie van systeempakketten over; deze moeten al
aanwezig zijn. `--no-start` voorkomt dat de dienst meteen start. De
pakketbestanden worden vóór installatie gecontroleerd aan de hand van
`SHA256SUMS`.

## Bijwerken

Pak voor toekomstige updates het nieuwe volledige releasepakket uit in een aparte
werkmap en voer daar opnieuw `sudo sh install.sh` uit. Maak vooraf een back-up.
Het installatieprogramma vervangt programmabestanden en behoudt accounts, talen,
apparaten, configuratie en meetwaarden. Het maakt geen automatische back-up.
Vernieuw daarna de webinterface met Ctrl+F5.

## Mappenstructuur

- `netzmonitor/` – Python-toepassing en bewakingsfuncties
- `netzmonitor/static/` – webinterface, afbeeldingen en lokale JavaScript- en CSS-bestanden
- `netzmonitor/languages/` – elf taalbestanden voor de interface
- `vendor/` – meegeleverde Tornado-webserver
- `tests/` – geautomatiseerde tests
- `tools/` – hulpmiddelen voor pakketonderhoud

## Apparaatbeheer en netwerkdetectie

Voeg apparaten afzonderlijk toe of neem resultaten uit netwerkdetectie binnen uw
eigen netwerkbereiken over. Groepen, sjablonen, zoekfilters en bulkbewerkingen
vereenvoudigen grotere inventarissen. Selecteer, test en bewaar de controles en
toegangsgegevens in de apparaatconfiguratie. Alleen de verbinding testen slaat nog
geen configuratie op.

## Servers en netwerkinterfaces

Linux-systemen worden via SSH bewaakt en geschikte apparaten via SNMP. Meetwaarden
omvatten CPU, geheugen, bestandssystemen, Linux-processen en diensten,
schijfprestaties en netwerkinterfaces. Switchpoorten en andere interfaces bieden
verkeer, belasting, fouten en historische grafieken. Windows en Hyper-V gebruiken
WinRM via HTTPS; aanvullende controles ondersteunen VMware, Redfish, Synology en
UPS-systemen.

## Diensten, databases en printers

Qisutu Monitoring controleert bereikbaarheid via ping, HTTP/HTTPS- en
TCP-diensten, DNS-antwoorden en TLS-certificaten. SMTP-, IMAP- en POP3-controles
testen de protocolverbinding zonder berichten te verzenden of op te halen.
MariaDB/MySQL en PostgreSQL worden via leesquery’s bewaakt. Printers leveren
status, verbruiksmaterialen en tellers via SNMP. Beschikbare meetwaarden hangen af
van het apparaat en de ingestelde rechten.

## Netwerkkwaliteit en verkeer

De netwerkkwaliteit wordt beoordeeld op pakketverlies, responstijden en hun
schommelingen. Een ingebouwde ontvanger verwerkt NetFlow v5/v9 en IPFIX en toont
verkeer per IP-adres en poort. Een geschikt netwerkapparaat moet flowgegevens naar
de monitoringserver exporteren. Na configuratie gebruikt de ontvangst standaard
UDP-poort 2055.

## Historie en apparaatverbindingen

Historische grafieken tonen de ontwikkeling van meetwaarden. Meetwaarden en
gebeurtenissen worden normaal 30 dagen bewaard. Afhankelijkheden tussen apparaten
en handmatig vastgelegde kabel- of wifi-verbindingen kunnen grafisch worden
weergegeven en beheerd.

## Agenten en persoonlijke instellingen

Maak onder Agenten extra accounts met gebruikersnaam, naam, wachtwoord en taal.
Alle agenten hebben dezelfde rechten. Accounts kunnen worden gewijzigd,
uitgeschakeld en verwijderd; u kunt uw eigen account niet uitschakelen of
verwijderen. Wachtwoorden moeten 12 tot 256 tekens bevatten.

Het tandwiel linksonder opent persoonlijke instellingen voor taal en wachtwoord.
Bij ingeklapte navigatie opent de avatar het gebruikersmenu. De taal wordt bij het
account opgeslagen en geldt ook in andere browsers. Eigen invoer en antwoorden van
bewaakte apparaten worden niet automatisch vertaald.

## E-mailmeldingen en Qisutu-koppeling

E-mail en de verbinding met het Qisutu-ticketsysteem worden afzonderlijk
ingeschakeld bij Meldingen. Configureer voor e-mail de SMTP-server, poort,
versleuteling, afzender en ontvanger. Gebruikersnaam en wachtwoord zijn alleen
nodig wanneer aanmelding vereist is. De verbindingstest verstuurt geen testmail.

De Qisutu-koppeling vereist afzonderlijke installatie van de passende
Monitoring-add-on in het ticketsysteem. Neem het daar getoonde verbindingsadres en
de toegangssleutel over in Qisutu Monitoring. De test maakt geen ticket aan. De
add-on wordt niet met dit pakket meegeleverd.

Meldingen kunnen tot groepen en individuele apparaten worden beperkt. Ze melden
statuswijzigingen en herstel; een onveranderde storing wordt niet na elke controle
opnieuw verstuurd. Wachtende meldingen blijven opgeslagen en worden na
verbindingsfouten opnieuw geprobeerd. Uitschakelen van een kanaal of wijzigen van
doel of apparaatbereik verwijdert de wachtende meldingen van dat kanaal.

## Apparaten activeren

Tot tien apparaten zijn gratis te gebruiken. Een installatiegebonden
activeringsbestand geeft ruimte voor 100, 500 of onbeperkt veel apparaten. Alle
niveaus bevatten alle meetfuncties. De activeringspagina toont de installatiecode.
Neem voor activering contact op met de fabrikant via
[monitoring.qisutu.de](https://monitoring.qisutu.de) en geef deze code door;
upload, controleer en activeer daarna het ontvangen `.nmlic`-bestand. De
monitoringserver heeft hiervoor geen internettoegang nodig.

Na afloop van het contract kunnen maximaal tien geselecteerde apparaten worden
bewaakt. Zijn er meer opgeslagen zonder selectie, dan blijven apparaatcontroles
geblokkeerd totdat een selectie is opgeslagen. Bestaande gegevens vallen onder de
normale bewaartermijn. Controles en switchpoorten tellen niet apart; een
geactiveerd apparaat gebruikt ook tijdens een pauze een plaats.

## Beheer en gegevensopslag

De database staat in `/var/lib/netzmonitor/monitoring.sqlite3` en de
serverconfiguratie in `/var/lib/netzmonitor/config.json`. De webinterface gebruikt
standaard TCP-poort 8787. Wijzig luisteradres en poort in `config.json` en
herstart de dienst. Vervang voor een eigen HTTPS-certificaat `server.crt` en
`server.key` in de gegevensmap en herstart de dienst. Alleen de dienstgebruiker
mag de privésleutel kunnen lezen.

Het beheercommando wordt geïnstalleerd als `/usr/local/bin/netzmonitor`:

    sudo netzmonitor status
    sudo netzmonitor restart
    sudo netzmonitor stop
    sudo netzmonitor start
    sudo netzmonitor doctor

Toepassingslogboeken staan in `/var/lib/netzmonitor/netzmonitor.log` en bij
systemd ook in het journal. Herstel een vergeten wachtwoord met
`sudo netzmonitor password` voor `admin`, of
`sudo netzmonitor password GEBRUIKERSNAAM` voor een ander account. Het
installatieprogramma verandert de globale firewall niet.

## Back-ups

Een consistente databaseback-up is tijdens het gebruik mogelijk:

    sudo netzmonitor backup /root/netzmonitor-backup.sqlite3

Een bestaand doelbestand wordt niet overschreven. Bewaar ook `config.json`,
`server.crt` en `server.key`. Stop de dienst voordat u de volledige gegevensmap
kopieert en start hem daarna opnieuw. Back-ups bevatten toegangsgegevens en moeten
beschermd worden bewaard.

## Verwijderen

    sudo netzmonitor uninstall

Bevestig de verwijdering met `JA`. Toepassing, monitoringgegevens, agentaccounts,
activering, certificaten, eigen logboeken, dienst en het eigen Linux-dienstaccount
worden verwijderd. U kunt ook `sudo sh uninstall.sh` vanuit het uitgepakte pakket
uitvoeren. Gedeelde systeempakketten, het systeemjournal, externe back-ups en
afzonderlijk uitgepakte pakketten blijven behouden.

## Projectdocumentatie

- [CHANGELOG.md](CHANGELOG.md) – opmerkingen bij gepubliceerde releases
- [DEVELOPMENT.md](DEVELOPMENT.md) – ontwikkeling, tests en aanmaken van pakketcontrolesommen
- [docs/LICENSE-FORMAT.md](docs/LICENSE-FORMAT.md) – technische specificatie van activeringsbestanden
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) – meegeleverde software van derden en licentievermeldingen

## Licentie

Qisutu Monitoring valt onder de GNU Affero General Public License, versie 3 of een
latere versie (`AGPL-3.0-or-later`). De volledige voorwaarden staan in
[LICENSE](LICENSE).

Copyright (C) 2026 Franziska Steps.

## Software van derden

Bestanden van derden behouden hun oorspronkelijke copyright- en
licentievermeldingen. Tornado wordt meegeleverd onder Apache License 2.0.
Volledige vermeldingen en de verwijzing naar de licentietekst staan in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Deze licenties gelden voor de
betreffende onderdelen van derden.
