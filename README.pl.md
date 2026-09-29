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

## Rozszerzony pakiet

Pakiet dodaje wydajność Windows, dzienniki, szczegóły SMART, liczniki VMware, replikację baz i SQL Server, scenariusze WWW, profile producentów, kontrole chmury/kontenerów, własne metryki, trendy i rozproszone kolektory. Domyślnie: 30 dni danych surowych i 730 dni danych godzinowych; oba okresy można zmienić. Nowe formularze są dostępne w jedenastu językach. Zobacz [konfigurację i zakres (po niemiecku)](docs/AUSBAU.md), aby poznać wymagania i ograniczenia. Nie osiągnięto pełnej zgodności funkcji z Zabbix.

Qisutu Monitoring to samodzielnie instalowany system monitorowania urządzeń,
serwerów, sieci i usług. Korzysta z Pythona, dołączonego serwera WWW Tornado i
SQLite. Obsługa odbywa się w przeglądarce; konfiguracja i pomiary pozostają na
własnym serwerze.

Strona projektu: https://monitoring.qisutu.de

## Status wydania

Wersja 1.0.1 jest pierwszym publicznym wydaniem Qisutu Monitoring. Pełny pakiet
`qisutumonitoring-1.0.1.tar.gz` zawiera aplikację, interfejs WWW, jedenaście
plików językowych i wymaganą bibliotekę Tornado.

## Języki

Qisutu Monitoring oferuje jedenaście języków interfejsu: niemiecki (`de`),
angielski (`en`), francuski (`fr`), włoski (`it`), portugalski brazylijski
(`pt-BR`), portugalski europejski (`pt-PT`), hiszpański (`es`), niderlandzki
(`nl`), polski (`pl`), czeski (`cs`) i turecki (`tr`). Język początkowy wybiera
się podczas instalacji. Każdy agent może następnie wybrać własny język,
zachowywany po ponownym zalogowaniu.

## Wymagania

Instalacja wymaga Linuksa i Pythona 3.9 lub nowszego z `sqlite3` i `ssl`, a także
`sha256sum`, OpenSSL i `ping`. Instalator może doinstalować brakujące pakiety
systemowe przez menedżer pakietów. Kontrole SSH, SNMP i baz danych wymagają
odpowiednich klientów OpenSSH, Net-SNMP i baz danych. Docker, dodatkowy serwer WWW
i zewnętrzny serwer bazy danych nie są potrzebne.

Istniejące klienty PostgreSQL i MariaDB/MySQL są nadal używane. Brakujące klienty
baz danych są instalowane niezależnie od siebie. W Debianie/Ubuntu wszystkie
polecenia instalacji APT używają `--no-remove`, aby zapobiec usuwaniu
zainstalowanych pakietów, oraz `--no-upgrade`, aby nie aktualizować jawnie
wskazanych pakietów, które są już zainstalowane. Jeśli instalacja opcjonalnego
klienta bazy danych wymaga usunięcia pakietu, ten krok jest pomijany z ostrzeżeniem.
Odpowiednie kontrole baz danych wymagają wtedy ręcznej instalacji zgodnego
pakietu klienta.

Tornado i wszystkie pliki interfejsu są dołączone lokalnie. Jeśli pakiety
systemowe są już zainstalowane, instalacja z `--skip-packages` i dalsza praca są
możliwe bez dostępu do internetu.

## Instalacja

Pobierz `qisutumonitoring-1.0.1.tar.gz` i wykonaj poniższe polecenia w katalogu
pobierania:

    tar xzf qisutumonitoring-1.0.1.tar.gz
    cd qisutumonitoring-1.0.1
    sudo sh install.sh

Instalator umieszcza aplikację w `/opt/netzmonitor`, a dane w
`/var/lib/netzmonitor`. Tworzy konto usługi Linux `netzmonitor` i rejestruje
usługę przez systemd, OpenRC lub SysV, jeśli są dostępne. Przy pierwszej
instalacji pyta o język i wyświetla hasło początkowe konta `admin`.

Otwórz `https://SERVER:8787`, zastąp `SERVER` adresem serwera monitoringu i
zaloguj się jako `admin`. Zmień hasło początkowe w ustawieniach osobistych.
Początkowy certyfikat HTTPS z podpisem własnym można zastąpić własnym
certyfikatem.

Język można również wskazać bezpośrednio:

    sudo sh install.sh --language pl

`--skip-packages` pomija instalowanie pakietów systemowych, które muszą już być
dostępne. `--no-start` zapobiega natychmiastowemu uruchomieniu usługi. Przed
instalacją pliki pakietu są sprawdzane na podstawie `SHA256SUMS`.

## Aktualizacja

