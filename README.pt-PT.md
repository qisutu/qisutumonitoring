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

O Qisutu Monitoring é um sistema autónomo para monitorizar dispositivos,
servidores, redes e serviços. Utiliza Python, o servidor web Tornado incluído e
SQLite. A administração é efetuada no navegador; a configuração e as medições
permanecem no seu próprio servidor.

Site do projeto: https://monitoring.qisutu.de

## Estado da versão

A versão 1.0.1 é a primeira versão pública do Qisutu Monitoring. O pacote completo
`qisutumonitoring-1.0.1.tar.gz` contém a aplicação, a interface web, os onze
ficheiros de idioma e a biblioteca Tornado necessária.

## Idiomas

O Qisutu Monitoring oferece onze idiomas de interface: alemão (`de`), inglês
(`en`), francês (`fr`), italiano (`it`), português do Brasil (`pt-BR`), português
de Portugal (`pt-PT`), espanhol (`es`), neerlandês (`nl`), polaco (`pl`), checo
(`cs`) e turco (`tr`). O idioma inicial é escolhido durante a instalação. Cada
agente pode depois escolher o seu idioma pessoal, mantido após um novo início de
sessão.

## Requisitos

A instalação requer Linux e Python 3.9 ou posterior com `sqlite3` e `ssl`, além de
`sha256sum`, OpenSSL e `ping`. O instalador pode instalar os pacotes de sistema em
falta através do gestor de pacotes. As verificações SSH, SNMP e de bases de dados
exigem os respetivos clientes OpenSSH, Net-SNMP e de bases de dados. Não são
necessários Docker, outro servidor web ou um servidor de base de dados externo.

O Tornado e todos os ficheiros da interface são incluídos localmente. Com os
pacotes de sistema já instalados, a instalação com `--skip-packages` e a
utilização posterior são possíveis sem acesso à Internet.

## Instalação

Transfira `qisutumonitoring-1.0.1.tar.gz` e execute estes comandos na pasta de
transferências:

    tar xzf qisutumonitoring-1.0.1.tar.gz
    cd qisutumonitoring-1.0.1
    sudo sh install.sh

O instalador coloca a aplicação em `/opt/netzmonitor` e os dados em
`/var/lib/netzmonitor`. Cria a conta de serviço Linux `netzmonitor` e regista o
serviço com systemd, OpenRC ou SysV, quando disponíveis. Na primeira instalação,
solicita o idioma e mostra a palavra-passe inicial da conta `admin`.

Abra `https://SERVER:8787`, substitua `SERVER` pelo endereço do servidor de
monitorização e inicie sessão como `admin`. Altere a palavra-passe inicial nas
definições pessoais. O certificado HTTPS inicial autoassinado pode ser substituído
por um certificado próprio.

O idioma também pode ser indicado diretamente:

    sudo sh install.sh --language pt-PT

`--skip-packages` ignora a instalação dos pacotes de sistema, que devem estar
presentes. `--no-start` impede o arranque imediato do serviço. Antes da
instalação, os ficheiros do pacote são verificados com `SHA256SUMS`.

## Atualização

Para atualizações futuras, extraia o novo pacote completo para uma pasta de
trabalho separada e execute novamente `sudo sh install.sh`. Efetue primeiro uma
cópia de segurança. O instalador substitui os ficheiros da aplicação e preserva
contas, idiomas, dispositivos, configuração e medições existentes. Não cria cópias
automáticas. Depois recarregue a interface com Ctrl+F5.

## Estrutura de pastas

- `netzmonitor/` – aplicação Python e funções de monitorização
- `netzmonitor/static/` – interface web, imagens e ficheiros JavaScript e CSS locais
- `netzmonitor/languages/` – onze ficheiros de idioma da interface
- `vendor/` – servidor web Tornado incluído
- `tests/` – testes automatizados
- `tools/` – ferramentas de manutenção de pacotes

## Gestão de dispositivos e descoberta de rede

Adicione dispositivos individualmente ou importe resultados da descoberta em
intervalos da sua própria rede. Grupos, modelos, filtros e edição em massa
facilitam a gestão de inventários maiores. Na configuração do dispositivo,
selecione, teste e guarde as verificações e credenciais necessárias. Testar apenas
a ligação não guarda a configuração.

## Servidores e interfaces de rede

Os sistemas Linux são monitorizados por SSH e os dispositivos compatíveis por
SNMP. As medições incluem CPU, memória, sistemas de ficheiros, processos e
serviços Linux, desempenho dos discos e interfaces de rede. As portas de switches
e outras interfaces fornecem tráfego, utilização, erros e gráficos históricos.
Windows e Hyper-V usam WinRM por HTTPS; verificações adicionais suportam VMware,
Redfish, Synology e UPS.

## Serviços, bases de dados e impressoras

O Qisutu Monitoring verifica disponibilidade por ping, serviços HTTP/HTTPS e TCP,
respostas DNS e certificados TLS. As verificações SMTP, IMAP e POP3 testam a
ligação ao protocolo sem enviar ou descarregar mensagens. MariaDB/MySQL e
PostgreSQL são monitorizados por consultas de leitura. As impressoras fornecem
estado, consumíveis e contadores por SNMP. As medições disponíveis dependem do
dispositivo e das permissões configuradas.

## Qualidade e tráfego de rede

A qualidade da rede é avaliada pela perda de pacotes, pelos tempos de resposta e
pelas suas variações. Um coletor integrado processa NetFlow v5/v9 e IPFIX e mostra
o tráfego por endereço IP e porta. Um dispositivo de rede compatível deve exportar
os dados de fluxo para o servidor de monitorização. Quando configurada, a receção
usa por predefinição a porta UDP 2055.

## Históricos e ligações de dispositivos

