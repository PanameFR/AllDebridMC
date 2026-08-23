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

Suivi de lecture vStream (films uniquement - même limite qu'avant : une
série n'a que la saison dans la table `viewing` de vStream, jamais
l'épisode précis, insuffisant pour une reprise fiable) : ne passe PAS par
un suivi événementiel xbmc.Player comme le local. service.py (nouveau
point d'extension xbmc.service, à la racine de l'addon) sonde
PÉRIODIQUEMENT, en lecture seule, la base SQLite locale de vStream (voir
vstream_db.py) - c'est vStream LUI-MÊME qui y écrit position/tmdb_id à
chaque arrêt de lecture, que celle-ci ait été lancée depuis notre addon OU
depuis la navigation native de vStream. Ancienne approche abandonnée
(reprise Git) : poser un repère avant de rediriger vers vStream, consommé
par un xbmc.Player dans le service - ne couvrait que notre propre
redirection, jamais la navigation native, et dépendait d'une fenêtre de
temps fragile. Lire la base est strictement meilleur : plus simple, et
couvre aussi la navigation native.

Reprise RÉELLEMENT synchronisée pour vStream (pas juste affichée) : avant
de construire le lien vStream d'un film listé (voir lists_gui.py, qui
appelle maybe_seed_vstream_resume() au RENDU de la liste, pas au clic -
l'item pointe ensuite directement vers vStream, sans écran relais), on
regarde si le serveur connaît une position plus récente pour ce tmdb_id,
et si oui on l'écrit dans la table `resume` LOCALE de vStream
(vstream_db.seed_resume, avec sa propre clé de corrélation, apprise en la
relisant sur l'appareil qui a joué ce film en premier - jamais devinée).
Le mécanisme natif de vStream (code non modifié) la trouve alors et
propose lui-même sa reprise. Ne fonctionne toujours que pour les films
listés depuis notre addon (aucun moyen d'agir avant que vStream ne prenne
la main depuis sa propre navigation), et seulement pour un film déjà joué
au moins une fois quelque part (sinon la clé de corrélation n'est pas
encore connue).

Import de navigation en tête (build_list_item) : c'est pour ça que
navigation.py importe CE module en différé (voir route()/play_item()) et
jamais l'inverse, pour éviter un cycle.
"""
import json
import os

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from resources.lib import api_client, navigation, vstream_db

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo('name')
ADDON_ID = ADDON.getAddonInfo('id')

HEARTBEAT_INTERVAL = 20  # secondes entre deux rapports pendant la lecture
START_TIMEOUT = 45  # secondes max d'attente que la lecture demarre vraiment

_STATUS_BY_ACTION = {'watch_in_progress': 'in_progress', 'watch_history': 'watched'}
_LABEL_BY_ACTION = {'watch_in_progress': 30250, 'watch_history': 30251}


def enabled():
    try:
        return ADDON.getSettingBool('watch_progress_enabled')
    except (AttributeError, TypeError):
        return True


def device_name():
    try:
        return (ADDON.getSettingString('device_name') or '').strip()
    except (AttributeError, TypeError):
        return ''


_LAST_SEEN_UPDATE_FILENAME = 'last_seen_watch_progress_update.json'


def _last_seen_update_path():
    root = xbmcvfs.translatePath('special://home/userdata/addon_data/{0}/'.format(ADDON_ID))
    return os.path.join(root, _LAST_SEEN_UPDATE_FILENAME)


def _read_last_seen_update():
    try:
        with open(_last_seen_update_path(), 'r', encoding='utf-8') as fh:
            return json.load(fh).get('updated_at')
    except (OSError, ValueError, AttributeError):
        return None


def _write_last_seen_update(value):
    path = _last_seen_update_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'updated_at': value}, fh)
    except OSError:
        pass


def server_has_new_watch_progress():
    """Utilise par service.py pour ne rafraichir un ecran (dont l'accueil,
    voir _maybe_auto_refresh) que quand une synchronisation a REELLEMENT eu
    lieu depuis un autre appareil - jamais sur une simple minuterie
    aveugle. Compare l'horodatage du serveur (petit fichier, jamais
    d'enrichissement - cf. api_client.get_watch_progress_last_updated) au
    dernier vu localement (fichier a part, pas un reglage de l'addon -
    meme logique que le marqueur de kodi_backup.py)."""
    try:
        remote = api_client.get_watch_progress_last_updated()
    except api_client.ApiError:
        return False

    remote_value = remote.get('updated_at') if isinstance(remote, dict) else None
    if not remote_value:
        return False

    if remote_value == _read_last_seen_update():
        return False

    _write_last_seen_update(remote_value)
    return True


def _format_time(seconds):
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return '{0:d}:{1:02d}:{2:02d}'.format(hours, minutes, secs)
    return '{0:d}:{1:02d}'.format(minutes, secs)


# ---- reprise avant lecture (appelé depuis navigation.play_item) ----------

def maybe_apply_resume(info, relative_path, title):
    if not relative_path or not enabled():
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


# ---- suivi des films vStream (service.py, sondage de sa base SQLite) -----

def report_vstream(tmdb_id, position, duration, device, resume_key=None, season=None, episode=None, smedia=None):
    try:
        api_client.post_watch_progress_vstream(
            tmdb_id, position, duration, device,
            resume_key=resume_key, season=season, episode=episode, smedia=smedia,
        )
    except api_client.ApiError:
        pass  # best-effort, meme raison que _report() pour le local


def track_playback(relative_path):
    if not relative_path or not enabled():
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

    if action == 'watch_show_seasons':
        _render_show_seasons(base_url, handle, params)
        return

    if action == 'watch_show_episodes':
        _render_show_episodes(base_url, handle, params)
        return

    _render_list(base_url, handle, action, params)


def _action_clear(params):
    source = params.get('source', 'local')
    try:
        if source == 'vstream':
            tmdb_id = params.get('tmdb_id', '')
            if not tmdb_id.isdigit():
                return
            season, episode = params.get('season'), params.get('episode')
            if season is not None and episode is not None:
                api_client.clear_watch_progress_vstream(int(tmdb_id), season=int(season), episode=int(episode))
            else:
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


def _vstream_resume_write_enabled():
    try:
        return ADDON.getSettingBool('vstream_resume_write_enabled')
    except (AttributeError, TypeError):
        return True


def maybe_seed_vstream_resume(tmdb_id, season=None, episode=None):
    """A appeler avant de construire le lien vStream d'un film (voir
    lists_gui.py) : si le serveur connaît une position plus récente pour ce
    film (peut-être laissée sur un AUTRE appareil), on l'écrit dans la base
    locale de vStream, pour que SON PROPRE mécanisme de reprise (code non
    modifié) la propose - voir la docstring en tête de module. Un échec à
    n'importe quelle étape ici (serveur injoignable, position inconnue, clé
    de corrélation pas encore apprise) ne fait simplement rien - vStream
    démarre alors normalement, sans reprise - jamais bloquant.

    Appelée au RENDU de la liste (pas au clic) : le lien de l'item pointe
    alors directement vers vStream (adapter.movie_url(), meme chemin propre
    et direct qu'une série - voir tvshow_url()), sans écran relais. Un
    relais séparé (action dédiée, Container.Update différé) a été essayé
    avant : le contenu vStream finissait par s'afficher, mais "Retour"
    depuis cet écran remontait vers vStream lui-même plutôt que vers notre
    liste (contrairement à une série, qui n'a jamais eu ce relais) - la
    pile de navigation de Kodi restait légèrement faussée même quand le
    contenu affiché était correct. Vérifier ici, avant tout push d'écran,
    l'évite structurellement plutôt que de rejouer avec le timing."""
    if not (enabled() and _vstream_resume_write_enabled()):
        return
    try:
        progress = api_client.get_watch_progress_vstream(int(tmdb_id), season=season, episode=episode)
    except (api_client.ApiError, TypeError, ValueError):
        return
    if progress and progress.get('resume_key'):
        vstream_db.seed_resume(progress['resume_key'], progress['position'], progress['duration'])


def _render_list(base_url, handle, action, params):
    status = _STATUS_BY_ACTION.get(action)
    if status is None:
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    # "En cours <categorie>" (Films/Series/Documentaires/...) - absent pour
    # "Historique", qui reste un seul ecran fourre-tout (jamais scinde,
    # jamais demande) - voir navigation._WATCH_CATEGORIES pour le libelle.
    category = params.get('category')

    try:
        entries = api_client.list_watch_progress(status, category=category)
    except api_client.ApiError:
        xbmcgui.Dialog().notification(
            ADDON_NAME, ADDON.getLocalizedString(30012), xbmcgui.NOTIFICATION_ERROR, 5000,
        )
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    label = ADDON.getLocalizedString(_LABEL_BY_ACTION[action])
    if category:
        category_label_id = dict(navigation._WATCH_CATEGORIES).get(category)
        if category_label_id:
            label = '%s - %s' % (label, ADDON.getLocalizedString(category_label_id))
    xbmcplugin.setPluginCategory(handle, label)
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
    """ListItem pour un film OU une SERIE (jamais un episode precis - voir
    docstring en tete de module) vStream suivi (jamais
    navigation.build_list_item, qui suppose un chemin local -
    entry['path'] est None ici).

    Film : cible = lien vStream direct (adapter.movie_url()), meme
    convention que lists_gui.render_list() - on atterrit sur la liste des
    hebergeurs, avec la reprise pre-semee ici (maybe_seed_vstream_resume),
    puisqu'un film n'a qu'UNE seule progression possible, sans ambiguite.

    Serie : cible = notre propre ecran Saisons (action watch_show_seasons,
    jamais une action de vStream) - PAS de seed ici, l'episode reel n'est
    pas encore connu a ce stade (voir _render_show_episodes, seul endroit
    ou il l'est vraiment)."""
    poster = entry.get('poster') or {}
    title = poster.get('title') or entry.get('name') or '?'
    year = poster.get('year')
    is_series = poster.get('media_type') == 'tv'

    label = '{0} ({1})'.format(title, year) if year else title

    list_item = xbmcgui.ListItem(label=label, offscreen=True)
    if poster.get('poster_url'):
        list_item.setArt({'thumb': poster['poster_url'], 'poster': poster['poster_url']})

    info = list_item.getVideoInfoTag()
    info.setTitle(label)
    info.setMediaType('tvshow' if is_series else 'movie')
    if year:
        info.setYear(int(year))
    if poster.get('overview'):
        info.setPlot(poster['overview'])

    tmdb_id = poster.get('tmdb_id')
    if is_series:
        url = navigation.build_watch_action_url(
            base_url, 'watch_show_seasons', tmdb_id=tmdb_id, title=title, smedia=poster.get('smedia') or '',
        )
    else:
        maybe_seed_vstream_resume(tmdb_id)
        from resources.lib.vstream_adapter import VStreamPastebinAdapter
        adapter = VStreamPastebinAdapter()
        url = adapter.movie_url(tmdb_id, title=title, poster_url=poster.get('poster_url'))
    return url, list_item, True


def _render_show_seasons(base_url, handle, params):
    """Ecran "Saisons" pour une serie vStream suivie (En cours/Historique) -
    construit depuis pastebin_catalog.py cote serveur (jamais vStream
    directement), pour garder la main jusqu'au clic sur l'episode precis
    (voir _render_show_episodes) et pouvoir semer la bonne reprise a ce
    moment-la, jamais avant."""
    tmdb_id = params.get('tmdb_id', '')
    title = params.get('title', '')
    smedia = params.get('smedia') or None

    try:
        data = api_client.get_watch_progress_vstream_seasons(tmdb_id)
    except api_client.ApiError:
        xbmcgui.Dialog().notification(
            ADDON_NAME, ADDON.getLocalizedString(30012), xbmcgui.NOTIFICATION_ERROR, 5000,
        )
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    xbmcplugin.setPluginCategory(handle, title or data.get('title') or '')
    xbmcplugin.setContent(handle, 'seasons')

    items = []
    for season_entry in data.get('seasons') or []:
        season = season_entry['season']
        li = xbmcgui.ListItem(label=ADDON.getLocalizedString(30314) % season, offscreen=True)
        info = li.getVideoInfoTag()
        info.setMediaType('season')
        info.setSeason(int(season))
        if season_entry.get('overview'):
            info.setPlot(season_entry['overview'])
        if season_entry.get('poster_url'):
            li.setArt({'thumb': season_entry['poster_url'], 'poster': season_entry['poster_url']})
        url = navigation.build_watch_action_url(
            base_url, 'watch_show_episodes', tmdb_id=tmdb_id, season=season,
            title=title or data.get('title') or '', smedia=smedia or data.get('smedia') or '',
        )
        items.append((url, li, True))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=bool(items), cacheToDisc=False)


def _render_show_episodes(base_url, handle, params):
    """Ecran "Episodes" d'UNE saison precise - seul endroit ou l'episode
    reellement choisi devient connu. C'est ICI, au RENDU (jamais dans une
    action a part au clic - meme raison que pour les films dans
    lists_gui.py : un ecran relais separe a deja cause des problemes de
    pile de navigation Kodi cette meme session) qu'on seme la reprise pour
    CHAQUE episode qui en a une, avant de construire son lien direct vers
    vStream (adapter.episode_url()) - jamais l'inverse."""
    tmdb_id_raw = params.get('tmdb_id', '')
    season_raw = params.get('season', '')
    title = params.get('title', '')
    smedia = params.get('smedia') or None

    try:
        episodes = api_client.get_watch_progress_vstream_episodes(tmdb_id_raw, season_raw)
    except api_client.ApiError:
        xbmcgui.Dialog().notification(
            ADDON_NAME, ADDON.getLocalizedString(30012), xbmcgui.NOTIFICATION_ERROR, 5000,
        )
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    xbmcplugin.setPluginCategory(handle, '{0} - Saison {1}'.format(title, season_raw))
    xbmcplugin.setContent(handle, 'episodes')

    from resources.lib.vstream_adapter import VStreamPastebinAdapter
    adapter = VStreamPastebinAdapter()

    items = []
    for entry in episodes:
        episode = entry.get('episode')
        progress = entry.get('progress')
        if progress and progress.get('resume_key'):
            vstream_db.seed_resume(progress['resume_key'], progress['position'], progress['duration'])

        label = ADDON.getLocalizedString(30315) % episode
        if entry.get('name'):
            label += ' - {0}'.format(entry['name'])
        li = xbmcgui.ListItem(label=label, offscreen=True)
        info = li.getVideoInfoTag()
        info.setMediaType('episode')
        info.setEpisode(int(episode))
        if entry.get('overview'):
            info.setPlot(entry['overview'])
        if entry.get('poster_url'):
            li.setArt({'thumb': entry['poster_url'], 'poster': entry['poster_url']})
        if progress:
            info.setResumePoint(float(progress['position']), float(progress['duration']))
        url = adapter.episode_url(tmdb_id_raw, season_raw, episode, title=title, smedia=smedia)
        items.append((url, li, True))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=bool(items), cacheToDisc=False)


def _add_remove_context_item(list_item, base_url, entry, watch_progress_info):
    if watch_progress_info.get('source') == 'vstream':
        poster = entry.get('poster') or {}
        tmdb_id = poster.get('tmdb_id')
        season, episode = poster.get('season'), poster.get('episode')
        if season is not None and episode is not None:
            url = navigation.build_watch_action_url(
                base_url, 'watch_clear', source='vstream', tmdb_id=tmdb_id, season=season, episode=episode,
            )
        else:
            url = navigation.build_watch_action_url(base_url, 'watch_clear', source='vstream', tmdb_id=tmdb_id)
    else:
        url = navigation.build_watch_action_url(base_url, 'watch_clear', path=entry.get('path'))
    list_item.addContextMenuItems([
        (ADDON.getLocalizedString(30256), 'RunPlugin({0})'.format(url)),
        navigation.build_refresh_context_item(base_url),
    ])
