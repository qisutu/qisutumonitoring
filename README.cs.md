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

## Rozšířený balíček

Balíček přidává výkon Windows, protokoly, podrobnosti SMART, čítače VMware, replikaci databází a SQL Server, webové scénáře, profily výrobců, cloudové/kontejnerové kontroly, vlastní metriky, dlouhodobá data a distribuované sběrače. Výchozí nastavení: 30 dní surových dat a 730 dní hodinových hodnot; oba intervaly lze změnit. Nové formuláře jsou dostupné ve všech jedenácti jazycích. Viz [nastavení a rozsah (německy)](docs/AUSBAU.md), kde jsou požadavky a omezení. Úplné shody funkcí se Zabbix nebylo dosaženo.

Qisutu Monitoring je samostatně instalovatelný systém pro monitorování zařízení,
serverů, sítí a služeb. Používá Python, přiložený webový server Tornado a SQLite.
Ovládá se v prohlížeči; konfigurace a naměřené hodnoty zůstávají na vašem vlastním
serveru.

Web projektu: https://monitoring.qisutu.de

## Stav vydání

Verze 1.0.1 je prvním veřejným vydáním Qisutu Monitoring. Kompletní instalační
balíček `qisutumonitoring-1.0.1.tar.gz` obsahuje aplikaci, webové rozhraní, všech
jedenáct jazykových souborů a potřebnou knihovnu Tornado.

## Jazyky

Qisutu Monitoring nabízí jedenáct jazyků rozhraní: němčinu (`de`), angličtinu
(`en`), francouzštinu (`fr`), italštinu (`it`), brazilskou portugalštinu
(`pt-BR`), evropskou portugalštinu (`pt-PT`), španělštinu (`es`), nizozemštinu
(`nl`), polštinu (`pl`), češtinu (`cs`) a turečtinu (`tr`). Výchozí jazyk se
vybírá při instalaci. Každý agent si pak může zvolit osobní jazyk, který zůstává
zachován po opětovném přihlášení.

## Požadavky

Instalace vyžaduje Linux a Python 3.9 nebo novější s `sqlite3` a `ssl`, dále
`sha256sum`, OpenSSL a `ping`. Chybějící systémové balíčky může instalátor doplnit
prostřednictvím správce balíčků. Kontroly SSH, SNMP a databází vyžadují
odpovídající klienty OpenSSH, Net-SNMP a databází. Docker, další webový server ani
externí databázový server nejsou potřeba.

Stávající klienti PostgreSQL a MariaDB/MySQL se používají i nadále. Chybějící
databázoví klienti se instalují nezávisle na sobě. V Debianu/Ubuntu všechny
instalační příkazy APT používají `--no-remove`, aby zabránily odstranění již
nainstalovaných balíčků, a `--no-upgrade`, aby neaktualizovaly výslovně požadované
balíčky, které jsou již nainstalovány. Pokud by instalace volitelného databázového
klienta vyžadovala odstranění balíčku, tento krok se přeskočí s upozorněním.
Příslušné databázové kontroly pak vyžadují ruční instalaci kompatibilního
klientského balíčku.

Tornado i všechny soubory rozhraní jsou přiloženy místně. Pokud jsou systémové
balíčky již nainstalovány, instalace s `--skip-packages` i následný provoz jsou
možné bez internetu.

## Instalace

Stáhněte `qisutumonitoring-1.0.1.tar.gz` a v adresáři pro stahování spusťte
následující příkazy:

    tar xzf qisutumonitoring-1.0.1.tar.gz
    cd qisutumonitoring-1.0.1
    sudo sh install.sh

Instalátor uloží aplikaci do `/opt/netzmonitor` a data do `/var/lib/netzmonitor`.
Vytvoří linuxový účet služby `netzmonitor` a zaregistruje službu přes systemd,
OpenRC nebo SysV, jsou-li dostupné. Při první instalaci se zeptá na jazyk a
zobrazí počáteční heslo účtu `admin`.

Otevřete `https://SERVER:8787`, nahraďte `SERVER` adresou monitorovacího serveru a
přihlaste se jako `admin`. Počáteční heslo změňte v osobním nastavení. Úvodní
certifikát HTTPS s vlastním podpisem lze nahradit vlastním certifikátem.

Jazyk lze zadat také přímo:

    sudo sh install.sh --language cs

