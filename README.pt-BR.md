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

## Pacote ampliado

Este pacote adiciona desempenho do Windows, logs, detalhes SMART, contadores VMware, replicação de bancos e SQL Server, cenários web, perfis de fabricantes, verificações de nuvem/contêineres, métricas personalizadas, dados de longo prazo e coletores distribuídos. Padrão: 30 dias de dados brutos e 730 dias de dados horários; ambos configuráveis. Os novos formulários estão disponíveis nos onze idiomas. Consulte [configuração e escopo (alemão)](docs/AUSBAU.md) para requisitos e limites. A equivalência completa com Zabbix não foi alcançada.

O Qisutu Monitoring é um sistema independente para monitorar dispositivos,
servidores, redes e serviços. Utiliza Python, o servidor web Tornado incluído e
SQLite. A administração é feita pelo navegador; a configuração e as medições
permanecem no seu próprio servidor.

Site do projeto: https://monitoring.qisutu.de

## Status da versão

A versão 1.0.1 é a primeira versão pública do Qisutu Monitoring. O pacote completo
`QisutuMonitoring-1.0.1.tar.gz` contém a aplicação, a interface web, os onze
arquivos de idioma e a biblioteca Tornado necessária.

## Idiomas

O Qisutu Monitoring oferece onze idiomas de interface: alemão (`de`), inglês
(`en`), francês (`fr`), italiano (`it`), português do Brasil (`pt-BR`), português
de Portugal (`pt-PT`), espanhol (`es`), neerlandês (`nl`), polonês (`pl`), tcheco
(`cs`) e turco (`tr`). O idioma inicial é escolhido durante a instalação. Cada
agente pode depois escolher seu idioma pessoal, mantido após um novo login.

## Requisitos

A instalação requer Linux e Python 3.9 ou posterior com `sqlite3` e `ssl`, além de
`sha256sum`, OpenSSL e `ping`. O instalador pode instalar os pacotes de sistema
ausentes pelo gerenciador de pacotes. As verificações SSH, SNMP e de bancos de
dados exigem os respectivos clientes OpenSSH, Net-SNMP e de bancos de dados. Não
são necessários Docker, outro servidor web ou um servidor de banco de dados
externo.

Os clientes PostgreSQL e MariaDB/MySQL existentes são reutilizados. Os clientes
de bancos de dados ausentes são instalados de forma independente. No
Debian/Ubuntu, todos os comandos de instalação do APT usam `--no-remove` para
impedir a remoção de pacotes instalados e `--no-upgrade` para evitar a atualização
dos pacotes solicitados explicitamente que já estejam instalados. Se a instalação
de um cliente de banco de dados opcional exigir a remoção de algum pacote, essa
etapa será ignorada com um aviso. As verificações de bancos de dados
correspondentes exigirão então a instalação manual de um pacote de cliente
compatível.

O Tornado e todos os arquivos da interface são incluídos localmente. Com os
pacotes de sistema já instalados, a instalação com `--skip-packages` e o uso
posterior são possíveis sem acesso à Internet.

## Instalação

Baixe o pacote com `wget`, extraia os arquivos e inicie a instalação:

    wget https://ftp.qisutu.de/Monitoring/QisutuMonitoring-1.0.1.tar.gz
    tar xzf QisutuMonitoring-1.0.1.tar.gz
    cd QisutuMonitoring
    sudo sh install.sh

O instalador coloca a aplicação em `/opt/netzmonitor` e os dados em
`/var/lib/netzmonitor`. Cria a conta de serviço Linux `netzmonitor` e registra o
serviço com systemd, OpenRC ou SysV, quando disponíveis. Na primeira instalação,
solicita o idioma e mostra a senha inicial da conta `admin`.

Abra `https://SERVER:8787`, substitua `SERVER` pelo endereço do servidor de
monitoramento e faça login como `admin`. Altere a senha inicial nas configurações
pessoais. O certificado HTTPS inicial autoassinado pode ser substituído por um
certificado próprio.

O idioma também pode ser informado diretamente:

    sudo sh install.sh --language pt-BR

`--skip-packages` ignora a instalação dos pacotes de sistema, que devem estar
presentes. `--no-start` impede o início imediato do serviço. Antes da instalação,
os arquivos do pacote são verificados com `SHA256SUMS`.