Przy przyszłych aktualizacjach rozpakuj nowy pełny pakiet do osobnego katalogu
roboczego i uruchom w nim ponownie `sudo sh install.sh`. Najpierw wykonaj kopię
zapasową. Instalator zastępuje pliki aplikacji, zachowując konta, języki,
urządzenia, konfigurację i pomiary. Nie tworzy automatycznej kopii. Następnie
odśwież interfejs przez Ctrl+F5.

## Struktura katalogów

- `netzmonitor/` – aplikacja Pythona i funkcje monitorowania
- `netzmonitor/static/` – interfejs WWW, obrazy i lokalne pliki JavaScript oraz CSS
- `netzmonitor/languages/` – jedenaście plików językowych interfejsu
- `vendor/` – dołączony serwer WWW Tornado
- `tests/` – testy automatyczne
- `tools/` – narzędzia utrzymania pakietów

## Zarządzanie urządzeniami i wykrywanie sieci

Dodawaj urządzenia pojedynczo lub importuj wyniki wykrywania we własnych zakresach
sieci. Grupy, szablony, filtry wyszukiwania i edycja zbiorcza ułatwiają obsługę
większych zasobów. W konfiguracji urządzenia wybierz, przetestuj i zapisz wymagane
kontrole oraz dane dostępowe. Sam test połączenia nie zapisuje konfiguracji.

## Serwery i interfejsy sieciowe

Systemy Linux są monitorowane przez SSH, a zgodne urządzenia przez SNMP. Pomiary
obejmują CPU, pamięć, systemy plików, procesy i usługi Linuksa, wydajność dysków i
interfejsy sieciowe. Dla portów przełączników i innych interfejsów dostępne są
ruch, wykorzystanie, błędy i wykresy historyczne. Windows i Hyper-V korzystają z
WinRM przez HTTPS; dodatkowe kontrole obsługują VMware, Redfish, Synology i UPS.

## Usługi, bazy danych i drukarki

Qisutu Monitoring sprawdza dostępność przez ping, usługi HTTP/HTTPS i TCP,
odpowiedzi DNS oraz certyfikaty TLS. Kontrole SMTP, IMAP i POP3 testują połączenie
protokołu bez wysyłania ani pobierania wiadomości. MariaDB/MySQL i PostgreSQL są
monitorowane przez zapytania odczytu. Drukarki udostępniają stan, materiały
eksploatacyjne i liczniki przez SNMP. Dostępne pomiary zależą od urządzenia i
skonfigurowanych uprawnień.

## Jakość i ruch sieciowy

Jakość sieci jest oceniana na podstawie utraty pakietów, czasów odpowiedzi i ich
zmienności. Wbudowany odbiornik przetwarza NetFlow v5/v9 i IPFIX oraz pokazuje
ruch według adresów IP i portów. Odpowiednie urządzenie sieciowe musi eksportować
dane przepływów do serwera monitoringu. Po skonfigurowaniu odbiór domyślnie używa
portu UDP 2055.

## Historia i połączenia urządzeń

Wykresy historyczne przedstawiają zmiany pomiarów w czasie. Pomiary i zdarzenia są
zwykle przechowywane przez 30 dni. Zależności między urządzeniami oraz ręcznie
zapisane połączenia kablowe i Wi-Fi można przedstawiać graficznie i nimi
zarządzać.

## Agenci i ustawienia osobiste

W zarządzaniu agentami twórz kolejne konta z loginem, nazwą, hasłem i językiem.
Wszyscy agenci mają takie same uprawnienia. Konta można edytować, wyłączać i
usuwać; nie można wyłączyć ani usunąć własnego konta. Hasła muszą mieć od 12 do
256 znaków.

Koło zębate w lewym dolnym rogu otwiera osobiste ustawienia języka i hasła. Przy
zwiniętej nawigacji awatar otwiera menu użytkownika. Język jest zapisany na koncie
i obowiązuje również w innych przeglądarkach. Wpisy użytkowników i odpowiedzi
urządzeń nie są automatycznie tłumaczone.

## Powiadomienia e-mail i integracja z Qisutu

W powiadomieniach można niezależnie włączyć e-mail i połączenie z systemem
zgłoszeń Qisutu. Dla poczty skonfiguruj serwer SMTP, port, szyfrowanie, nadawcę i
odbiorcę. Login i hasło są potrzebne tylko przy wymaganym uwierzytelnianiu. Test
połączenia nie wysyła wiadomości testowej.

Integracja z Qisutu wymaga osobnego zainstalowania zgodnego dodatku monitoringu w
systemie zgłoszeń. Wprowadź w Qisutu Monitoring pokazany tam adres połączenia i
klucz dostępu. Test nie tworzy zgłoszenia. Dodatek nie należy do tego pakietu.

