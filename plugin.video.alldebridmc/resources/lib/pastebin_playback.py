# -*- coding: utf-8 -*-
"""Lecture directe d'un contenu Pastebin, en remplacement de
vstream_adapter.py (qui redirigeait entierement vers plugin.video.vstream) :
resout les fichiers disponibles pour un tmdb_id via le serveur
(resources/lib/api_client.py::resolve_pastebin_files, qui appelle lui-meme
unlock_link_once cote AllDebrid - voir la docstring de la route serveur
/api/kodi/lists/resolve-files), propose un choix de qualite si plusieurs
fichiers sont disponibles, renvoie le fichier choisi (avec son lien direct
deja resolu, pret pour setResolvedUrl()).

Etapes 1 (films, resolve_movie) et 2 (episodes, resolve_episode) du
chantier de suppression de vStream - meme resolution des deux cotes,
resolve_pastebin_files acceptant deja season/episode.
"""
import xbmc
import xbmcaddon
import xbmcgui

from resources.lib import api_client

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo('name')

# Secondes entre deux nouvelles tentatives d'un fichier "delayed" (AllDebrid
# doit encore le preparer cote hebergeur) - jamais interroge en boucle
# indefiniment (voir docstring serveur : le worker gunicorn, partage avec
# les telechargements en arriere-plan, ne doit jamais rester bloque sur un
# poll long) - c'est le CLIENT qui reessaie ici, un nombre borne de fois.
_RETRY_DELAYS_SECONDS = (2, 3, 5, 5, 5)


def _resolve_with_retry(media_type, tmdb_id, season=None, episode=None):
    files = api_client.resolve_pastebin_files(media_type, tmdb_id, season=season, episode=episode)

    for delay in _RETRY_DELAYS_SECONDS:
        if not any(f.get('delayed') for f in files):
            break
        xbmc.sleep(delay * 1000)
        files = api_client.resolve_pastebin_files(media_type, tmdb_id, season=season, episode=episode)

    # Les fichiers en echec (lien mort, erreur AllDebrid...) sont exclus en
    # silence plutot que proposes dans le choix de qualite - un choix qui
    # echouerait a nouveau si l'utilisateur le selectionnait.
    return [f for f in files if f.get('ok') and f.get('link')]


# Ordre d'affichage des groupes - "Autres" (resolution non detectee) en
# repli, demande explicitement, jamais une erreur ni un groupe cache.
_RESOLUTION_GROUP_ORDER = ('4K', '1080p', '720p', 'Autres')

# Tons discrets (le dialogue Dialog().select() de Kodi/Estuary a un fond
# GRIS CLAIR, pas sombre - un rose/vert fluo y "pique" les yeux, constate
# en conditions reelles). Bleu ardoise + vert sauge, assez lisibles sans
# etre criards.
_COLOR_AUDIO_TAG = 'FF4A6FA5'
_COLOR_SIZE = 'FFFF7F50'  # orange corail, demande explicitement


def _build_grouped_labels(playable):
    """Construit la liste plate consommee par Dialog().select() : un
    en-tete de groupe (non selectionnable - Dialog().select() ne sait pas
    desactiver une ligne, voir _pick_file) suivi de ses fichiers, dans
    l'ordre _RESOLUTION_GROUP_ORDER. playable arrive deja trie par
    _quality_sort_key cote serveur (voir resolve-files) - meilleure qualite
    d'abord PAR taille DANS un meme groupe de resolution - donc aucun tri
    supplementaire ici, juste un regroupement qui preserve cet ordre.
    Etiquette volontairement minimale (juste le tag audio + la taille) :
    la resolution est deja dite par l'en-tete de section, pas la peine de
    la repeter dans chaque ligne."""
    groups = {}
    for f in playable:
        groups.setdefault(f.get('resolution_group') or 'Autres', []).append(f)

    labels = []
    index_map = []  # meme longueur que labels ; None pour un en-tete

    for group_name in _RESOLUTION_GROUP_ORDER:
        files = groups.get(group_name)
        if not files:
            continue

        labels.append('[B]— {0} —[/B]'.format(group_name))
        index_map.append(None)

        for i, f in enumerate(files, start=1):
            tag = f.get('audio_tag') or '?'
            labels.append(
                '   Lien {0} : [COLOR {1}]{2}[/COLOR]  [COLOR {3}]{4}[/COLOR]'.format(
                    i, _COLOR_AUDIO_TAG, tag, _COLOR_SIZE, f.get('size_human') or '?',
                )
            )
            index_map.append(f)

    return labels, index_map


