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

Qisutu Monitoring es un sistema independiente para supervisar dispositivos,
servidores, redes y servicios. Utiliza Python, el servidor web Tornado incluido y
SQLite. Se gestiona mediante una interfaz en el navegador; la configuración y las
mediciones permanecen en su propio servidor.

Sitio del proyecto: https://monitoring.qisutu.de

## Estado de la versión

La versión 1.0.1 es la primera publicación de Qisutu Monitoring. El paquete
completo `qisutumonitoring-1.0.1.tar.gz` contiene la aplicación, la interfaz web,
los once archivos de idioma y la biblioteca Tornado necesaria.

## Idiomas

Qisutu Monitoring ofrece once idiomas de interfaz: alemán (`de`), inglés (`en`),
francés (`fr`), italiano (`it`), portugués de Brasil (`pt-BR`), portugués de
Portugal (`pt-PT`), español (`es`), neerlandés (`nl`), polaco (`pl`), checo (`cs`)
y turco (`tr`). El idioma inicial se elige durante la instalación. Cada agente
puede seleccionar después su idioma personal, que se conserva al volver a iniciar
sesión.

## Requisitos

La instalación requiere Linux y Python 3.9 o posterior con `sqlite3` y `ssl`,
además de `sha256sum`, OpenSSL y `ping`. El instalador puede instalar los paquetes
del sistema que falten mediante el gestor de paquetes. Las comprobaciones SSH,
SNMP y de bases de datos requieren los clientes OpenSSH, Net-SNMP y de bases de
datos correspondientes. No se necesita Docker, otro servidor web ni un servidor de
bases de datos externo.

Tornado y todos los archivos de la interfaz se incluyen localmente. Con los
paquetes del sistema ya instalados, la instalación con `--skip-packages` y el
funcionamiento posterior son posibles sin acceso a Internet.

## Instalación

Descargue `qisutumonitoring-1.0.1.tar.gz` y ejecute estas órdenes en el directorio
de descarga:

    tar xzf qisutumonitoring-1.0.1.tar.gz
    cd qisutumonitoring-1.0.1
    sudo sh install.sh

El instalador coloca la aplicación en `/opt/netzmonitor` y los datos en
`/var/lib/netzmonitor`. Crea la cuenta de servicio Linux `netzmonitor` y registra
el servicio con systemd, OpenRC o SysV cuando están disponibles. En la primera
instalación solicita el idioma y muestra la contraseña inicial de la cuenta
`admin`.

Abra `https://SERVER:8787`, sustituya `SERVER` por la dirección del servidor de
supervisión e inicie sesión como `admin`. Cambie la contraseña inicial en sus
ajustes personales. El certificado HTTPS inicial autofirmado puede sustituirse por
uno propio.

También puede indicar el idioma directamente:

    sudo sh install.sh --language es

`--skip-packages` omite la instalación de paquetes del sistema, que deben estar
presentes. `--no-start` evita el inicio inmediato del servicio. Antes de instalar
se verifican los archivos del paquete mediante `SHA256SUMS`.

## Actualización

Para futuras actualizaciones, extraiga el nuevo paquete completo en un directorio
de trabajo separado y vuelva a ejecutar `sudo sh install.sh`. Cree antes una copia
de seguridad. El instalador sustituye los archivos de la aplicación y conserva las
cuentas, idiomas, dispositivos, configuración y mediciones existentes. No crea
copias automáticas. Recargue después la interfaz con Ctrl+F5.

## Estructura de directorios

- `netzmonitor/` – aplicación Python y funciones de supervisión
- `netzmonitor/static/` – interfaz web, imágenes y archivos JavaScript y CSS locales
- `netzmonitor/languages/` – once archivos de idioma de la interfaz
- `vendor/` – servidor web Tornado incluido
- `tests/` – pruebas automatizadas
- `tools/` – herramientas de mantenimiento de paquetes

## Gestión de dispositivos y descubrimiento de red

Añada dispositivos individualmente o importe los resultados del descubrimiento en
sus propios rangos de red. Grupos, plantillas, filtros y edición masiva facilitan
la gestión de inventarios grandes. En la configuración del dispositivo seleccione,
pruebe y guarde las comprobaciones y credenciales necesarias. Probar la conexión
no guarda por sí solo la configuración.

## Servidores e interfaces de red

Los sistemas Linux se supervisan mediante SSH y los dispositivos compatibles
mediante SNMP. Se miden CPU, memoria, sistemas de archivos, procesos y servicios
Linux, rendimiento de discos e interfaces de red. Los puertos de switch y otras
interfaces ofrecen tráfico, utilización, errores y gráficos históricos. Windows e
Hyper-V se conectan mediante WinRM sobre HTTPS; otras comprobaciones admiten
VMware, Redfish, Synology y SAI.

## Servicios, bases de datos e impresoras

Qisutu Monitoring comprueba disponibilidad por ping, servicios HTTP/HTTPS y TCP,
respuestas DNS y certificados TLS. Las comprobaciones SMTP, IMAP y POP3 prueban la
conexión al protocolo sin enviar ni recuperar mensajes. MariaDB/MySQL y PostgreSQL
se supervisan mediante consultas de lectura. Las impresoras proporcionan estado,
consumibles y contadores mediante SNMP. Las mediciones disponibles dependen del
dispositivo y los permisos configurados.

## Calidad y tráfico de red

La calidad de red se evalúa mediante pérdida de paquetes, tiempos de respuesta y
sus variaciones. Un receptor integrado procesa NetFlow v5/v9 e IPFIX y muestra el
tráfico por dirección IP y puerto. Un dispositivo de red compatible debe exportar
sus datos de flujo al servidor de supervisión. Una vez configurada, la recepción
utiliza por defecto el puerto UDP 2055.

