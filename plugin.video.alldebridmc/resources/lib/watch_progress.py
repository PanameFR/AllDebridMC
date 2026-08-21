# -*- coding: utf-8 -*-
"""Reprise de lecture synchronisée entre appareils Kodi, via le serveur
(watch_progress.py côté Pi) - et écrans "En cours"/"Historique" pour le
contenu du MediaCenter (équivalent, pour notre addon, de ce que vStream
propose déjà pour son propre contenu - vStream n'est ni modifié ni
intégré, on construit juste le même genre d'écran chez nous).

Suivi de lecture MediaCenter (locale) : pas de service.py séparé pour
cette partie. main.py appelle juste navigation.route(...) puis termine -
rien n'oblige le script à revenir vite après xbmcplugin.setResolvedUrl()
(qui débloque immédiatement le lecteur Kodi ; le timeout de résolution ne
s'applique qu'à la phase AVANT cet appel). track_playback() est donc
appelée à la suite, dans le même script, et bloque jusqu'à la fin de la
lecture - pattern réel, déjà utilisé par des addons de scrobbling Kodi.

Suivi de lecture vStream (films uniquement, lancés depuis notre propre
addon) : là, un service.py persistant (nouveau point d'extension
xbmc.service, à la racine de l'addon) est nécessaire, parce que notre
script n'est plus actif au moment où la lecture réelle démarre chez
vStream (plusieurs écrans plus tard, après le choix d'un hébergeur). Voir
arm_vstream_marker()/consume_vstream_marker()/is_own_smb_path() plus bas -
le service filtre explicitement notre propre lecture SMB (déjà suivie via
track_playback ci-dessus) pour ne jamais la rapporter deux fois.

Import de navigation en tête (build_list_item) : c'est pour ça que
navigation.py importe CE module en différé (voir route()/play_item()) et
jamais l'inverse, pour éviter un cycle.
"""
import json
import time
import urllib.parse

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

from resources.lib import api_client, navigation, playback

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo('name')

HEARTBEAT_INTERVAL = 20  # secondes entre deux rapports pendant la lecture
START_TIMEOUT = 45  # secondes max d'attente que la lecture demarre vraiment

_STATUS_BY_ACTION = {'watch_in_progress': 'in_progress', 'watch_history': 'watched'}
_LABEL_BY_ACTION = {'watch_in_progress': 30250, 'watch_history': 30251}

# Repere pose juste avant de rediriger vers un film vStream lance depuis
# notre propre addon (Mes Listes/Recherche/En cours) - consomme par
# service.py au demarrage de la lecture reelle qui suit, potentiellement
# plusieurs ecrans plus tard a l'interieur de vStream (choix d'un
# hebergeur). Fenetre 10000 : mecanisme standard Kodi pour communiquer
# entre scripts/processus separes au sein de la meme session. Voir la
# docstring en tete de module pour la limite assumee (navigation vStream
# native jamais suivie - aucune identite TMDB fiable n'en ressort).
_VSTREAM_MARKER_PROPERTY = 'script.plugin.video.alldebridmc.pending_vstream_movie'
VSTREAM_MARKER_TIMEOUT = 300  # secondes : le temps de choisir un hebergeur dans vStream avant lecture reelle


def _enabled():
    try:
        return ADDON.getSettingBool('watch_progress_enabled')
    except (AttributeError, TypeError):
        return True


def device_name():
    try:
        return (ADDON.getSettingString('device_name') or '').strip()
    except (AttributeError, TypeError):
        return ''


def _format_time(seconds):
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return '{0:d}:{1:02d}:{2:02d}'.format(hours, minutes, secs)
    return '{0:d}:{1:02d}'.format(minutes, secs)


# ---- reprise avant lecture (appelé depuis navigation.play_item) ----------

def maybe_apply_resume(info, relative_path, title):
    if not relative_path or not _enabled():
        return

    try:
        progress = api_client.get_watch_progress(relative_path)
    except api_client.ApiError:
        return  # ne bloque jamais la lecture pour un probleme reseau

    if not progress:
        return

    position, duration = progress.get('position'), progress.get('duration')
    if not position or not duration:
        return

    device = progress.get('device') or '?'
    message = ADDON.getLocalizedString(30253).format(device, _format_time(position))

    # Le titre en en-tete plutot qu'un texte generique : utile pour lever
    # toute ambiguite sur CE qui reprend, surtout depuis l'ecran "En cours"
    # ou plusieurs reprises possibles se ressemblent a l'oeil.
    resume = xbmcgui.Dialog().yesno(
        heading=title or ADDON.getLocalizedString(30252),
        message=message,
        nolabel=ADDON.getLocalizedString(30255),
        yeslabel=ADDON.getLocalizedString(30254),
    )

    if resume:
        info.setResumePoint(float(position), float(duration))
    else:
        try:
            api_client.clear_watch_progress(relative_path)
        except api_client.ApiError:
            pass


