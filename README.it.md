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

## Pacchetto esteso

Questo pacchetto aggiunge prestazioni Windows, log, dettagli SMART, contatori VMware, replica dei database e SQL Server, scenari web, profili produttore, controlli cloud/container, metriche personalizzate, dati a lungo termine e collettori distribuiti. Conservazione predefinita: 30 giorni di dati grezzi e 730 giorni di dati orari; entrambe configurabili. I nuovi moduli sono disponibili nelle undici lingue. Vedi [configurazione e ambito (tedesco)](docs/AUSBAU.md) per requisiti e limiti. Non è raggiunta la completa parità con Zabbix.

Qisutu Monitoring è un sistema autonomo per il monitoraggio di dispositivi,
server, reti e servizi. Utilizza Python, il server web Tornado incluso e SQLite.
Si gestisce da un’interfaccia nel browser; configurazione e misurazioni rimangono
sul proprio server.

Sito del progetto: https://monitoring.qisutu.de

## Stato della versione

La versione 1.0.1 è la prima versione pubblica di Qisutu Monitoring. Il pacchetto
completo `QisutuMonitoring-1.0.1.tar.gz` contiene applicazione, interfaccia web,
tutti gli undici file di lingua e la libreria Tornado necessaria.

## Lingue

Qisutu Monitoring offre undici lingue per l’interfaccia: tedesco (`de`), inglese
(`en`), francese (`fr`), italiano (`it`), portoghese brasiliano (`pt-BR`),
portoghese europeo (`pt-PT`), spagnolo (`es`), olandese (`nl`), polacco (`pl`),
ceco (`cs`) e turco (`tr`). La lingua iniziale si sceglie durante l’installazione.
Ogni agente può poi scegliere la propria lingua, conservata anche dopo un nuovo
accesso.

## Requisiti

Sono richiesti Linux e Python 3.9 o successivo con `sqlite3` e `ssl`, oltre a
`sha256sum`, OpenSSL e `ping`. L’installatore può installare i pacchetti di
sistema mancanti tramite il gestore dei pacchetti. I controlli SSH, SNMP e
database richiedono i rispettivi client OpenSSH, Net-SNMP e database. Non sono
necessari Docker, un altro server web o un server database esterno.

I client PostgreSQL e MariaDB/MySQL già presenti vengono riutilizzati. I client
database mancanti vengono installati indipendentemente l’uno dall’altro. Su
Debian/Ubuntu, tutti i comandi di installazione APT usano `--no-remove` per impedire
la rimozione dei pacchetti installati e `--no-upgrade` per evitare l’aggiornamento
dei pacchetti richiesti esplicitamente che sono già installati. Se l’installazione
di un client database opzionale richiede la rimozione di un pacchetto, il passaggio
viene saltato con un avviso. I relativi controlli database richiedono quindi
l’installazione manuale di un pacchetto client compatibile.

Tornado e tutti i file dell’interfaccia sono inclusi localmente. Con i pacchetti
di sistema già presenti, l’installazione con `--skip-packages` e il successivo
utilizzo sono possibili senza accesso a Internet.

## Installazione

Scaricare il pacchetto con `wget`, estrarlo e avviare l’installazione:

    wget https://ftp.qisutu.de/Monitoring/QisutuMonitoring-1.0.1.tar.gz
    tar xzf QisutuMonitoring-1.0.1.tar.gz
    cd QisutuMonitoring
    sudo sh install.sh

L’installatore colloca l’applicazione in `/opt/netzmonitor` e i dati in
`/var/lib/netzmonitor`. Crea l’account di servizio Linux `netzmonitor` e registra
il servizio con systemd, OpenRC o SysV, se disponibili. Alla prima installazione
chiede la lingua e mostra la password iniziale dell’account `admin`.

Aprire `https://SERVER:8787`, sostituire `SERVER` con l’indirizzo del server di
monitoraggio e accedere come `admin`. Modificare la password iniziale nelle
impostazioni personali. Il certificato HTTPS iniziale autofirmato può essere
sostituito con un proprio certificato.

La lingua può essere indicata anche direttamente:

    sudo sh install.sh --language it

`--skip-packages` salta l’installazione dei pacchetti di sistema, che devono
essere già presenti. `--no-start` impedisce l’avvio immediato del servizio. Prima
dell’installazione i file vengono verificati tramite `SHA256SUMS`.

