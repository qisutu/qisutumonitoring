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

Qisutu Monitoring est un système autonome de supervision des équipements,
serveurs, réseaux et services. Il repose sur Python, le serveur web Tornado fourni
et SQLite. Son interface est accessible depuis un navigateur ; la configuration et
les mesures restent sur votre propre serveur.

Site du projet: https://monitoring.qisutu.de

## Statut de la version

La version 1.0.1 est la première version publique de Qisutu Monitoring. Le paquet
complet `qisutumonitoring-1.0.1.tar.gz` contient l’application, l’interface web,
les onze fichiers de langue et la bibliothèque Tornado nécessaire.

## Langues

Qisutu Monitoring propose onze langues d’interface : allemand (`de`), anglais
(`en`), français (`fr`), italien (`it`), portugais du Brésil (`pt-BR`), portugais
du Portugal (`pt-PT`), espagnol (`es`), néerlandais (`nl`), polonais (`pl`),
tchèque (`cs`) et turc (`tr`). La langue initiale est choisie pendant
l’installation. Chaque agent peut ensuite choisir sa langue personnelle, conservée
après reconnexion.

## Prérequis

L’installation nécessite Linux et Python 3.9 ou ultérieur avec `sqlite3` et `ssl`,
ainsi que `sha256sum`, OpenSSL et `ping`. L’installateur peut installer les
paquets système manquants par le gestionnaire de paquets. Les contrôles SSH, SNMP
et de bases de données nécessitent les clients OpenSSH, Net-SNMP et de bases de
données correspondants. Docker, un serveur web supplémentaire et un serveur de
base de données externe ne sont pas nécessaires.

Tornado et tous les fichiers de l’interface sont fournis localement. Si les
paquets système sont déjà installés, l’installation avec `--skip-packages` puis
l’exploitation sont possibles sans accès Internet.

## Installation

Téléchargez le paquet `qisutumonitoring-1.0.1.tar.gz`, puis exécutez les commandes
suivantes dans le dossier de téléchargement :

    tar xzf qisutumonitoring-1.0.1.tar.gz
    cd qisutumonitoring-1.0.1
    sudo sh install.sh

L’installateur place l’application dans `/opt/netzmonitor` et les données dans
`/var/lib/netzmonitor`. Il crée le compte de service Linux `netzmonitor` et
enregistre le service avec systemd, OpenRC ou SysV lorsqu’ils sont disponibles. À
la première installation, il demande la langue et affiche le mot de passe initial
du compte `admin`.

Ouvrez `https://SERVER:8787`, remplacez `SERVER` par l’adresse du serveur de
supervision et connectez-vous avec `admin`. Changez le mot de passe initial dans
vos paramètres personnels. Le certificat HTTPS initial autosigné peut être
remplacé par votre propre certificat.

La langue peut également être indiquée directement :

    sudo sh install.sh --language fr

`--skip-packages` ignore l’installation des paquets système, qui doivent déjà être
présents. `--no-start` empêche le démarrage immédiat du service. Les fichiers du
paquet sont vérifiés à l’aide de `SHA256SUMS` avant l’installation.

## Mise à jour

Pour les prochaines mises à jour, décompressez le nouveau paquet complet dans un
dossier de travail séparé et relancez `sudo sh install.sh`. Effectuez une
sauvegarde au préalable. L’installateur remplace les fichiers de l’application en
conservant les comptes, langues, équipements, configuration et mesures. Il ne crée
pas de sauvegarde automatique. Rechargez ensuite l’interface avec Ctrl+F5.

## Structure des répertoires

- `netzmonitor/` – application Python et fonctions de supervision
- `netzmonitor/static/` – interface web, images et fichiers JavaScript et CSS locaux
- `netzmonitor/languages/` – onze fichiers de langue de l’interface
- `vendor/` – serveur web Tornado fourni
- `tests/` – tests automatisés
- `tools/` – outils de maintenance des paquets

## Gestion des équipements et découverte réseau

