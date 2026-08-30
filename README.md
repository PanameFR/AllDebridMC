<p align="center">
  <img src="plugin.video.alldebridmc/icon.png" width="140" alt="AllDebridMC">
</p>

<h1 align="center">AllDebridMC</h1>

<p align="center">
  Ta médiathèque AllDebrid Downloader directement dans Kodi, avec jaquettes, saisons et épisodes TMDB.
</p>

<p align="center">
  <img alt="Version extension" src="https://img.shields.io/badge/AllDebridMC-1.18.0-2ea3f2">
  <img alt="Version depot" src="https://img.shields.io/badge/Repository-1.0.2-2ea3f2">
  <img alt="Licence" src="https://img.shields.io/badge/licence-GPL--3.0-lightgrey">
</p>

---

## 🎬 C'est quoi ?

**AllDebridMC** connecte Kodi à un serveur [AllDebrid Downloader](https://github.com)
auto-hébergé (typiquement un Raspberry Pi sous [OpenMediaVault](https://www.openmediavault.org/)) :
il parcourt exactement la même arborescence que la page Stockage de l'outil
(À trier, Films, Séries, Animations...), avec les mêmes jaquettes, saisons
et épisodes déjà associés via TMDB — rien n'est redeviné côté Kodi, tout
vient du serveur.

La lecture vidéo passe directement par le partage réseau (SMB) du serveur,
jamais par son API — aucun impact sur les téléchargements en cours.

Inclut aussi la fonctionnalité **Listes** : crée des listes personnelles
mêlant ta bibliothèque locale et du contenu [vStream](https://github.com/Kodi-vStream/venom-xbmc-addons)/Pastebin,
chacun redirigé automatiquement vers la bonne source à la lecture — sans
jamais modifier vStream, juste s'appuyer dessus pour cette source précise.

## ✨ Fonctionnalités

- 📂 Navigation complète de la bibliothèque (dossiers, films, séries)
- 🖼️ Affiches et informations TMDB : jaquettes de saison, titre/résumé/image
  par épisode, triés automatiquement SxxExx
- 🎞️ Détails film (résumé, genres, note, durée) à la demande, sans requête
  superflue au serveur
- ▶️ Lecture directe en SMB, indépendante du serveur web
- 📋 Listes personnelles mêlant bibliothèque locale et contenu vStream/Pastebin
- 🔁 Reprise de lecture synchronisée entre tous tes appareils Kodi, avec
  écrans "En cours"/"Historique"
- ⏭️ Intégration [service.upnext](https://github.com/MoojMidge/service.upnext)
  (si installé) pour enchaîner automatiquement les épisodes
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

- Un serveur AllDebrid Downloader accessible sur le même réseau (typiquement
  un Raspberry Pi sous [OpenMediaVault](https://www.openmediavault.org/)),
  avec ses routes `/api/kodi/*` (déjà incluses par défaut) et un partage
  réseau SMB actif
- Un compte [AllDebrid](https://alldebrid.com/) actif, utilisé par le
  serveur pour débrider/télécharger
- [vStream](https://github.com/Kodi-vStream/venom-xbmc-addons) installé et
  configuré si tu veux utiliser la fonctionnalité Listes avec du contenu
  Pastebin

## 🛠️ Support

AllDebridMC est un addon gratuit et libre de modification, développé sur
mon temps bénévole. Les futures mises à jour dépendront des
[issues](../../issues) ouvertes sur ce dépôt et du temps disponible, sans
garantie de délai.

Pour tout problème lié à **AllDebridMC**, ouvre une issue ici. Merci de ne
pas contacter l'équipe de vStream ou AllDebrid à ce sujet, ce projet n'a
aucun lien avec eux et ils n'ont pas à gérer nos bugs.

## 📄 Licence & crédits

Distribué sous licence GPL-3.0. S'appuie sur [vStream](https://github.com/Kodi-vStream/venom-xbmc-addons)
pour la lecture de la source Pastebin, et sur l'API [TMDB](https://www.themoviedb.org/)
pour les métadonnées. Ce produit utilise l'API TMDB mais n'est ni approuvé
ni certifié par TMDB.

Le serveur AllDebrid Downloader tourne typiquement sur un Raspberry Pi sous
[OpenMediaVault](https://www.openmediavault.org/), avec un partage réseau
SMB pour la lecture vidéo.

Projet non officiel, développé indépendamment : il n'est ni développé, ni
approuvé, ni maintenu par l'équipe de vStream.
