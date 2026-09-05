<p align="center">
  <img src="plugin.video.alldebridmc/icon.png" width="140" alt="AllDebridMC">
</p>

<h1 align="center">AllDebridMC</h1>

<p align="center">
  Ta médiathèque AllDebrid Downloader directement dans Kodi, avec jaquettes, saisons et épisodes TMDB.
</p>

<p align="center">
  <img alt="Version extension" src="https://img.shields.io/badge/AllDebridMC-1.21.1-2ea3f2">
  <img alt="Version depot" src="https://img.shields.io/badge/Repository-1.0.2-2ea3f2">
  <img alt="Licence" src="https://img.shields.io/badge/licence-GPL--3.0-lightgrey">
</p>

---

## 🎬 C'est quoi ?

**AllDebridMC** connecte Kodi à un serveur [AllDebrid Downloader](https://github.com)
auto-hébergé (typiquement un Raspberry Pi ou mini-PC sous [OpenMediaVault](https://www.openmediavault.org/)) :
il parcourt exactement la même arborescence que la page Stockage de l'outil
(À trier, Films, Séries, Animations...), avec les mêmes jaquettes, saisons
et épisodes déjà associés via TMDB — rien n'est redeviné côté Kodi, tout
vient du serveur.

La lecture vidéo passe directement par le partage réseau (SMB) du serveur,
jamais par son API — aucun impact sur les téléchargements en cours.

Inclut aussi un accès direct au **catalogue Pastebin** (le catalogue
communautaire "lesalkodiques" - recherche, parcours par genre/année/
diffuseur, listes organisées, nouveautés/populaires/mieux notés) et à tes
**liens sauvegardés sur AllDebrid** : tout est résolu et lu directement par
l'addon, aucun addon tiers requis. La fonctionnalité **Listes** permet de
créer des listes personnelles mêlant ce contenu Pastebin et ta bibliothèque
locale.

## ✨ Fonctionnalités

- 📂 Navigation complète de la bibliothèque (dossiers, films, séries)
- 🖼️ Affiches et informations TMDB : jaquettes de saison, titre/résumé/image
  par épisode, triés automatiquement SxxExx
- 🎞️ Détails film (résumé, genres, note, durée) à la demande, sans requête
  superflue au serveur
- ▶️ Lecture directe en SMB, indépendante du serveur web
- 🔎 Catalogue Pastebin intégré : recherche, recherche par saga, parcours
  complet, genres, les mieux notés, nouveautés/populaires, listes
  organisées, années, ordre alphabétique, aléatoire, par diffuseur
- 💾 Liens sauvegardés AllDebrid : parcours, lecture et suppression
  directement depuis Kodi
- 📋 Listes personnelles mêlant bibliothèque locale et catalogue Pastebin
- 🔁 Reprise de lecture synchronisée entre tous tes appareils Kodi (films
  ET épisodes, précisément), avec écrans "En cours"/"Historique"
- ⏭️ Enchaînement automatique et fiable des épisodes, entièrement géré par
  l'addon (popup "Épisode suivant" avec compte à rebours configurable),
  aucun addon externe requis
- 💾 Sauvegarde/restauration complète de Kodi (fichiers, addons et leurs
  données, bases de données, cache d'affiches, profils, paramètres) :
  pousse une archive sur le serveur (3 conservées, rotation automatique) et
  restaure la même configuration sur un nouvel appareil (Android, Mac, Windows)
- 🔄 Mises à jour automatiques une fois le dépôt installé

## 📦 Installation

1. **Ajouter la source** : *Système → Gestionnaire de fichiers → Ajouter une
   source → Aucun* → saisir :
   ```
   https://PanameFR.github.io/AllDebridMC/
   ```
2. **Installer le dépôt** : *Extensions → Installer depuis un fichier zip* →
   sélectionner la source ajoutée → `repo/` → `repository.alldebridmc/` →
   le fichier `.zip`.
3. **Installer l'extension** : *Extensions → Installer depuis un dépôt →
   AllDebrid Media Center → Extensions vidéo → AllDebrid Media Center →
   Installer*.

   ⚠️ Toujours par cette étape, jamais en installant son zip directement
   (`repo/plugin.video.alldebridmc/...zip`) : Kodi ne relie l'extension au
   dépôt que si elle est installée ainsi, sinon les mises à jour futures
   sont détectées mais jamais appliquées ni notifiées.
4. Ouvrir les réglages de l'extension et renseigner l'adresse de ton
   serveur, tes identifiants, et le partage SMB (nom, utilisateur, mot de
   passe).
5. Dans *Réglages → Extensions → Mises à jour des extensions*, choisir
   *« Installer automatiquement »* (pas seulement « Notifier »).

Les mises à jour suivantes se font automatiquement (quelques minutes après
chaque nouvelle version publiée), plus besoin de repasser par un zip.

## ✅ Prérequis

- Un serveur AllDebrid Downloader accessible sur le même réseau, avec ses
  routes `/api/kodi/*` (déjà incluses par défaut) et un partage réseau SMB
  actif
- Un compte [AllDebrid](https://alldebrid.com/) actif, utilisé par le
  serveur pour débrider/télécharger
- Aucun autre addon requis : le catalogue Pastebin et l'enchaînement
  d'épisodes sont entièrement gérés par AllDebridMC lui-même

## 🛠️ Support

AllDebridMC est un addon gratuit et libre de modification, développé sur
mon temps bénévole. Les futures mises à jour dépendront des
[issues](../../issues) ouvertes sur ce dépôt et du temps disponible, sans
garantie de délai.

Pour tout problème lié à **AllDebridMC**, ouvre une issue ici. Merci de ne
pas contacter l'équipe de vStream ou AllDebrid à ce sujet, ce projet n'a
aucun lien avec eux et ils n'ont pas à gérer nos bugs.

## 📄 Licence & crédits

Distribué sous licence GPL-3.0.

Le catalogue Pastebin ("lesalkodiques") est une source communautaire
partagée, déjà exploitée par l'addon [vStream](https://github.com/Kodi-vStream/venom-xbmc-addons)
(licence GPL-2.0-only) pour son propre contenu. AllDebridMC **ne modifie ni
ne redistribue vStream** - le code de lecture de ce catalogue (format des
listes partagées, structure de navigation) a été **réimplémenté
intégralement dans son propre code**, en s'inspirant de la logique déjà
publique de vStream pour cette source précise, afin de fonctionner de façon
autonome sans dépendre de son installation.

Utilise aussi l'API [TMDB](https://www.themoviedb.org/) pour les métadonnées.
Ce produit utilise l'API TMDB mais n'est ni approuvé ni certifié par TMDB.

Projet non officiel, développé indépendamment : il n'est ni développé, ni
approuvé, ni maintenu par l'équipe de vStream.
