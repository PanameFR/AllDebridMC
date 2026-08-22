# -*- coding: utf-8 -*-
"""Lecture SEULE de la base SQLite locale de vStream (aucun INSERT/UPDATE/
DELETE, uniquement des SELECT) pour récupérer la progression que vStream a
lui-même déjà enregistrée - que la lecture ait été lancée depuis notre
addon OU directement dans vStream, peu importe : ce mécanisme fonctionne
dans les deux cas, contrairement à un repère posé-avant-redirection
(approche précédente, abandonnée - voir historique Git) qui ne couvrait
que notre propre redirection.

Films ET épisodes de séries (episode precis, pas juste la saison - voir
plus bas pourquoi une version anterieure de ce module s'en croyait
incapable).

Schéma vérifié en lisant le code source réel de vStream
(resources/lib/db.py, resources/lib/player.py) avant d'écrire ce module,
jamais deviné :
- table `resume` (title, hoster, point, total) : point de reprise d'un
  contenu EN COURS (>180s de lecture, <90% vu), `title` = titre Kodi
  normalisé (espaces retirés) - écrite UNIQUEMENT à l'arrêt de la lecture
  (onPlayBackStopped/Ended), jamais pendant - pas de reprise "en direct"
  possible, seulement "où on s'est arrêté la dernière fois". `hoster` =
  en fait le siteUrl Pastebin ORIGINAL complet (pas juste un nom
  d'hébergeur, malgré le nom de la colonne) - confirmé en inspectant une
  vraie ligne apres visionnage reel (Futurama en cours) :
  ".../raw/&sMedia=serie&sYear=1999&idTMDB=615&sTitle=Futurama&sSaison=01&sEpisode=1" -
  contient donc idTMDB, sSaison ET sEpisode, tous trois exploitables ici
  (voir _parse_encoded_params). vStream::get_resume() (resources/lib/db.py)
  ne relit JAMAIS cette colonne pour retrouver un point de reprise - la
  correspondance se fait UNIQUEMENT par `title` (donc par show entier pour
  une serie, jamais par episode precis cote vStream lui-meme) : nos
  propres ecrans "En cours" peuvent afficher/synchroniser un episode
  precis, mais le mecanisme de reprise NATIF de vStream, une fois relance,
  proposera cette reprise quel que soit l'episode du meme show qu'on
  commence a regarder - limite de vStream, pas quelque chose qu'on peut
  changer d'ici.
- table `watched` (tmdb_id, title_id, title, siteurl, cat, season) : films/
  séries marqués VUS - écrite À LA PLACE de resume quand le seuil de 90%
  est dépassé (resume est alors supprimé côté vStream). `siteurl` = même
  role que `resume.hoster` (siteUrl Pastebin complet, meme parsing).
- table `viewing` (tmdb_id, title_id, title, cat, season, ...) : ce que
  vStream affiche dans "Mes contenus/Mes visionnages en cours" - PAS
  utilisee ici (voir plus bas).

Version anterieure de ce module : limitee aux films, joignait `resume` a
`viewing` (`viewing.title_id = resume.title`) pour recuperer idTMDB,
resume.title seul ne le portant pas. Abandonne : pour une serie,
`viewing.title_id` porte un suffixe de saison (ex: 'futurama_S01') que
`resume.title` n'a jamais (juste 'futurama') - cette jointure ne
matchait donc simplement JAMAIS pour une serie (confirme avec une vraie
ligne Futurama : aucune correspondance possible), d'ou la conclusion
(fausse) que "l'episode precis n'est pas recuperable ici". Le vrai
idTMDB (+ saison/episode pour une serie) est en fait deja directement
dans `resume.hoster`/`watched.siteurl` - le lire depuis LA, en le
parsant, evite la jointure et fonctionne pour les deux.

Position sur le disque : special://home/userdata/addon_data/
plugin.video.vstream/vstream.db (ou .../userdata/profiles/<profil>/
addon_data/... hors profil par défaut "Master user" - rarement utilisé en
usage domestique, géré en repli).

État de suivi (derniers addon_id déjà traités) persisté sur DISQUE (notre
propre dossier de données, jamais celui de vStream) pour ne jamais
retraiter une ancienne ligne après un redémarrage de Kodi - la retraiter
ferait régresser un contenu déjà marqué "vu" côté serveur vers une
position plus ancienne, plus faible.

seed_resume() est la SEULE écriture de ce module (tout le reste est
lecture seule) : insère un point de reprise dans la table `resume` d'UN
AUTRE appareil, avec le même `title` que vStream utilise lui-même (appris
en le relisant sur l'appareil qui a joué ce contenu en premier - jamais
reconstruit/deviné ici). vStream, au démarrage de sa propre lecture,
trouve alors une ligne qu'il croit avoir écrite lui-même et propose SA
PROPRE reprise native - aucune ligne de son code n'est modifiée, seule sa
base est complétée avec son propre format (`hoster` laissé vide : voir
plus haut, vStream ne le relit jamais pour cette correspondance, donc pas
la peine de le reconstruire). Toujours utilisée avec le paramétrage
habituel (pas de mode=ro cette fois : c'est la seule fonction qui a
besoin d'écrire).
"""
import json
import sqlite3
import urllib.parse