## Aggiornamento

Per gli aggiornamenti futuri, estrarre il nuovo pacchetto completo in una cartella
di lavoro separata ed eseguire nuovamente `sudo sh install.sh`. Creare prima un
backup. L’installatore sostituisce i file dell’applicazione mantenendo account,
lingue, dispositivi, configurazione e misurazioni. Non crea backup automatici.
Ricaricare poi l’interfaccia con Ctrl+F5.

## Struttura delle cartelle

- `netzmonitor/` – applicazione Python e funzioni di monitoraggio
- `netzmonitor/static/` – interfaccia web, immagini e file JavaScript e CSS locali
- `netzmonitor/languages/` – undici file di lingua dell’interfaccia
- `vendor/` – server web Tornado incluso
- `tests/` – test automatizzati
- `tools/` – strumenti di manutenzione dei pacchetti

## Gestione dei dispositivi e rilevamento della rete

I dispositivi si aggiungono singolarmente o importando i risultati di una
scansione dei propri intervalli di rete. Gruppi, modelli, filtri ed elaborazione
collettiva semplificano la gestione di inventari più ampi. Nella configurazione
del dispositivo si scelgono, provano e salvano controlli e credenziali. La sola
prova della connessione non salva la configurazione.

## Server e interfacce di rete

I sistemi Linux vengono monitorati tramite SSH e i dispositivi compatibili tramite
SNMP. Le misurazioni comprendono CPU, memoria, file system, processi e servizi
Linux, prestazioni dei dischi e interfacce di rete. Per porte degli switch e altre
interfacce sono disponibili traffico, utilizzo, errori e grafici storici. Windows
e Hyper-V utilizzano WinRM su HTTPS; altri controlli supportano VMware, Redfish,
Synology e UPS.

## Servizi, database e stampanti

Qisutu Monitoring verifica disponibilità tramite ping, servizi HTTP/HTTPS e TCP,
risposte DNS e certificati TLS. I controlli SMTP, IMAP e POP3 provano la
connessione al protocollo senza inviare o scaricare messaggi. MariaDB/MySQL e
PostgreSQL vengono monitorati tramite query di lettura. Le stampanti forniscono
stato, consumabili e contatori tramite SNMP. I valori disponibili dipendono dal
dispositivo e dai permessi configurati.

## Qualità e traffico di rete

La qualità della rete viene valutata in base a perdita di pacchetti, tempi di
risposta e loro variazioni. Un ricevitore integrato elabora NetFlow v5/v9 e IPFIX
e mostra il traffico per indirizzo IP e porta. Un dispositivo di rete compatibile
deve esportare i dati di flusso al server di monitoraggio. Una volta configurata,
la ricezione utilizza per impostazione predefinita la porta UDP 2055.

## Storici e connessioni dei dispositivi

I grafici storici mostrano l’andamento delle misurazioni. Misurazioni ed eventi
vengono normalmente conservati per 30 giorni. Le dipendenze tra dispositivi e le
connessioni cablate o Wi-Fi inserite manualmente possono essere visualizzate e
gestite graficamente.

## Agenti e impostazioni personali

Nella gestione degli agenti si creano altri account con nome utente, nome,
password e lingua. Tutti gli agenti hanno gli stessi permessi. Gli account possono
essere modificati, disattivati ed eliminati; non è possibile disattivare o
eliminare il proprio account. Le password devono contenere da 12 a 256 caratteri.

L’ingranaggio in basso a sinistra apre le impostazioni personali per lingua e
password. Nella barra laterale ridotta, l’avatar apre il menu utente. La lingua
viene salvata nell’account ed è valida anche in altri browser. I testi degli
utenti e le risposte dei dispositivi non vengono tradotti automaticamente.

## Notifiche e-mail e collegamento a Qisutu

Nelle notifiche si possono attivare separatamente e-mail e collegamento al sistema
di ticket Qisutu. Per le e-mail si configurano server SMTP, porta, crittografia,
mittente e destinatario. Nome utente e password servono solo se è richiesta
l’autenticazione. La prova della connessione non invia messaggi di test.

Il collegamento a Qisutu richiede l’installazione separata del componente
aggiuntivo di monitoraggio compatibile nel sistema di ticket. Inserire in Qisutu
Monitoring l’indirizzo di connessione e la chiave di accesso visualizzati nel
componente. La prova non crea ticket. Il componente aggiuntivo non è incluso nel
pacchetto.