## Historiales y conexiones de dispositivos

Los gráficos históricos muestran la evolución de las mediciones. Las mediciones y
los eventos se conservan normalmente durante 30 días. Las dependencias entre
dispositivos y las conexiones por cable o Wi-Fi registradas manualmente pueden
representarse y gestionarse gráficamente.

## Agentes y ajustes personales

Cree cuentas adicionales en la gestión de agentes con usuario, nombre, contraseña
e idioma. Todos los agentes tienen los mismos permisos. Las cuentas pueden
editarse, desactivarse y eliminarse; no puede desactivar ni eliminar su propia
cuenta. Las contraseñas deben tener entre 12 y 256 caracteres.

El engranaje de la esquina inferior izquierda abre los ajustes personales de
idioma y contraseña. Con la barra lateral contraída, el avatar abre el menú del
usuario. El idioma se guarda en la cuenta y también se aplica en otros
navegadores. Los textos introducidos y las respuestas de los dispositivos no se
traducen automáticamente.

## Avisos por correo e integración con Qisutu

El correo y la conexión al sistema de tickets Qisutu se activan por separado en
los avisos. Para el correo configure servidor SMTP, puerto, cifrado, remitente y
destinatario. Usuario y contraseña solo son necesarios cuando se exige
autenticación. La prueba de conexión no envía mensajes de prueba.

La integración requiere instalar por separado el complemento de supervisión
compatible en el sistema de tickets. Introduzca en Qisutu Monitoring la dirección
de conexión y la clave de acceso mostradas en el complemento. La prueba no crea
tickets. El complemento no se incluye en este paquete.

Los avisos pueden limitarse a grupos y dispositivos individuales. Informan de
cambios de estado y recuperación sin repetir una incidencia idéntica después de
cada comprobación. Los avisos pendientes permanecen guardados y se reintentan tras
errores de conexión. Desactivar un canal o cambiar su destino o ámbito descarta
sus avisos pendientes.

## Activación de dispositivos

Hasta diez dispositivos pueden utilizarse gratis. Un archivo vinculado a la
instalación permite activar 100, 500 o un número ilimitado. Todos los niveles
incluyen todas las funciones de medición. La página de activación muestra el
identificador de instalación. Contacte con el fabricante mediante
[monitoring.qisutu.de](https://monitoring.qisutu.de), facilite este identificador
y después cargue, verifique y aplique el archivo `.nmlic` recibido. El servidor de
supervisión no necesita Internet para esta operación.

Al vencer el contrato pueden seguir supervisándose como máximo diez dispositivos
seleccionados. Si hay más guardados y no existe una selección, las comprobaciones
quedan bloqueadas hasta guardarla. Los datos existentes siguen sujetos al periodo
de retención normal. Las comprobaciones y los puertos de switch no cuentan por
separado; un dispositivo activado ocupa una plaza aunque esté pausado.

## Funcionamiento y almacenamiento de datos

La base está en `/var/lib/netzmonitor/monitoring.sqlite3` y la configuración del
servidor en `/var/lib/netzmonitor/config.json`. La interfaz utiliza por defecto el
puerto TCP 8787. Modifique dirección de escucha y puerto en `config.json` y
reinicie el servicio. Para usar un certificado HTTPS propio, sustituya
`server.crt` y `server.key` en el directorio de datos y reinicie el servicio. Solo
el usuario del servicio debe poder leer la clave privada.

La orden de administración se instala como `/usr/local/bin/netzmonitor`:

    sudo netzmonitor status
    sudo netzmonitor restart
    sudo netzmonitor stop
    sudo netzmonitor start
    sudo netzmonitor doctor

Los registros están en `/var/lib/netzmonitor/netzmonitor.log` y, con systemd,
también en el diario del sistema. Restablezca una contraseña olvidada con
`sudo netzmonitor password` para `admin`, o `sudo netzmonitor password USUARIO`
para otra cuenta. El instalador no modifica el cortafuegos global.

## Copias de seguridad

Puede crear una copia coherente de la base de datos durante el funcionamiento:

    sudo netzmonitor backup /root/netzmonitor-backup.sqlite3

No se sobrescribe un archivo de destino existente. Guarde también `config.json`,
`server.crt` y `server.key`. Detenga el servicio antes de copiar todo el
directorio de datos y vuelva a iniciarlo después. Las copias contienen
credenciales y deben protegerse.

## Desinstalación

    sudo netzmonitor uninstall

Confirme la eliminación escribiendo `JA`. Se eliminan aplicación, datos de
supervisión, cuentas de agentes, activación, certificados, registros propios,
servicio y cuenta Linux dedicada. También puede ejecutar `sudo sh uninstall.sh`
desde el paquete extraído. Se conservan los paquetes compartidos del sistema, el
diario del sistema, las copias externas y los paquetes extraídos por separado.

## Documentación del proyecto

- [CHANGELOG.md](CHANGELOG.md) – notas de las versiones publicadas
- [DEVELOPMENT.md](DEVELOPMENT.md) – desarrollo, pruebas y generación de sumas de comprobación
- [docs/LICENSE-FORMAT.md](docs/LICENSE-FORMAT.md) – especificación técnica de los archivos de activación
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) – software de terceros incluido y avisos de licencia

## Licencia

Qisutu Monitoring se distribuye bajo la GNU Affero General Public License, versión
3 o cualquier versión posterior (`AGPL-3.0-or-later`). Las condiciones completas
están en [LICENSE](LICENSE).

Copyright (C) 2026 Franziska Steps.

## Software de terceros

Los archivos de terceros conservan sus avisos originales de copyright y licencia.
Tornado se incluye bajo Apache License 2.0. Los avisos completos y el enlace al
texto de la licencia están en [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Estas licencias se aplican a los componentes de terceros correspondientes.
