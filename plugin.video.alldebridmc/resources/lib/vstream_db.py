# -*- coding: utf-8 -*-
"""Lecture SEULE de la base SQLite locale de vStream (aucun INSERT/UPDATE/
DELETE, uniquement des SELECT) pour récupérer, pour les FILMS uniquement
(même limite que précédemment - une série n'a que la saison dans la table
`viewing`, jamais l'épisode précis, insuffisant pour une reprise fiable),
la progression que vStream a lui-même déjà enregistrée - que la lecture
ait été lancée depuis notre addon OU directement dans vStream, peu importe :
ce mécanisme fonctionne dans les deux cas, contrairement à un repère
posé-avant-redirection (approche précédente, abandonnée - voir historique
Git) qui ne couvrait que notre propre redirection.

Schéma vérifié en lisant le code source réel de vStream
(resources/lib/db.py, resources/lib/player.py) avant d'écrire ce module,
jamais deviné :
- table `resume` (title, hoster, point, total) : point de reprise d'un
  contenu EN COURS (>180s de lecture, <90% vu), `title` = titre original
  Kodi normalisé (getVideoInfoTag().getOriginalTitle(), espaces retirés) -
  écrite UNIQUEMENT à l'arrêt de la lecture (onPlayBackStopped/Ended),
  jamais pendant - pas de reprise "en direct" possible, seulement "où on
  s'est arrêté la dernière fois".
- table `viewing` (tmdb_id, title_id, title, cat, season, ...) : ce que
  vStream considère "en cours" - `title_id` utilise la MÊME normalisation
  que `resume.title`, donc joignable dessus. `cat='1'` = film (seule
  catégorie retenue ici : pour les séries, `viewing` ne retient que la
  SAISON, jamais l'épisode précis).
- table `watched` (tmdb_id, cat, ...) : films/séries marqués VUS - écrite
  À LA PLACE de resume/viewing quand le seuil de 90% est dépassé (resume
  est alors supprimé côté vStream - pas de nouvelle ligne resume à
  détecter dans ce cas, il faut donc aussi surveiller cette table
  séparément pour ne pas rater les visionnages allés jusqu'au bout).

Position sur le disque : special://home/userdata/addon_data/
plugin.video.vstream/vstream.db (ou .../userdata/profiles/<profil>/
addon_data/... hors profil par défaut "Master user" - rarement utilisé en
usage domestique, géré en repli).

État de suivi (derniers addon_id déjà traités) persisté sur DISQUE (notre
propre dossier de données, jamais celui de vStream) pour ne jamais
retraiter une ancienne ligne après un redémarrage de Kodi - la retraiter
ferait régresser un film déjà marqué "vu" côté serveur vers une position
plus ancienne, plus faible.

seed_resume() est la SEULE écriture de ce module (tout le reste est
lecture seule) : insère un point de reprise dans la table `resume` d'UN
AUTRE appareil, avec le même `title` que vStream utilise lui-même (appris
en le relisant sur l'appareil qui a joué ce contenu en premier - jamais
reconstruit/deviné ici). vStream, au démarrage de sa propre lecture,
trouve alors une ligne qu'il croit avoir écrite lui-même et propose SA
PROPRE reprise native - aucune ligne de son code n'est modifiée, seule sa
base est complétée avec son propre format. Toujours utilisée avec le
paramétrage habituel (pas de mode=ro cette fois : c'est la seule fonction
qui a besoin d'écrire).
"""
import json
import sqlite3

import xbmc
import xbmcvfs

_DB_RELATIVE_DEFAULT = 'special://home/userdata/addon_data/plugin.video.vstream/vstream.db'
_DB_RELATIVE_PROFILE = 'special://home/userdata/profiles/{profile}/addon_data/plugin.video.vstream/vstream.db'
_STATE_DIR = 'special://profile/addon_data/plugin.video.alldebridmc/'
_STATE_FILE = _STATE_DIR + 'vstream_db_state.json'

MOVIE_CAT = '1'


def _resolve_db_path():
    default_path = xbmcvfs.translatePath(_DB_RELATIVE_DEFAULT)
    if xbmcvfs.exists(default_path):
        return default_path

    profile = xbmc.getInfoLabel('System.ProfileName')
    if profile and profile.strip().lower() != 'master user':
        profile_path = xbmcvfs.translatePath(_DB_RELATIVE_PROFILE.format(profile=profile))
        if xbmcvfs.exists(profile_path):
            return profile_path

    return None  # vStream non installé, ou base jamais créée (jamais utilisé)


