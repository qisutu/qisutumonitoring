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

## Genişletilmiş paket

Bu paket Windows performansı, günlükler, SMART ayrıntıları, VMware sayaçları, veritabanı çoğaltması ve SQL Server, web senaryoları, üretici profilleri, bulut/konteyner kontrolleri, özel ölçümler, uzun dönem verileri ve dağıtık toplayıcılar ekler. Varsayılan: 30 gün ham veri ve 730 gün saatlik veri; ikisi de ayarlanabilir. Yeni formlar on bir dilde kullanılabilir. Gereksinimler ve sınırlar için [kurulum ve kapsam (Almanca)](docs/AUSBAU.md) belgesine bakın. Zabbix ile tam işlev eşitliğine ulaşılmamıştır.

Qisutu Monitoring; cihazları, sunucuları, ağları ve hizmetleri izlemek için
bağımsız olarak kurulabilen bir sistemdir. Python, pakete dahil Tornado web
sunucusu ve SQLite kullanır. Tarayıcı üzerinden yönetilir; yapılandırma ve
ölçümler kendi sunucunuzda kalır.

Proje sitesi: https://monitoring.qisutu.de

## Sürüm durumu

1.0.1, Qisutu Monitoring’in ilk herkese açık sürümüdür. Tam kurulum paketi
`qisutumonitoring-1.0.1.tar.gz`; uygulamayı, web arayüzünü, on bir dil dosyasını
ve gerekli Tornado kütüphanesini içerir.

## Diller

Qisutu Monitoring on bir arayüz dili sunar: Almanca (`de`), İngilizce (`en`),
Fransızca (`fr`), İtalyanca (`it`), Brezilya Portekizcesi (`pt-BR`), Avrupa
Portekizcesi (`pt-PT`), İspanyolca (`es`), Felemenkçe (`nl`), Lehçe (`pl`), Çekçe
(`cs`) ve Türkçe (`tr`). Başlangıç dili kurulum sırasında seçilir. Her temsilci
daha sonra kendi dilini seçebilir; bu seçim yeniden giriş yapıldığında korunur.

## Gereksinimler

Kurulum için Linux ve `sqlite3` ile `ssl` içeren Python 3.9 veya üzeri; ayrıca
`sha256sum`, OpenSSL ve `ping` gerekir. Kurulum aracı eksik sistem paketlerini
paket yöneticisi üzerinden kurabilir. SSH, SNMP ve veritabanı denetimleri ilgili
OpenSSH, Net-SNMP ve veritabanı istemcilerini gerektirir. Docker, ek bir web
sunucusu veya harici veritabanı sunucusu gerekmez.

Mevcut PostgreSQL ve MariaDB/MySQL istemcileri kullanılmaya devam eder. Eksik
veritabanı istemcileri birbirinden bağımsız olarak kurulur. Debian/Ubuntu’da tüm
APT kurulum komutları, kurulu paketlerin kaldırılmasını önlemek için `--no-remove`
ve açıkça istenen, zaten kurulu paketlerin yükseltilmesini önlemek için
`--no-upgrade` kullanır. İsteğe bağlı bir veritabanı istemcisinin kurulumu bir
paketin kaldırılmasını gerektiriyorsa bu adım bir uyarıyla atlanır. İlgili
veritabanı denetimleri için bu durumda uyumlu bir istemci paketinin elle kurulması
gerekir.

Tornado ve tüm arayüz dosyaları yerel olarak sağlanır. Sistem paketleri önceden
kuruluysa `--skip-packages` ile kurulum ve sonraki kullanım internet erişimi
olmadan mümkündür.

## Kurulum

`qisutumonitoring-1.0.1.tar.gz` paketini indirin ve indirme dizininde şu komutları
çalıştırın:

    tar xzf qisutumonitoring-1.0.1.tar.gz
    cd qisutumonitoring-1.0.1
    sudo sh install.sh

Kurulum aracı uygulamayı `/opt/netzmonitor`, verileri `/var/lib/netzmonitor`
dizinine yerleştirir. Linux hizmet hesabı `netzmonitor` oluşturulur ve varsa
systemd, OpenRC veya SysV üzerinden arka plan hizmeti kaydedilir. İlk kurulumda
dil sorulur ve `admin` hesabının başlangıç parolası gösterilir.

`https://SERVER:8787` adresini açın, `SERVER` yerine izleme sunucusunun adresini
yazın ve `admin` olarak giriş yapın. Başlangıç parolasını kişisel ayarlardan
değiştirin. İlk kendinden imzalı HTTPS sertifikası kendi sertifikanızla
değiştirilebilir.

Dili doğrudan da belirtebilirsiniz:

    sudo sh install.sh --language tr

`--skip-packages` sistem paketlerinin kurulumunu atlar; bunlar önceden kurulu
olmalıdır. `--no-start` hizmetin hemen başlamasını engeller. Paket dosyaları
kurulumdan önce `SHA256SUMS` ile doğrulanır.

## Güncelleme