## Atualização

Para atualizações futuras, extraia o novo pacote completo em uma pasta de trabalho
separada e execute novamente `sudo sh install.sh`. Faça um backup antes. O
instalador substitui os arquivos da aplicação e preserva contas, idiomas,
dispositivos, configuração e medições existentes. Não cria backups automáticos.
Depois recarregue a interface com Ctrl+F5.

## Estrutura de pastas

- `netzmonitor/` – aplicação Python e funções de monitoramento
- `netzmonitor/static/` – interface web, imagens e arquivos JavaScript e CSS locais
- `netzmonitor/languages/` – onze arquivos de idioma da interface
- `vendor/` – servidor web Tornado incluído
- `tests/` – testes automatizados
- `tools/` – ferramentas de manutenção de pacotes

## Gerenciamento de dispositivos e descoberta de rede

Adicione dispositivos individualmente ou importe resultados da descoberta em
faixas da sua própria rede. Grupos, modelos, filtros e edição em massa facilitam o
gerenciamento de inventários maiores. Na configuração do dispositivo, selecione,
teste e salve as verificações e credenciais necessárias. Somente testar a conexão
não salva a configuração.

## Servidores e interfaces de rede

Sistemas Linux são monitorados por SSH e dispositivos compatíveis por SNMP. As
medições incluem CPU, memória, sistemas de arquivos, processos e serviços Linux,
desempenho de discos e interfaces de rede. Portas de switches e outras interfaces
fornecem tráfego, utilização, erros e gráficos históricos. Windows e Hyper-V usam
WinRM por HTTPS; verificações adicionais atendem VMware, Redfish, Synology e UPS.

## Serviços, bancos de dados e impressoras

O Qisutu Monitoring verifica disponibilidade por ping, serviços HTTP/HTTPS e TCP,
respostas DNS e certificados TLS. As verificações SMTP, IMAP e POP3 testam a
conexão ao protocolo sem enviar ou baixar mensagens. MariaDB/MySQL e PostgreSQL
são monitorados por consultas de leitura. Impressoras fornecem estado, suprimentos
e contadores por SNMP. As medições disponíveis dependem do dispositivo e das
permissões configuradas.

## Qualidade e tráfego de rede

A qualidade da rede é avaliada pela perda de pacotes, pelos tempos de resposta e
suas variações. Um coletor integrado processa NetFlow v5/v9 e IPFIX e mostra o
tráfego por endereço IP e porta. Um dispositivo de rede compatível deve exportar
os dados de fluxo para o servidor de monitoramento. Quando configurada, a recepção
usa por padrão a porta UDP 2055.

## Históricos e conexões de dispositivos

Os gráficos históricos mostram a evolução das medições. Medições e eventos são
normalmente mantidos por 30 dias. As dependências entre dispositivos e as conexões
por cabo ou Wi-Fi inseridas manualmente podem ser exibidas e gerenciadas
graficamente.

## Agentes e configurações pessoais

No gerenciamento de agentes, crie contas adicionais com nome de usuário, nome,
senha e idioma. Todos os agentes têm as mesmas permissões. As contas podem ser
editadas, desativadas e excluídas; não é possível desativar nem excluir a própria
conta. As senhas devem ter de 12 a 256 caracteres.

A engrenagem no canto inferior esquerdo abre as configurações pessoais de idioma e
senha. Com a navegação recolhida, o avatar abre o menu do usuário. O idioma é
salvo na conta e também se aplica em outros navegadores. Entradas dos usuários e
respostas dos dispositivos monitorados não são traduzidas automaticamente.

## Notificações por e-mail e conexão ao Qisutu

O e-mail e a conexão ao sistema de tickets Qisutu podem ser ativados separadamente
nas notificações. Para e-mail, configure servidor SMTP, porta, criptografia,
remetente e destinatário. Nome de usuário e senha só são necessários quando há
autenticação. O teste de conexão não envia mensagens de teste.

A conexão ao Qisutu exige a instalação separada do módulo de monitoramento
compatível no sistema de tickets. Informe no Qisutu Monitoring o endereço de
conexão e a chave de acesso exibidos no módulo. O teste não cria tickets. O módulo
não faz parte deste pacote.