Powiadomienia można ograniczyć do grup i pojedynczych urządzeń. Przekazują zmiany
stanu i przywrócenie działania; niezmieniona awaria nie jest ponawiana po każdej
kontroli. Oczekujące wiadomości pozostają zapisane i są ponawiane po błędach
połączenia. Wyłączenie kanału lub zmiana jego celu albo zakresu usuwa oczekujące
powiadomienia tego kanału.

## Aktywacja urządzeń

Bezpłatnie można korzystać z maksymalnie dziesięciu urządzeń. Plik przypisany do
instalacji aktywuje 100, 500 lub nieograniczoną liczbę urządzeń. Każdy poziom
obejmuje wszystkie funkcje pomiarowe. Strona aktywacji pokazuje identyfikator
instalacji. Skontaktuj się z producentem przez
[monitoring.qisutu.de](https://monitoring.qisutu.de), podając ten identyfikator, a
następnie prześlij, sprawdź i zastosuj otrzymany plik `.nmlic`. Serwer monitoringu
nie potrzebuje do tego internetu.

Po wygaśnięciu umowy można nadal monitorować najwyżej dziesięć wybranych urządzeń.
Jeśli zapisano ich więcej bez wyboru, kontrole są blokowane do czasu zapisania
wyboru. Istniejące dane podlegają zwykłemu okresowi przechowywania. Kontrole i
porty przełączników nie liczą się osobno; aktywowane urządzenie zajmuje miejsce
także po wstrzymaniu.

## Obsługa i przechowywanie danych

Baza znajduje się w `/var/lib/netzmonitor/monitoring.sqlite3`, a konfiguracja
serwera w `/var/lib/netzmonitor/config.json`. Interfejs WWW domyślnie korzysta z
portu TCP 8787. Zmień adres nasłuchiwania i port w `config.json`, po czym uruchom
usługę ponownie. Aby użyć własnego certyfikatu HTTPS, zastąp `server.crt` i
`server.key` w katalogu danych i zrestartuj usługę. Klucz prywatny powinien być
czytelny tylko dla użytkownika usługi.

Polecenie administracyjne jest instalowane jako `/usr/local/bin/netzmonitor`:

    sudo netzmonitor status
    sudo netzmonitor restart
    sudo netzmonitor stop
    sudo netzmonitor start
    sudo netzmonitor doctor

Dzienniki aplikacji są w `/var/lib/netzmonitor/netzmonitor.log`, a przy systemd
także w dzienniku systemowym. Zapomniane hasło zresetuj przez
`sudo netzmonitor password` dla `admin` lub `sudo netzmonitor password LOGIN` dla
innego konta. Instalator nie zmienia globalnej zapory.

## Kopie zapasowe

Spójną kopię bazy można wykonać podczas działania aplikacji:

    sudo netzmonitor backup /root/netzmonitor-backup.sqlite3

Istniejący plik docelowy nie zostanie nadpisany. Zapisz również `config.json`,
`server.crt` i `server.key`. Przed skopiowaniem całego katalogu danych zatrzymaj
usługę, a następnie uruchom ją ponownie. Kopie zawierają dane dostępowe i wymagają
ochrony.

## Odinstalowanie

    sudo netzmonitor uninstall

Potwierdź usunięcie, wpisując `JA`. Usunięte zostaną aplikacja, dane monitoringu,
konta agentów, aktywacja, certyfikaty, własne dzienniki, usługa i dedykowane konto
Linuksa. Można też uruchomić `sudo sh uninstall.sh` z rozpakowanego pakietu.
Wspólne pakiety systemowe, dziennik systemowy, kopie zewnętrzne i osobno
rozpakowane pakiety pozostają.

## Dokumentacja projektu

- [CHANGELOG.md](CHANGELOG.md) – informacje o opublikowanych wydaniach
- [DEVELOPMENT.md](DEVELOPMENT.md) – rozwój, testy i generowanie sum kontrolnych pakietu
- [docs/LICENSE-FORMAT.md](docs/LICENSE-FORMAT.md) – specyfikacja techniczna plików aktywacji
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) – dołączone oprogramowanie zewnętrzne i informacje licencyjne

## Licencja

Qisutu Monitoring jest udostępniane na GNU Affero General Public License, wersja 3
lub dowolna późniejsza (`AGPL-3.0-or-later`). Pełne warunki znajdują się w
[LICENSE](LICENSE).

Copyright (C) 2026 Franziska Steps.

## Oprogramowanie zewnętrzne

Pliki zewnętrzne zachowują oryginalne informacje o prawach autorskich i
licencjach. Tornado jest dołączone na Apache License 2.0. Pełne informacje i
odnośnik do tekstu licencji są w [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Licencje te dotyczą odpowiednich komponentów zewnętrznych.