Gelecekteki güncellemelerde yeni sürümün tam paketini ayrı bir çalışma dizinine
çıkarın ve burada yeniden `sudo sh install.sh` çalıştırın. Önce yedek alın.
Kurulum aracı uygulama dosyalarını değiştirirken mevcut hesapları, dilleri,
cihazları, yapılandırmayı ve ölçümleri korur. Otomatik yedek oluşturmaz. Ardından
arayüzü Ctrl+F5 ile yenileyin.

## Dizin yapısı

- `netzmonitor/` – Python uygulaması ve izleme işlevleri
- `netzmonitor/static/` – web arayüzü, görseller ve yerel JavaScript ile CSS dosyaları
- `netzmonitor/languages/` – on bir arayüz dili dosyası
- `vendor/` – pakete dahil Tornado web sunucusu
- `tests/` – otomatik testler
- `tools/` – paket bakım araçları

## Cihaz yönetimi ve ağ keşfi

Cihazları tek tek ekleyin veya kendi ağ aralıklarınızdaki keşif sonuçlarını içe
aktarın. Gruplar, şablonlar, arama filtreleri ve toplu düzenleme büyük
envanterleri yönetmeyi kolaylaştırır. Cihaz yapılandırmasında gerekli denetimleri
ve erişim bilgilerini seçin, test edin ve kaydedin. Yalnızca bağlantı testi yapmak
yapılandırmayı kaydetmez.

## Sunucular ve ağ arayüzleri

Linux sistemleri SSH, uygun cihazlar ise SNMP üzerinden izlenir. Ölçümler CPU,
bellek, dosya sistemleri, Linux süreçleri ve hizmetleri, disk performansı ve ağ
arayüzlerini kapsar. Ağ anahtarı portları ve diğer arayüzler için trafik,
kullanım, hatalar ve geçmiş grafikleri sunulur. Windows ve Hyper-V, HTTPS
üzerinden WinRM kullanır; ek denetimler VMware, Redfish, Synology ve UPS
destekler.

## Hizmetler, veritabanları ve yazıcılar

Qisutu Monitoring; ping ile erişilebilirliği, HTTP/HTTPS ve TCP hizmetlerini, DNS
yanıtlarını ve TLS sertifikalarını denetler. SMTP, IMAP ve POP3 denetimleri ileti
göndermeden veya indirmeden protokol bağlantısını test eder. MariaDB/MySQL ve
PostgreSQL, okuma sorgularıyla izlenir. Yazıcılar SNMP üzerinden durum, sarf
malzemesi ve sayaç bilgilerini sağlar. Kullanılabilir ölçümler cihaza ve
yapılandırılan izinlere bağlıdır.

## Ağ kalitesi ve trafik

Ağ kalitesi; paket kaybı, yanıt süreleri ve bunların değişimleriyle
değerlendirilir. Dahili alıcı NetFlow v5/v9 ve IPFIX işler, trafiği IP adresi ve
porta göre gösterir. Uygun bir ağ cihazı akış verilerini izleme sunucusuna
göndermelidir. Yapılandırıldığında alım varsayılan olarak UDP 2055 portunu
kullanır.

## Geçmiş ve cihaz bağlantıları

Geçmiş grafikleri ölçümlerin zaman içindeki değişimini gösterir. Ölçümler ve
olaylar normalde 30 gün saklanır. Cihaz bağımlılıkları ve elle kaydedilen kablolu
veya Wi-Fi bağlantıları grafik olarak gösterilip yönetilebilir.

## Temsilciler ve kişisel ayarlar

Temsilci yönetiminde kullanıcı adı, ad, parola ve dil belirterek ek hesaplar
oluşturun. Tüm temsilciler aynı yetkilere sahiptir. Hesaplar düzenlenebilir, devre
dışı bırakılabilir ve silinebilir; kendi hesabınızı devre dışı bırakamaz veya
silemezsiniz. Parolalar 12 ile 256 karakter arasında olmalıdır.

Sol alttaki dişli simgesi kişisel dil ve parola ayarlarını açar. Gezinme çubuğu
daraltıldığında avatar kullanıcı menüsünü açar. Dil hesapta saklanır ve diğer
tarayıcılarda da geçerlidir. Kullanıcı girdileri ve izlenen cihazların yanıtları
otomatik çevrilmez.

## E-posta bildirimleri ve Qisutu bağlantısı

Bildirimlerde e-posta ve Qisutu destek talebi sistemi bağlantısı ayrı ayrı
etkinleştirilebilir. E-posta için SMTP sunucusu, port, şifreleme, gönderen ve
alıcıyı yapılandırın. Kullanıcı adı ve parola yalnızca kimlik doğrulama
gerekiyorsa kullanılır. Bağlantı testi deneme e-postası göndermez.

Qisutu bağlantısı için uyumlu izleme eklentisi destek talebi sistemine ayrıca
kurulmalıdır. Eklentide gösterilen bağlantı adresini ve erişim anahtarını Qisutu
Monitoring’e girin. Test destek talebi oluşturmaz. Eklenti bu pakete dahil
değildir.