`--skip-packages` přeskočí instalaci systémových balíčků, které již musejí být
dostupné. `--no-start` zabrání okamžitému spuštění služby. Před instalací jsou
soubory balíčku ověřeny pomocí `SHA256SUMS`.

## Aktualizace

Při budoucích aktualizacích rozbalte nový kompletní balíček do samostatného
pracovního adresáře a znovu spusťte `sudo sh install.sh`. Nejprve vytvořte zálohu.
Instalátor nahradí soubory aplikace a zachová účty, jazyky, zařízení, konfiguraci
i měření. Automatickou zálohu nevytváří. Poté obnovte rozhraní pomocí Ctrl+F5.

## Struktura adresářů

- `netzmonitor/` – aplikace v Pythonu a monitorovací funkce
- `netzmonitor/static/` – webové rozhraní, obrázky a místní soubory JavaScript a CSS
- `netzmonitor/languages/` – jedenáct jazykových souborů rozhraní
- `vendor/` – přiložený webový server Tornado
- `tests/` – automatizované testy
- `tools/` – nástroje pro správu balíčku

## Správa zařízení a vyhledávání v síti

Zařízení přidávejte jednotlivě nebo importujte výsledky vyhledávání ve vlastních
síťových rozsazích. Skupiny, šablony, vyhledávací filtry a hromadné úpravy
usnadňují správu většího počtu zařízení. V nastavení zařízení vyberte, otestujte a
uložte potřebné kontroly a přístupové údaje. Samotný test spojení konfiguraci
neukládá.

## Servery a síťová rozhraní

Systémy Linux se monitorují přes SSH a vhodná zařízení přes SNMP. Měření zahrnují
CPU, paměť, souborové systémy, procesy a služby Linuxu, výkon disků a síťová
rozhraní. U portů přepínačů a dalších rozhraní jsou dostupné provoz, využití,
chyby a historické grafy. Windows a Hyper-V používají WinRM přes HTTPS; další
kontroly podporují VMware, Redfish, Synology a UPS.

## Služby, databáze a tiskárny

Qisutu Monitoring kontroluje dostupnost pomocí pingu, služby HTTP/HTTPS a TCP,
odpovědi DNS a certifikáty TLS. Kontroly SMTP, IMAP a POP3 ověřují protokolové
spojení bez odesílání či stahování zpráv. MariaDB/MySQL a PostgreSQL se monitorují
pomocí čtecích dotazů. Tiskárny poskytují stav, spotřební materiál a čítače přes
SNMP. Dostupná měření závisejí na zařízení a nastavených oprávněních.

## Kvalita a provoz sítě

Kvalita sítě se vyhodnocuje podle ztrátovosti paketů, doby odezvy a jejího
kolísání. Integrovaný přijímač zpracovává NetFlow v5/v9 a IPFIX a zobrazuje provoz
podle IP adres a portů. Vhodné síťové zařízení musí exportovat data toků na
monitorovací server. Po nastavení příjem standardně používá port UDP 2055.

## Historie a propojení zařízení

Historické grafy zobrazují vývoj naměřených hodnot. Měření a události se běžně
uchovávají 30 dní. Závislosti zařízení a ručně zadaná kabelová nebo Wi-Fi spojení
lze graficky zobrazovat a spravovat.

## Agenti a osobní nastavení

Ve správě agentů vytvářejte další účty s uživatelským jménem, jménem, heslem a
jazykem. Všichni agenti mají stejná oprávnění. Účty lze upravovat, deaktivovat a
mazat; vlastní účet nelze deaktivovat ani smazat. Hesla musejí mít 12 až 256
znaků.

Ozubené kolo vlevo dole otevře osobní nastavení jazyka a hesla. Ve sbalené
navigaci otevře avatar uživatelské menu. Jazyk je uložen u účtu a platí i v jiných
prohlížečích. Uživatelské vstupy a odpovědi monitorovaných zařízení se automaticky
nepřekládají.

## E-mailová oznámení a propojení s Qisutu

V oznámeních lze nezávisle zapnout e-mail a spojení s ticketovým systémem Qisutu.
Pro e-mail nastavte server SMTP, port, šifrování, odesílatele a příjemce.
Uživatelské jméno a heslo jsou potřeba jen při požadovaném ověření. Test spojení
neodesílá zkušební e-mail.

Propojení s Qisutu vyžaduje samostatnou instalaci kompatibilního monitorovacího
doplňku v ticketovém systému. Zadejte do Qisutu Monitoring adresu spojení a
přístupový klíč zobrazené v doplňku. Test nevytváří ticket. Doplněk není součástí
tohoto balíčku.