def _connect_readonly(path):
    # uri=True + mode=ro : connexion strictement en lecture, vStream garde
    # la main entière sur l'écriture de sa propre base - jamais un seul
    # INSERT/UPDATE/DELETE depuis ce module.
    return sqlite3.connect('file:{0}?mode=ro'.format(path), uri=True, timeout=2)


def _load_state():
    try:
        with xbmcvfs.File(xbmcvfs.translatePath(_STATE_FILE)) as fh:
            return json.loads(fh.read())
    except Exception:
        return {}


def _save_state(state):
    xbmcvfs.mkdirs(xbmcvfs.translatePath(_STATE_DIR))
    try:
        fh = xbmcvfs.File(xbmcvfs.translatePath(_STATE_FILE), 'w')
        try:
            fh.write(json.dumps(state))
        finally:
            fh.close()
    except Exception:
        pass


class VStreamDbReader(object):
    """Un lecteur réutilisable (une instance par session de service.py) -
    garde en mémoire ET sur disque les derniers addon_id déjà traités pour
    ne renvoyer que les lignes nouvelles à chaque appel de poll()."""

    def __init__(self):
        state = _load_state()
        self.last_resume_id = state.get('last_resume_id', 0)
        self.last_watched_id = state.get('last_watched_id', 0)

    def save(self):
        _save_state({'last_resume_id': self.last_resume_id, 'last_watched_id': self.last_watched_id})

    def poll(self):
        """Renvoie une liste de (tmdb_id, position, duration, resume_key).
        Pour un film marqué vu (table `watched`, pas de point de reprise
        réel disponible dans ce cas) : position=duration=100.0 et
        resume_key=None (rien à corréler, l'entrée n'offre plus jamais de
        reprise de toute façon une fois "vu"). Liste vide si vStream n'est
        pas installé, sa base est absente/vide, ou rien de nouveau depuis
        le dernier appel."""
        path = _resolve_db_path()
        if not path:
            return []

        try:
            conn = _connect_readonly(path)
        except sqlite3.Error:
            return []

        results = []
        changed = False
        try:
            cur = conn.cursor()

            cur.execute(
                "SELECT resume.addon_id, resume.point, resume.total, resume.title, viewing.tmdb_id "
                "FROM resume JOIN viewing ON viewing.title_id = resume.title "
                "WHERE viewing.cat = ? AND resume.addon_id > ? "
                "ORDER BY resume.addon_id ASC",
                (MOVIE_CAT, self.last_resume_id),
            )
            for addon_id, point, total, title, tmdb_id in cur.fetchall():
                self.last_resume_id = max(self.last_resume_id, addon_id)
                changed = True
                if tmdb_id and str(tmdb_id).isdigit():
                    try:
                        results.append((int(tmdb_id), float(point), float(total), title or None))
                    except (TypeError, ValueError):
                        pass

            cur.execute(
                "SELECT addon_id, tmdb_id FROM watched WHERE cat = ? AND addon_id > ? ORDER BY addon_id ASC",
                (MOVIE_CAT, self.last_watched_id),
            )
            for addon_id, tmdb_id in cur.fetchall():
                self.last_watched_id = max(self.last_watched_id, addon_id)
                changed = True
                if tmdb_id and str(tmdb_id).isdigit():
                    results.append((int(tmdb_id), 100.0, 100.0, None))
        except sqlite3.Error:
            pass
        finally:
            conn.close()

        if changed:
            self.save()

        return results


def seed_resume(resume_key, position, duration):
    """Écrit un point de reprise dans la table `resume` LOCALE de vStream,
    avec sa propre clé de corrélation (apprise ailleurs, jamais construite
    ici) - pour que SON PROPRE mécanisme de reprise (onAVStarted, code non
    modifié) le trouve et le propose nativement à l'utilisateur. Seule
    écriture de ce module - tout le reste est lecture seule. Renvoie True
    si l'écriture a réussi, False sinon (vStream non installé, base
    verrouillée, erreur SQL...) - un échec ici ne doit jamais empêcher la
    lecture de démarrer normalement (sans reprise proposée)."""
    if not resume_key:
        return False

    path = _resolve_db_path()
    if not path:
        return False

    try:
        conn = sqlite3.connect(path, timeout=5)
    except sqlite3.Error:
        return False

    try:
        cur = conn.cursor()
        # Meme sequence que insert_resume() de vStream (resources/lib/db.py) :
        # supprime l'ancienne ligne pour ce titre avant de reinserer, pour
        # ne jamais laisser deux points de reprise concurrents.
        cur.execute("DELETE FROM resume WHERE title = ?", (resume_key,))
        cur.execute(
            "INSERT INTO resume (title, hoster, point, total) VALUES (?, ?, ?, ?)",
            (resume_key, '', float(position), float(duration)),
        )
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()