# ---- suivi pendant/apres lecture (appelé depuis navigation.play_item) ----

class _ProgressPlayer(xbmc.Player):
    def __init__(self):
        super().__init__()
        self.started = False
        self.stopped = False

    def onAVStarted(self):
        self.started = True

    def onPlayBackStopped(self):
        self.stopped = True

    def onPlayBackEnded(self):
        self.stopped = True

    def onPlayBackError(self):
        self.stopped = True


def _report(relative_path, position, duration, device):
    try:
        api_client.post_watch_progress(relative_path, position, duration, device)
    except api_client.ApiError:
        pass  # best-effort : un heartbeat rate ne doit jamais interrompre la lecture ni notifier


# ---- suivi des films vStream lances depuis notre addon (service.py) ------

def arm_vstream_marker(tmdb_id):
    if not _enabled():
        return
    xbmcgui.Window(10000).setProperty(
        _VSTREAM_MARKER_PROPERTY, json.dumps({'tmdb_id': tmdb_id, 'armed_at': time.time()}),
    )


def consume_vstream_marker(timeout=VSTREAM_MARKER_TIMEOUT):
    """Lit et efface le repere (une seule consommation possible) - un
    repere trop vieux (navigation plus longue que `timeout` dans vStream
    avant lecture reelle, ou repere abandonne puis autre chose regarde
    ensuite) est ignore plutot que mal attribue a la mauvaise lecture."""
    window = xbmcgui.Window(10000)
    raw = window.getProperty(_VSTREAM_MARKER_PROPERTY)
    if not raw:
        return None
    window.clearProperty(_VSTREAM_MARKER_PROPERTY)
    try:
        marker = json.loads(raw)
    except ValueError:
        return None
    if time.time() - marker.get('armed_at', 0) > timeout:
        return None
    return marker


def is_own_smb_path(playing_file):
    """Vrai si le fichier en cours de lecture vient de NOTRE partage SMB
    MediaCenter - deja suivi par navigation.play_item()/track_playback(),
    jamais a rapporter une seconde fois depuis service.py.

    Compare uniquement hote+partage, jamais les identifiants : Kodi peut
    masquer user:pass dans les infos de lecture exposees (getPlayingFile),
    ce qui casserait une comparaison de prefixe complet construite nous-
    memes via playback.build_smb_url()."""
    if not playing_file or not playing_file.lower().startswith('smb://'):
        return False
    try:
        parsed = urllib.parse.urlsplit(playing_file)
        server = playback.ADDON.getSettingString('server').strip().lower()
        share = playback.ADDON.getSettingString('smb_share').strip().lower()
    except Exception:
        return False
    path_first_segment = parsed.path.lstrip('/').split('/', 1)[0].lower()
    return (parsed.hostname or '') == server and path_first_segment == share


def report_vstream(tmdb_id, position, duration, device):
    try:
        api_client.post_watch_progress_vstream(tmdb_id, position, duration, device)
    except api_client.ApiError:
        pass  # best-effort, meme raison que _report() pour le local


def track_playback(relative_path):
    if not relative_path or not _enabled():
        return

    player = _ProgressPlayer()
    monitor = xbmc.Monitor()
    device = device_name()

    waited = 0
    while not player.started and waited < START_TIMEOUT:
        if monitor.waitForAbort(1):
            return
        waited += 1

    if not player.started:
        # La lecture n'a jamais vraiment demarre (erreur, SMB injoignable...)
        # - Kodi affiche deja sa propre erreur, rien a rapporter.
        return

    last_position, last_duration = 0.0, 0.0

    while not player.stopped:
        if monitor.waitForAbort(HEARTBEAT_INTERVAL):
            break
        if player.stopped or not player.isPlaying():
            continue
        try:
            last_position = player.getTime()
            last_duration = player.getTotalTime()
        except Exception:
            continue
        _report(relative_path, last_position, last_duration, device)

    if last_duration:
        _report(relative_path, last_position, last_duration, device)


# ---- ecrans "En cours" / "Historique" -------------------------------------

def dispatch(base_url, handle, params):
    action = params.get('action')

    if action == 'watch_clear':
        _action_clear(params)
        xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)
        return

    if action == 'watch_open_vstream_movie':
        _action_open_vstream_movie(params)
        xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)
        return

    _render_list(base_url, handle, action)


def _action_clear(params):
    source = params.get('source', 'local')
    try:
        if source == 'vstream':
            tmdb_id = params.get('tmdb_id', '')
            if not tmdb_id.isdigit():
                return
            api_client.clear_watch_progress_vstream(int(tmdb_id))
        else:
            relative_path = params.get('path', '')
            if not relative_path:
                return
            api_client.clear_watch_progress(relative_path)
    except api_client.ApiError:
        xbmcgui.Dialog().notification(
            ADDON_NAME, ADDON.getLocalizedString(30012), xbmcgui.NOTIFICATION_ERROR, 5000,
        )
        return
    xbmc.executebuiltin('Container.Refresh')