Bildirimler gruplarla ve tek tek cihazlarla sınırlandırılabilir. Durum
değişiklikleri ve düzelmeler bildirilir; değişmeyen bir arıza her denetimde
yeniden gönderilmez. Bekleyen bildirimler kayıtlı kalır ve bağlantı hatalarından
sonra yeniden denenir. Bir kanalı kapatmak veya hedefini ya da cihaz kapsamını
değiştirmek o kanalın bekleyen bildirimlerini siler.

## Cihaz etkinleştirme

En fazla on cihaz ücretsiz kullanılabilir. Kuruluma bağlı bir etkinleştirme
dosyası 100, 500 veya sınırsız cihazı etkinleştirir. Her kademe tüm ölçüm
işlevlerini içerir. Etkinleştirme sayfası kurulum kimliğini gösterir. Üreticiyle
[monitoring.qisutu.de](https://monitoring.qisutu.de) üzerinden iletişime geçip bu
kimliği belirtin; ardından gelen `.nmlic` dosyasını yükleyin, doğrulayın ve
uygulayın. İzleme sunucusu bu işlem için internet erişimine ihtiyaç duymaz.

Sözleşme sona erdiğinde en fazla on seçilmiş cihaz izlenmeye devam edebilir. Daha
fazla cihaz kayıtlıysa ve seçim yoksa seçim kaydedilene kadar cihaz denetimleri
engellenir. Mevcut veriler normal saklama süresine tabidir. Denetimler ve ağ
anahtarı portları ayrıca sayılmaz; etkinleştirilmiş bir cihaz duraklatıldığında da
bir yer kullanır.

## İşletim ve veri saklama

Veritabanı `/var/lib/netzmonitor/monitoring.sqlite3`, sunucu yapılandırması
`/var/lib/netzmonitor/config.json` içindedir. Web arayüzü varsayılan olarak TCP
8787 portunu kullanır. Dinleme adresini ve portu `config.json` içinde değiştirip
hizmeti yeniden başlatın. Kendi HTTPS sertifikanız için veri dizinindeki
`server.crt` ve `server.key` dosyalarını değiştirip hizmeti yeniden başlatın. Özel
anahtarı yalnızca hizmet kullanıcısı okuyabilmelidir.

Yönetim komutu `/usr/local/bin/netzmonitor` olarak kurulur:

    sudo netzmonitor status
    sudo netzmonitor restart
    sudo netzmonitor stop
    sudo netzmonitor start
    sudo netzmonitor doctor

Uygulama günlükleri `/var/lib/netzmonitor/netzmonitor.log` içinde, systemd
kullanıldığında ayrıca sistem günlüğündedir. Unutulan parolayı `admin` için
`sudo netzmonitor password`, başka hesaplar için
`sudo netzmonitor password KULLANICIADI` ile sıfırlayın. Kurulum aracı genel
güvenlik duvarını değiştirmez.

## Yedekleme

Uygulama çalışırken tutarlı bir veritabanı yedeği oluşturabilirsiniz:

    sudo netzmonitor backup /root/netzmonitor-backup.sqlite3

Mevcut hedef dosyanın üzerine yazılmaz. `config.json`, `server.crt` ve
`server.key` dosyalarını da yedekleyin. Veri dizininin tamamını kopyalamadan önce
hizmeti durdurup işlemden sonra yeniden başlatın. Yedekler erişim bilgileri içerir
ve korunmalıdır.

## Kaldırma

    sudo netzmonitor uninstall

Silmeyi `JA` yazarak onaylayın. Uygulama, izleme verileri, temsilci hesapları,
etkinleştirme, sertifikalar, uygulama günlükleri, hizmet ve ayrılmış Linux hizmet
hesabı kaldırılır. Çıkarılmış paketten `sudo sh uninstall.sh` de çalıştırılabilir.
Ortak sistem paketleri, sistem günlüğü, harici yedekler ve ayrıca çıkarılmış
paketler kalır.

## Proje belgeleri

- [CHANGELOG.md](CHANGELOG.md) – yayımlanan sürümlerin notları
- [DEVELOPMENT.md](DEVELOPMENT.md) – geliştirme, testler ve paket sağlama toplamlarının oluşturulması
- [docs/LICENSE-FORMAT.md](docs/LICENSE-FORMAT.md) – etkinleştirme dosyalarının teknik tanımı
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) – pakete dahil üçüncü taraf yazılımlar ve lisans bildirimleri

## Lisans

Qisutu Monitoring, GNU Affero General Public License sürüm 3 veya daha sonraki
herhangi bir sürüm (`AGPL-3.0-or-later`) altında lisanslanmıştır. Tam lisans
koşulları [LICENSE](LICENSE) dosyasındadır.

Copyright (C) 2026 Franziska Steps.

## Üçüncü taraf yazılımlar

Üçüncü taraf dosyaları özgün telif ve lisans bildirimlerini korur. Tornado, Apache
License 2.0 altında sağlanır. Tam bildirimler ve lisans metni bağlantısı
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) içindedir. Bu lisanslar ilgili
üçüncü taraf bileşenlerine uygulanır.