Ajoutez les équipements individuellement ou importez les résultats d’une
découverte sur vos propres plages réseau. Groupes, modèles, filtres de recherche
et modifications en masse facilitent la gestion de grands inventaires. Dans la
configuration d’un équipement, sélectionnez, testez et enregistrez les contrôles
et identifiants nécessaires. Un test de connexion seul n’enregistre pas la
configuration.

## Serveurs et interfaces réseau

Les systèmes Linux sont supervisés par SSH et les équipements compatibles par
SNMP. Les mesures couvrent notamment processeur, mémoire, systèmes de fichiers,
processus et services Linux, performances des disques et interfaces réseau. Les
ports de commutateur et autres interfaces fournissent trafic, utilisation, erreurs
et graphiques historiques. Windows et Hyper-V utilisent WinRM sur HTTPS ; d’autres
contrôles prennent en charge VMware, Redfish, Synology et les onduleurs.

## Services, bases de données et imprimantes

Qisutu Monitoring contrôle la disponibilité par ping, les services HTTP/HTTPS et
TCP, les réponses DNS et les certificats TLS. Les contrôles SMTP, IMAP et POP3
testent la connexion au protocole sans envoyer ni récupérer de messages.
MariaDB/MySQL et PostgreSQL sont supervisés par des requêtes de lecture. Les
imprimantes fournissent état, consommables et compteurs par SNMP. Les mesures
disponibles dépendent de l’équipement et des droits configurés.

## Qualité et trafic réseau

La qualité réseau est évaluée à partir des pertes de paquets, des temps de réponse
et de leurs variations. Un collecteur intégré traite NetFlow v5/v9 et IPFIX et
présente le trafic par adresse IP et port. Un équipement réseau compatible doit
exporter ses données de flux vers le serveur de supervision. Une fois configurée,
la réception utilise par défaut le port UDP 2055.

## Historiques et connexions des équipements

Les graphiques historiques montrent l’évolution des mesures. Mesures et événements
sont normalement conservés pendant 30 jours. Les dépendances entre équipements et
les connexions câblées ou Wi-Fi saisies manuellement peuvent être affichées et
gérées graphiquement.

## Agents et paramètres personnels

Créez des comptes supplémentaires dans la gestion des agents avec identifiant,
nom, mot de passe et langue. Tous les agents disposent des mêmes droits. Les
comptes peuvent être modifiés, désactivés et supprimés ; vous ne pouvez ni
désactiver ni supprimer votre propre compte. Les mots de passe doivent comporter
de 12 à 256 caractères.

La roue dentée en bas à gauche ouvre les paramètres personnels de langue et de mot
de passe. Lorsque la navigation est repliée, l’avatar ouvre le menu utilisateur.
La langue est enregistrée dans le compte et s’applique également aux autres
navigateurs. Les saisies des utilisateurs et les réponses des équipements ne sont
pas traduites automatiquement.

## Notifications par e-mail et connexion à Qisutu

L’e-mail et la connexion au système de tickets Qisutu peuvent être activés
séparément dans les notifications. Pour l’e-mail, configurez le serveur SMTP, le
port, le chiffrement, l’expéditeur et le destinataire. L’identifiant et le mot de
passe ne sont requis qu’en cas d’authentification. Le test de connexion n’envoie
aucun message de test.

La connexion à Qisutu nécessite l’installation séparée du module de supervision
compatible dans le système de tickets. Reportez l’adresse de connexion et la clé
d’accès qui y sont affichées dans Qisutu Monitoring. Le test de connexion ne crée
aucun ticket. Le module n’est pas inclus dans ce paquet.

Les notifications peuvent être limitées à des groupes et équipements individuels.
Elles signalent les changements d’état et rétablissements, sans répéter un
incident inchangé après chaque contrôle. Les envois en attente restent enregistrés
et sont retentés après une erreur de connexion. Désactiver un canal ou modifier sa
destination ou son périmètre supprime ses notifications en attente.

## Activation des équipements