Le notifiche possono essere limitate a gruppi e singoli dispositivi. Comunicano
cambiamenti di stato e ripristini, senza ripetere un guasto invariato a ogni
controllo. Le notifiche in attesa rimangono salvate e vengono ritentate dopo
errori di connessione. Disattivare un canale o modificarne destinazione o ambito
elimina le notifiche in attesa di quel canale.

## Attivazione dei dispositivi

Si possono utilizzare gratuitamente fino a dieci dispositivi. Un file associato
all’installazione ne attiva 100, 500 o un numero illimitato. Ogni livello
comprende tutte le funzioni di misurazione. La pagina di attivazione mostra
l’identificativo dell’installazione. Contattare il produttore tramite
[monitoring.qisutu.de](https://monitoring.qisutu.de) indicando questo
identificativo, quindi caricare, verificare e applicare il file `.nmlic` ricevuto.
Il server di monitoraggio non necessita di Internet per questa operazione.

Alla scadenza del contratto possono continuare a essere monitorati al massimo
dieci dispositivi selezionati. Se ne sono salvati di più senza una selezione, i
controlli rimangono bloccati finché non viene salvata. I dati esistenti restano
soggetti al normale periodo di conservazione. Controlli e porte degli switch non
contano separatamente; un dispositivo attivato occupa un posto anche se sospeso.

## Funzionamento e archiviazione dei dati

Il database è in `/var/lib/netzmonitor/monitoring.sqlite3` e la configurazione del
server in `/var/lib/netzmonitor/config.json`. L’interfaccia usa per impostazione
predefinita la porta TCP 8787. Modificare indirizzo di ascolto e porta in
`config.json`, poi riavviare il servizio. Per usare un certificato HTTPS proprio,
sostituire `server.crt` e `server.key` nella cartella dei dati e riavviare il
servizio. Solo l’utente del servizio deve poter leggere la chiave privata.

Il comando di amministrazione viene installato come `/usr/local/bin/netzmonitor`:

    sudo netzmonitor status
    sudo netzmonitor restart
    sudo netzmonitor stop
    sudo netzmonitor start
    sudo netzmonitor doctor

I log dell’applicazione si trovano in `/var/lib/netzmonitor/netzmonitor.log` e,
con systemd, anche nel journal. Reimpostare una password dimenticata con
`sudo netzmonitor password` per `admin` oppure
`sudo netzmonitor password NOMEUTENTE` per un altro account. L’installatore non
modifica il firewall globale.

## Backup

È possibile creare un backup coerente del database durante il funzionamento:

    sudo netzmonitor backup /root/netzmonitor-backup.sqlite3

Un file di destinazione esistente non viene sovrascritto. Salvare anche
`config.json`, `server.crt` e `server.key`. Arrestare il servizio prima di copiare
l’intera cartella dei dati, poi riavviarlo. I backup contengono credenziali e
devono essere protetti.

## Disinstallazione

    sudo netzmonitor uninstall

Confermare l’eliminazione digitando `JA`. Vengono rimossi applicazione, dati di
monitoraggio, account agente, attivazione, certificati, log propri, servizio e
account Linux dedicato. In alternativa eseguire `sudo sh uninstall.sh` dal
pacchetto estratto. Restano i pacchetti condivisi del sistema, il journal, i
backup esterni e i pacchetti estratti separatamente.

## Documentazione del progetto

- [CHANGELOG.md](CHANGELOG.md) – note delle versioni pubblicate
- [DEVELOPMENT.md](DEVELOPMENT.md) – sviluppo, test e generazione delle somme di controllo
- [docs/LICENSE-FORMAT.md](docs/LICENSE-FORMAT.md) – specifica tecnica dei file di attivazione
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) – software di terze parti incluso e avvisi di licenza

## Licenza

Qisutu Monitoring è distribuito sotto la GNU Affero General Public License,
versione 3 o successiva (`AGPL-3.0-or-later`). I termini completi sono in
[LICENSE](LICENSE).

Copyright (C) 2026 Franziska Steps.

## Software di terze parti

I file di terze parti mantengono le indicazioni originali di copyright e licenza.
Tornado è incluso con Apache License 2.0. Gli avvisi completi e il collegamento al
testo della licenza sono in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Queste licenze riguardano i rispettivi componenti di terze parti.