def _action_open_vstream_movie(params):
    """Point d'entree commun pour tout film vStream lance depuis notre
    addon (Mes Listes/Recherche/En cours) : pose le repere PUIS redirige,
    exactement comme le faisait l'appel direct a adapter.movie_url()
    auparavant - un seul saut de plus, invisible pour l'utilisateur."""
    tmdb_id_raw = params.get('tmdb_id', '')
    if not tmdb_id_raw.isdigit():
        return
    tmdb_id = int(tmdb_id_raw)

    arm_vstream_marker(tmdb_id)

    from resources.lib.vstream_adapter import VStreamPastebinAdapter
    adapter = VStreamPastebinAdapter()
    target = adapter.movie_url(tmdb_id, title=params.get('title'), poster_url=params.get('poster_url'))
    # ",replace" evite d'empiler un ecran intermediaire dans l'historique
    # retour de Kodi - revenir en arriere depuis vStream doit ramener a
    # l'ecran d'origine (Mes Listes/Recherche/En cours), pas a ce relais.
    xbmc.executebuiltin('Container.Update(%s,replace)' % target)


def _render_list(base_url, handle, action):
    status = _STATUS_BY_ACTION.get(action)
    if status is None:
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    try:
        entries = api_client.list_watch_progress(status)
    except api_client.ApiError:
        xbmcgui.Dialog().notification(
            ADDON_NAME, ADDON.getLocalizedString(30012), xbmcgui.NOTIFICATION_ERROR, 5000,
        )
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    xbmcplugin.setPluginCategory(handle, ADDON.getLocalizedString(_LABEL_BY_ACTION[action]))
    xbmcplugin.setContent(handle, 'episodes' if any(e.get('episode_info') for e in entries) else 'movies')

    items = []
    for entry in entries:
        watch_progress_info = entry.get('watch_progress') or {}
        if watch_progress_info.get('source') == 'vstream':
            url, list_item, is_folder = _build_vstream_item(base_url, entry)
        else:
            url, list_item, is_folder = navigation.build_list_item(base_url, entry)
        _apply_visuals(list_item, watch_progress_info, watched=(status == 'watched'))
        _add_remove_context_item(list_item, base_url, entry, watch_progress_info)
        items.append((url, list_item, is_folder))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    # Deja trie par le serveur (plus recent d'abord) : on garde cet ordre
    # plutot que le tri natif de Kodi, meme raison que list_directory().
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=True, updateListing=False, cacheToDisc=False)


def _apply_visuals(list_item, progress, watched):
    info = list_item.getVideoInfoTag()
    if watched:
        # Coche "vu" native de Kodi, meme convention visuelle que le reste
        # de l'interface pour du contenu deja regarde.
        info.setPlaycount(1)
        return
    if not progress:
        return
    position, duration = progress.get('position'), progress.get('duration')
    if position and duration:
        # Barre de progression native Kodi sur la vignette (skin Estuary) -
        # affichage seulement, la vraie proposition de reprise reste le
        # dialogue de maybe_apply_resume() au moment de lancer la lecture.
        info.setResumePoint(float(position), float(duration))


def _build_vstream_item(base_url, entry):
    """ListItem pour un film vStream suivi (jamais navigation.build_list_item,
    qui suppose un chemin local - entry['path'] est None ici). Cible =
    notre propre action watch_open_vstream_movie (pose le repere puis
    redirige), isFolder=True - meme convention que lists_gui.render_list()
    pour du contenu vStream (on atterrit sur la liste des hebergeurs, pas
    directement sur une lecture)."""
    poster = entry.get('poster') or {}
    title = poster.get('title') or entry.get('name') or '?'
    year = poster.get('year')
    label = '{0} ({1})'.format(title, year) if year else title

    list_item = xbmcgui.ListItem(label=label, offscreen=True)
    if poster.get('poster_url'):
        list_item.setArt({'thumb': poster['poster_url'], 'poster': poster['poster_url']})

    info = list_item.getVideoInfoTag()
    info.setTitle(label)
    info.setMediaType('movie')
    if year:
        info.setYear(int(year))

    url = navigation.build_watch_action_url(
        base_url, 'watch_open_vstream_movie', tmdb_id=poster.get('tmdb_id'),
        title=title, poster_url=poster.get('poster_url') or '',
    )
    return url, list_item, True


def _add_remove_context_item(list_item, base_url, entry, watch_progress_info):
    if watch_progress_info.get('source') == 'vstream':
        tmdb_id = (entry.get('poster') or {}).get('tmdb_id')
        url = navigation.build_watch_action_url(base_url, 'watch_clear', source='vstream', tmdb_id=tmdb_id)
    else:
        url = navigation.build_watch_action_url(base_url, 'watch_clear', path=entry.get('path'))
    list_item.addContextMenuItems([
        (ADDON.getLocalizedString(30256), 'RunPlugin({0})'.format(url)),
    ])