Jusqu’à dix équipements sont utilisables gratuitement. Un fichier lié à
l’installation autorise 100, 500 ou un nombre illimité d’équipements. Toutes les
fonctions de mesure sont disponibles à chaque niveau. La page d’activation affiche
l’identifiant d’installation. Contactez le fabricant via
[monitoring.qisutu.de](https://monitoring.qisutu.de) en indiquant cet identifiant,
puis importez, vérifiez et appliquez le fichier `.nmlic` reçu. Le serveur de
supervision n’a pas besoin d’Internet pour cette opération.

À l’expiration du contrat, seuls dix équipements sélectionnés au maximum peuvent
continuer à être supervisés. Si davantage sont enregistrés sans sélection, les
contrôles sont bloqués jusqu’à l’enregistrement d’une sélection. Les données
existantes restent soumises à la durée de conservation normale. Les contrôles et
ports de commutateur ne comptent pas séparément ; un équipement activé occupe une
place même en pause.

## Exploitation et stockage des données

La base se trouve dans `/var/lib/netzmonitor/monitoring.sqlite3` et la
configuration du serveur dans `/var/lib/netzmonitor/config.json`. L’interface
utilise par défaut le port TCP 8787. Modifiez l’adresse d’écoute et le port dans
`config.json`, puis redémarrez le service. Pour utiliser votre propre certificat
HTTPS, remplacez `server.crt` et `server.key` dans le dossier de données et
redémarrez le service. Seul le compte du service doit pouvoir lire la clé privée.

La commande d’administration est installée sous `/usr/local/bin/netzmonitor` :

    sudo netzmonitor status
    sudo netzmonitor restart
    sudo netzmonitor stop
    sudo netzmonitor start
    sudo netzmonitor doctor

Les journaux de l’application sont dans `/var/lib/netzmonitor/netzmonitor.log` et,
avec systemd, également dans le journal système. Réinitialisez un mot de passe
oublié avec `sudo netzmonitor password` pour `admin` ou
`sudo netzmonitor password IDENTIFIANT` pour un autre compte. L’installateur ne
modifie pas le pare-feu global.

## Sauvegarde

Une sauvegarde cohérente de la base est possible pendant le fonctionnement :

    sudo netzmonitor backup /root/netzmonitor-backup.sqlite3

Un fichier cible existant n’est pas écrasé. Sauvegardez également `config.json`,
`server.crt` et `server.key`. Arrêtez le service avant de copier l’ensemble du
dossier de données, puis redémarrez-le. Les sauvegardes contiennent des
identifiants et doivent être protégées.

## Désinstallation

    sudo netzmonitor uninstall

Confirmez la suppression en saisissant `JA`. L’application, les données de
supervision, comptes agents, activation, certificats, journaux propres, service et
compte Linux dédié sont supprimés. Vous pouvez aussi lancer `sudo sh uninstall.sh`
depuis le paquet décompressé. Les paquets système partagés, le journal système,
les sauvegardes externes et les paquets décompressés séparément restent présents.

## Documentation du projet

- [CHANGELOG.md](CHANGELOG.md) – notes des versions publiées
- [DEVELOPMENT.md](DEVELOPMENT.md) – développement, tests et génération des sommes de contrôle
- [docs/LICENSE-FORMAT.md](docs/LICENSE-FORMAT.md) – spécification technique des fichiers d’activation
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) – logiciels tiers fournis et mentions de licence

## Licence

Qisutu Monitoring est distribué sous la GNU Affero General Public License, version
3 ou toute version ultérieure (`AGPL-3.0-or-later`). Les conditions complètes
figurent dans [LICENSE](LICENSE).

Copyright (C) 2026 Franziska Steps.

## Logiciels tiers

Les fichiers tiers conservent leurs mentions de copyright et de licence d’origine.
Tornado est fourni sous Apache License 2.0. Les mentions complètes et le lien vers
le texte de licence sont dans [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Ces licences concernent les composants tiers correspondants.
