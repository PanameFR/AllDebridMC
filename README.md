<p align="center">
  <img src="plugin.video.alldebridmc/icon.png" width="140" alt="AllDebridMC">
</p>

<h1 align="center">AllDebridMC</h1>

<p align="center">
  Ta médiathèque AllDebrid Downloader directement dans Kodi, avec jaquettes, saisons et épisodes TMDB.
</p>

<p align="center">
  <img alt="Version extension" src="https://img.shields.io/badge/AllDebridMC-1.0.5-2ea3f2">
  <img alt="Version depot" src="https://img.shields.io/badge/Repository-1.0.2-2ea3f2">
</p>

---

## 🎬 C'est quoi ?

**AllDebridMC** connecte Kodi à un serveur [AllDebrid
Downloader](https://github.com) auto-hébergé (typiquement sur un Raspberry
Pi) : il parcourt exactement la même arborescence que la page Stockage de
l'outil (A trier, Films, Séries, Animations...), avec les mêmes jaquettes,
saisons et épisodes déjà associés via TMDB — rien n'est redeviné côté Kodi,
tout vient du serveur.

La lecture vidéo passe directement par le partage réseau (SMB) du serveur,
jamais par son API — aucun impact sur les téléchargements en cours.

## ✨ Fonctionnalités

- 📂 Navigation complète de la bibliothèque (dossiers, films, séries)
- 🖼️ Affiches et informations TMDB : jaquettes de saison, titre/résumé/image
  par épisode, triés automatiquement SxxExx
- 🎞️ Détails film (résumé, genres, note, durée) à la demande, sans requête
  superflue au serveur
- ▶️ Lecture directe en SMB, indépendante du serveur web
- 🔁 Mises à jour automatiques une fois le dépôt installé

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
4. Ouvrir les réglages de l'extension et renseigner l'adresse de ton
   serveur, tes identifiants, et le partage SMB (nom, utilisateur, mot de
   passe).

Les mises à jour suivantes se font automatiquement, plus besoin de repasser
par un zip.

## ✅ Prérequis

- Un serveur AllDebrid Downloader accessible sur le
  même réseau, avec ses routes `/api/kodi/*` (déjà incluses par défaut)
- Le partage SMB du serveur accessible avec un compte valide

## 📄 Licence

Projet personnel, non affilié à AllDebrid.