Oznámení lze omezit na skupiny a jednotlivá zařízení. Hlásí změny stavu a obnovení
provozu; nezměněná porucha se neposílá po každé kontrole znovu. Čekající oznámení
zůstávají uložena a po chybách spojení se odeslání opakuje. Vypnutí kanálu nebo
změna jeho cíle či rozsahu odstraní čekající oznámení daného kanálu.

## Aktivace zařízení

Zdarma lze používat až deset zařízení. Soubor vázaný na instalaci aktivuje 100,
500 nebo neomezený počet zařízení. Všechny úrovně zahrnují všechny měřicí funkce.
Stránka aktivace zobrazuje identifikátor instalace. Kontaktujte výrobce přes
[monitoring.qisutu.de](https://monitoring.qisutu.de) a uveďte tento identifikátor;
poté nahrajte, ověřte a použijte přijatý soubor `.nmlic`. Monitorovací server k
tomu nepotřebuje internet.

Po vypršení smlouvy lze dále monitorovat nejvýše deset vybraných zařízení. Je-li
uloženo více zařízení bez výběru, kontroly zůstanou zablokované až do uložení
výběru. Existující data podléhají běžné době uchování. Kontroly a porty přepínačů
se nepočítají zvlášť; aktivované zařízení zabírá místo i při pozastavení.

## Provoz a ukládání dat

Databáze je v `/var/lib/netzmonitor/monitoring.sqlite3` a konfigurace serveru v
`/var/lib/netzmonitor/config.json`. Webové rozhraní standardně používá port TCP
8787. Adresu a port změňte v `config.json` a službu restartujte. Pro vlastní
certifikát HTTPS nahraďte `server.crt` a `server.key` v datovém adresáři a
restartujte službu. Soukromý klíč smí číst jen uživatel služby.

Příkaz pro správu se instaluje jako `/usr/local/bin/netzmonitor`:

    sudo netzmonitor status
    sudo netzmonitor restart
    sudo netzmonitor stop
    sudo netzmonitor start
    sudo netzmonitor doctor

Protokoly aplikace jsou v `/var/lib/netzmonitor/netzmonitor.log` a při systemd
také v systémovém journalu. Zapomenuté heslo obnovte pomocí
`sudo netzmonitor password` pro `admin` nebo `sudo netzmonitor password UZIVATEL`
pro jiný účet. Instalátor nemění globální firewall.

## Zálohování

Konzistentní zálohu databáze lze vytvořit za provozu:

    sudo netzmonitor backup /root/netzmonitor-backup.sqlite3

Existující cílový soubor se nepřepisuje. Zálohujte také `config.json`,
`server.crt` a `server.key`. Před kopií celého datového adresáře službu zastavte a
poté znovu spusťte. Zálohy obsahují přístupové údaje a musejí být chráněny.

## Odinstalace

    sudo netzmonitor uninstall

Odstranění potvrďte zadáním `JA`. Odstraní se aplikace, monitorovací data, účty
agentů, aktivace, certifikáty, vlastní protokoly, služba a vyhrazený linuxový
účet. Lze také spustit `sudo sh uninstall.sh` z rozbaleného balíčku. Sdílené
systémové balíčky, systémový journal, externí zálohy a samostatně rozbalené
balíčky zůstávají.

## Dokumentace projektu

- [CHANGELOG.md](CHANGELOG.md) – poznámky k veřejným vydáním
- [DEVELOPMENT.md](DEVELOPMENT.md) – vývoj, testy a vytváření kontrolních součtů balíčku
- [docs/LICENSE-FORMAT.md](docs/LICENSE-FORMAT.md) – technická specifikace aktivačních souborů
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) – přiložený software třetích stran a licenční oznámení

## Licence

Qisutu Monitoring je licencován pod GNU Affero General Public License, verze 3
nebo kterékoli novější (`AGPL-3.0-or-later`). Úplné podmínky jsou v
[LICENSE](LICENSE).

Copyright (C) 2026 Franziska Steps.

## Software třetích stran

Soubory třetích stran zachovávají původní autorská a licenční oznámení. Tornado je
přiloženo pod Apache License 2.0. Úplná oznámení a odkaz na text licence jsou v
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Tyto licence platí pro příslušné
komponenty třetích stran.