Os gráficos históricos mostram a evolução das medições. Medições e eventos são
normalmente conservados durante 30 dias. As dependências entre dispositivos e as
ligações por cabo ou Wi-Fi introduzidas manualmente podem ser apresentadas e
geridas graficamente.

## Agentes e definições pessoais

Na gestão de agentes, crie contas adicionais com nome de utilizador, nome,
palavra-passe e idioma. Todos os agentes têm as mesmas permissões. As contas podem
ser editadas, desativadas e eliminadas; não é possível desativar nem eliminar a
própria conta. As palavras-passe devem ter entre 12 e 256 carateres.

A roda dentada no canto inferior esquerdo abre as definições pessoais de idioma e
palavra-passe. Com a navegação recolhida, o avatar abre o menu do utilizador. O
idioma é guardado na conta e também se aplica noutros navegadores. As entradas dos
utilizadores e as respostas dos dispositivos monitorizados não são traduzidas
automaticamente.

## Notificações por e-mail e ligação ao Qisutu

O e-mail e a ligação ao sistema de tickets Qisutu podem ser ativados separadamente
nas notificações. Para e-mail, configure servidor SMTP, porta, encriptação,
remetente e destinatário. Nome de utilizador e palavra-passe só são necessários
quando é exigida autenticação. O teste de ligação não envia mensagens de teste.

A ligação ao Qisutu exige a instalação separada do módulo de monitorização
compatível no sistema de tickets. Introduza no Qisutu Monitoring o endereço de
ligação e a chave de acesso apresentados no módulo. O teste não cria tickets. O
módulo não faz parte deste pacote.

As notificações podem ser limitadas a grupos e dispositivos individuais. Informam
mudanças de estado e recuperação, sem repetir uma falha inalterada a cada
verificação. As notificações pendentes permanecem guardadas e são novamente
tentadas após erros de ligação. Desativar um canal ou alterar o seu destino ou
âmbito elimina as notificações pendentes desse canal.

## Ativação de dispositivos

Até dez dispositivos podem ser utilizados gratuitamente. Um ficheiro associado à
instalação ativa 100, 500 ou um número ilimitado de dispositivos. Todos os níveis
incluem todas as funções de medição. A página de ativação mostra o identificador
da instalação. Contacte o fabricante através de
[monitoring.qisutu.de](https://monitoring.qisutu.de), indique esse identificador e
depois carregue, verifique e aplique o ficheiro `.nmlic` recebido. O servidor de
monitorização não precisa de Internet para esta operação.

Após o fim do contrato, até dez dispositivos selecionados podem continuar a ser
monitorizados. Se houver mais dispositivos guardados sem uma seleção, as
verificações ficam bloqueadas até a seleção ser guardada. Os dados existentes
seguem o prazo normal de retenção. Verificações e portas de switches não contam
separadamente; um dispositivo ativado ocupa um lugar mesmo quando está em pausa.

## Operação e armazenamento de dados

A base de dados fica em `/var/lib/netzmonitor/monitoring.sqlite3` e a configuração
do servidor em `/var/lib/netzmonitor/config.json`. A interface usa por
predefinição a porta TCP 8787. Altere o endereço de escuta e a porta em
`config.json` e reinicie o serviço. Para usar um certificado HTTPS próprio,
substitua `server.crt` e `server.key` na pasta de dados e reinicie o serviço.
Apenas o utilizador do serviço deve poder ler a chave privada.

O comando de administração é instalado como `/usr/local/bin/netzmonitor`:

    sudo netzmonitor status
    sudo netzmonitor restart
    sudo netzmonitor stop
    sudo netzmonitor start
    sudo netzmonitor doctor

Os registos da aplicação ficam em `/var/lib/netzmonitor/netzmonitor.log` e, com
systemd, também no journal. Redefina uma palavra-passe esquecida com
`sudo netzmonitor password` para `admin` ou `sudo netzmonitor password UTILIZADOR`
para outra conta. O instalador não altera a firewall global.

## Cópias de segurança

É possível criar uma cópia consistente da base de dados durante o funcionamento:

    sudo netzmonitor backup /root/netzmonitor-backup.sqlite3

Um ficheiro de destino existente não é substituído. Guarde também `config.json`,
`server.crt` e `server.key`. Pare o serviço antes de copiar toda a pasta de dados
e volte a iniciá-lo depois. As cópias contêm credenciais e devem ser protegidas.

## Desinstalação

    sudo netzmonitor uninstall

Confirme a eliminação escrevendo `JA`. São removidos aplicação, dados de
monitorização, contas de agentes, ativação, certificados, registos próprios,
serviço e conta Linux dedicada. Também pode executar `sudo sh uninstall.sh` a
partir do pacote extraído. Os pacotes partilhados do sistema, o journal, as cópias
externas e os pacotes extraídos separadamente permanecem.

## Documentação do projeto

- [CHANGELOG.md](CHANGELOG.md) – notas das versões publicadas
- [DEVELOPMENT.md](DEVELOPMENT.md) – desenvolvimento, testes e geração das somas de verificação
- [docs/LICENSE-FORMAT.md](docs/LICENSE-FORMAT.md) – especificação técnica dos ficheiros de ativação
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) – software de terceiros incluído e avisos de licença

## Licença

O Qisutu Monitoring é licenciado sob a GNU Affero General Public License, versão 3
ou qualquer versão posterior (`AGPL-3.0-or-later`). As condições completas
encontram-se em [LICENSE](LICENSE).

Copyright (C) 2026 Franziska Steps.

## Software de terceiros

Os ficheiros de terceiros mantêm os avisos originais de copyright e licença. O
Tornado é incluído sob a Apache License 2.0. Os avisos completos e a ligação para
o texto da licença estão em [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Estas licenças aplicam-se aos respetivos componentes de terceiros.