def _pick_file(playable):
    if len(playable) == 1:
        return playable[0]

    labels, index_map = _build_grouped_labels(playable)

    # Reaffiche tant qu'un en-tete est clique (Dialog().select() n'a pas de
    # notion de ligne desactivee - un clic dessus renvoie quand meme son
    # index) - rare en pratique (Kodi distingue visuellement le [B] du
    # reste), mais ne doit jamais planter en traitant un en-tete comme un
    # fichier.
    while True:
        index = xbmcgui.Dialog().select(ADDON.getLocalizedString(30353), labels)
        if index < 0:
            return None
        if index_map[index] is not None:
            return index_map[index]


def _pick_closest_match(playable, match_resolution, match_tag):
    """Choix SANS dialogue, pour l'enchainement automatique d'episodes
    (voir navigation.py::play_pastebin_episode, jamais pour un clic manuel -
    demande explicitement : ne pas interrompre le visionnage). Le plus
    proche de ce qui etait regarde sur l'episode precedent : meme groupe de
    resolution ET meme tag audio (le plus gros si plusieurs correspondent),
    sinon meme resolution seule (le plus gros), sinon le plus gros fichier
    tout court - playable est deja trie par taille decroissante a
    resolution/langue egales cote serveur (voir _quality_sort_key), donc
    max() sur "size" suffit a chaque etage plutot que de re-trier."""
    if match_resolution and match_tag:
        exact = [
            f for f in playable
            if f.get('resolution_group') == match_resolution and f.get('audio_tag') == match_tag
        ]
        if exact:
            return max(exact, key=lambda f: f.get('size') or 0)

    if match_resolution:
        same_resolution = [f for f in playable if f.get('resolution_group') == match_resolution]
        if same_resolution:
            return max(same_resolution, key=lambda f: f.get('size') or 0)

    return max(playable, key=lambda f: f.get('size') or 0)


def _resolve_and_pick(media_type, tmdb_id, season=None, episode=None, auto_match=None):
    """Commun a resolve_movie/resolve_episode : resout, notifie en cas
    d'echec reseau ou d'absence totale de fichier, puis choisit un fichier -
    au dialogue (cas normal) ou automatiquement (auto_match = (resolution,
    tag) du fichier precedent, voir _pick_closest_match - enchainement
    uniquement). Renvoie None dans tous les cas d'echec/annulation - jamais
    d'exception remontee a l'appelant (voir navigation.py)."""
    try:
        playable = _resolve_with_retry(media_type, tmdb_id, season=season, episode=episode)
    except api_client.ApiError:
        xbmcgui.Dialog().notification(
            ADDON_NAME, ADDON.getLocalizedString(30012), xbmcgui.NOTIFICATION_ERROR, 5000,
        )
        return None

    if not playable:
        xbmcgui.Dialog().notification(
            ADDON_NAME, ADDON.getLocalizedString(30354), xbmcgui.NOTIFICATION_ERROR, 5000,
        )
        return None

    if auto_match:
        match_resolution, match_tag = auto_match
        return _pick_closest_match(playable, match_resolution, match_tag)

    return _pick_file(playable)


def resolve_movie(tmdb_id):
    """Renvoie le fichier choisi par l'utilisateur ({label, size_human,
    host, link, ...}) pour ce film, ou None (rien de resolu, ou choix
    annule)."""
    return _resolve_and_pick('movie', tmdb_id)


def resolve_episode(tmdb_id, season, episode, auto_match=None):
    """Etape 2 du chantier de suppression de vStream : meme principe que
    resolve_movie, filtre par saison/episode - resolve-files (cote serveur)
    accepte deja ces deux parametres, aucun changement serveur necessaire
    ici. auto_match : voir _resolve_and_pick/_pick_closest_match."""
    return _resolve_and_pick('tv', tmdb_id, season=season, episode=episode, auto_match=auto_match)