As notificações podem ser limitadas a grupos e dispositivos individuais. Informam
mudanças de estado e recuperação, sem repetir uma falha inalterada a cada
verificação. Notificações pendentes continuam salvas e são reenviadas após erros
de conexão. Desativar um canal ou alterar seu destino ou escopo descarta as
notificações pendentes desse canal.

## Ativação de dispositivos

Até dez dispositivos podem ser usados gratuitamente. Um arquivo vinculado à
instalação ativa 100, 500 ou um número ilimitado de dispositivos. Todos os níveis
incluem todas as funções de medição. A página de ativação mostra o identificador
da instalação. Entre em contato com o fabricante por
[monitoring.qisutu.de](https://monitoring.qisutu.de), informe esse identificador e
depois carregue, verifique e aplique o arquivo `.nmlic` recebido. O servidor de
monitoramento não precisa de Internet para isso.

Após o vencimento do contrato, até dez dispositivos selecionados podem continuar
sendo monitorados. Se houver mais dispositivos salvos sem uma seleção, as
verificações ficam bloqueadas até salvá-la. Os dados existentes seguem o prazo
normal de retenção. Verificações e portas de switches não contam separadamente; um
dispositivo ativado ocupa uma vaga mesmo quando pausado.

## Operação e armazenamento de dados

O banco de dados fica em `/var/lib/netzmonitor/monitoring.sqlite3` e a
configuração do servidor em `/var/lib/netzmonitor/config.json`. A interface usa
por padrão a porta TCP 8787. Altere endereço de escuta e porta em `config.json` e
reinicie o serviço. Para usar um certificado HTTPS próprio, substitua `server.crt`
e `server.key` na pasta de dados e reinicie o serviço. Somente o usuário do
serviço deve poder ler a chave privada.

O comando de administração é instalado como `/usr/local/bin/netzmonitor`:

    sudo netzmonitor status
    sudo netzmonitor restart
    sudo netzmonitor stop
    sudo netzmonitor start
    sudo netzmonitor doctor

Os registros da aplicação ficam em `/var/lib/netzmonitor/netzmonitor.log` e, com
systemd, também no journal. Redefina uma senha esquecida com
`sudo netzmonitor password` para `admin`, ou `sudo netzmonitor password USUARIO`
para outra conta. O instalador não altera o firewall global.

## Backups

É possível criar um backup consistente do banco de dados durante o funcionamento:

    sudo netzmonitor backup /root/netzmonitor-backup.sqlite3

Um arquivo de destino existente não é sobrescrito. Salve também `config.json`,
`server.crt` e `server.key`. Pare o serviço antes de copiar toda a pasta de dados
e depois reinicie-o. Os backups contêm credenciais e devem ser protegidos.

## Desinstalação

    sudo netzmonitor uninstall

Confirme a exclusão digitando `JA`. São removidos aplicação, dados de
monitoramento, contas de agentes, ativação, certificados, registros próprios,
serviço e conta Linux dedicada. Também é possível executar `sudo sh uninstall.sh`
do pacote extraído. Pacotes compartilhados do sistema, journal, backups externos e
pacotes extraídos separadamente permanecem.

## Documentação do projeto

- [CHANGELOG.md](CHANGELOG.md) – notas das versões publicadas
- [DEVELOPMENT.md](DEVELOPMENT.md) – desenvolvimento, testes e geração das somas de verificação
- [docs/LICENSE-FORMAT.md](docs/LICENSE-FORMAT.md) – especificação técnica dos arquivos de ativação
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) – software de terceiros incluído e avisos de licença

## Licença

O Qisutu Monitoring é licenciado sob a GNU Affero General Public License, versão 3
ou qualquer versão posterior (`AGPL-3.0-or-later`). Os termos completos estão em
[LICENSE](LICENSE).

Copyright (C) 2026 Franziska Steps.

## Software de terceiros

Os arquivos de terceiros mantêm seus avisos originais de copyright e licença. O
Tornado é incluído sob a Apache License 2.0. Os avisos completos e o link para o
texto da licença estão em [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Essas
licenças se aplicam aos respectivos componentes de terceiros.