import xbmc
import xbmcvfs

_DB_RELATIVE_DEFAULT = 'special://home/userdata/addon_data/plugin.video.vstream/vstream.db'
_DB_RELATIVE_PROFILE = 'special://home/userdata/profiles/{profile}/addon_data/plugin.video.vstream/vstream.db'
_STATE_DIR = 'special://profile/addon_data/plugin.video.alldebridmc/'
_STATE_FILE = _STATE_DIR + 'vstream_db_state.json'


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


def _parse_encoded_params(raw):
    """Reconstruit le dict de parametres depuis resume.hoster/watched.siteurl
    (le siteUrl Pastebin original, URL-encode - voir docstring du module).
    Meme decoupage que pastebin.py lui-meme (split '&' puis '='), mais
    tolerant : un segment sans '=' (le prefixe 'https://.../raw/') est
    simplement ignore plutot que de lever une exception - jamais vu
    d'erreur de format ici, mais ce module ne doit jamais faire planter le
    service pour une ligne mal formee."""
    if not raw:
        return {}
    try:
        decoded = urllib.parse.unquote_plus(raw)
    except (TypeError, ValueError):
        return {}
    params = {}
    for segment in decoded.split('&'):
        if '=' not in segment:
            continue
        key, _, value = segment.partition('=')
        params[key] = value
    return params


def _season_episode_from_params(params):
    season = params.get('sSaison')
    episode = params.get('sEpisode')
    if not (season and episode and str(season).isdigit() and str(episode).isdigit()):
        return None, None
    return int(season), int(episode)


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
        """Renvoie une liste de (tmdb_id, position, duration, resume_key,
        season, episode) - season/episode a None pour un film. Pour un
        contenu marque vu (table `watched`, pas de point de reprise reel
        disponible dans ce cas) : position=duration=100.0 et
        resume_key=None (rien a correler, l'entree n'offre plus jamais de
        reprise de toute facon une fois "vu"). Liste vide si vStream n'est
        pas installe, sa base est absente/vide, ou rien de nouveau depuis
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
                "SELECT addon_id, point, total, title, hoster FROM resume "
                "WHERE addon_id > ? ORDER BY addon_id ASC",
                (self.last_resume_id,),
            )
            for addon_id, point, total, title, hoster in cur.fetchall():
                self.last_resume_id = max(self.last_resume_id, addon_id)
                changed = True
                params = _parse_encoded_params(hoster)
                tmdb_id = params.get('idTMDB')
                if not (tmdb_id and tmdb_id.isdigit()):
                    continue
                season, episode = _season_episode_from_params(params)
                try:
                    results.append(
                        (int(tmdb_id), float(point), float(total), title or None, season, episode)
                    )
                except (TypeError, ValueError):
                    pass

            cur.execute(
                "SELECT addon_id, tmdb_id, siteurl FROM watched WHERE addon_id > ? ORDER BY addon_id ASC",
                (self.last_watched_id,),
            )
            for addon_id, tmdb_id, siteurl in cur.fetchall():
                self.last_watched_id = max(self.last_watched_id, addon_id)
                changed = True
                if tmdb_id and str(tmdb_id).isdigit():
                    season, episode = _season_episode_from_params(_parse_encoded_params(siteurl))
                    results.append((int(tmdb_id), 100.0, 100.0, None, season, episode))
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
