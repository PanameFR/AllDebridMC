# -*- coding: utf-8 -*-
"""Reprise de lecture synchronisée entre appareils Kodi, via le serveur
(watch_progress.py côté Pi) - et écrans "En cours"/"Historique", pour le
contenu du MediaCenter ET pour le contenu Pastebin (résolu et lu
directement, voir pastebin_playback.py - étapes 1/2 du chantier de
suppression de vStream).

Suivi de lecture MediaCenter (locale) : pas de service.py séparé pour
cette partie. main.py appelle juste navigation.route(...) puis termine -
rien n'oblige le script à revenir vite après xbmcplugin.setResolvedUrl()
(qui débloque immédiatement le lecteur Kodi ; le timeout de résolution ne
s'applique qu'à la phase AVANT cet appel). track_playback() est donc
appelée à la suite, dans le même script, et bloque jusqu'à la fin de la
lecture - pattern réel, déjà utilisé par des addons de scrobbling Kodi.

Suivi de lecture Pastebin (films ET épisodes, précisément) : même
principe, track_playback_episode()/report_vstream() appelés dans le même
script que play_pastebin_movie()/play_pastebin_episode() (voir
navigation.py), dans un thread démon pour ne jamais bloquer le retour de
l'action RunPlugin. Le suffixe "vstream" de ces fonctions (report_vstream,
get_watch_progress_vstream, post_watch_progress_vstream...) est un nom
historique - vStream n'est plus impliqué du tout depuis les étapes 1/2 du
chantier de suppression de vStream, le contenu vient entièrement de la
source Pastebin résolue directement. Jamais renommé depuis (identique
côté serveur, source de vérité partagée) pour ne pas invalider les
entrées déjà stockées.

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

from resources.lib import api_client, navigation

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

def maybe_apply_resume(info, relative_path, title, list_item=None):
    """list_item : optionnel, UNIQUEMENT necessaire quand la lecture demarre
    via xbmc.Player().play() (jamais setResolvedUrl - voir
    play_pastebin_movie/play_pastebin_episode). Constate en conditions
    reelles : VideoInfoTag.setResumePoint() est bien lu par Kodi pour la
    reprise NATIVE d'un item resolu via setResolvedUrl/la bibliotheque,
    mais totalement ignore par Player().play() - la video repart de zero
    malgre "Reprendre" accepte. Seule la propriete ListItem "StartOffset"
    (en secondes, chaine) fait reellement seeker Player().play() au bon
    endroit."""
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
        if list_item is not None:
            list_item.setProperty('StartOffset', str(position))
    else:
        try:
            api_client.clear_watch_progress(relative_path)
        except api_client.ApiError:
            pass


def maybe_apply_resume_episode(info, tmdb_id, season, episode, title, list_item=None):
    """Etape 2 du chantier de suppression de vStream : meme dialogue que
    maybe_apply_resume, sur l'identite tmdb_id/saison/episode (deja precise
    cote serveur, voir get_watch_progress_vstream) plutot qu'un chemin -
    appelee depuis navigation.py::play_pastebin_episode, juste avant
    xbmc.Player().play(). list_item : voir la docstring de maybe_apply_resume
    (StartOffset, indispensable pour que Player().play() reprenne reellement)."""
    if not enabled():
        return

    try:
        progress = api_client.get_watch_progress_vstream(int(tmdb_id), season=int(season), episode=int(episode))
    except (api_client.ApiError, TypeError, ValueError):
        return

    if not progress:
        return

    position, duration = progress.get('position'), progress.get('duration')
    if not position or not duration:
        return

    device = progress.get('device') or '?'
    message = ADDON.getLocalizedString(30253).format(device, _format_time(position))

    resume = xbmcgui.Dialog().yesno(
        heading=title or ADDON.getLocalizedString(30252),
        message=message,
        nolabel=ADDON.getLocalizedString(30255),
        yeslabel=ADDON.getLocalizedString(30254),
    )

    if resume:
        info.setResumePoint(float(position), float(duration))
        if list_item is not None:
            list_item.setProperty('StartOffset', str(position))
    else:
        try:
            api_client.clear_watch_progress_vstream(int(tmdb_id), season=int(season), episode=int(episode))
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


def _track_playback(report_fn):
    """Commun a track_playback/track_playback_episode : bloque jusqu'a la
    fin de la lecture en cours (voir docstring de tete de module), rapporte
    via report_fn(position, duration, device) - jamais de callback
    xbmc.Player (onAVStarted/onPlayBackStopped), sondage direct comme
    partout ailleurs dans ce module."""
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
        report_fn(last_position, last_duration, device)

    if last_duration:
        report_fn(last_position, last_duration, device)


def track_playback(relative_path):
    if not relative_path or not enabled():
        return
    _track_playback(lambda position, duration, device: _report(relative_path, position, duration, device))


def track_playback_episode(tmdb_id, season, episode):
    """Etape 2 du chantier de suppression de vStream : meme suivi que
    track_playback, mais rapporte par identite tmdb_id/saison/episode
    (report_vstream, deja precise - voir play_pastebin_episode) plutot que
    par chemin."""
    if not enabled():
        return
    _track_playback(
        lambda position, duration, device: report_vstream(
            tmdb_id, position, duration, device, season=season, episode=episode,
        )
    )


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
    title = params.get('title', '')
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
    # Confirmation explicite du succes (jamais affichee avant) : voir
    # docstring de _add_remove_context_item pour le pourquoi - le seul
    # retour visuel fiable tant qu'un widget d'accueil ne se rafraichit pas
    # forcement tout de suite.
    xbmcgui.Dialog().notification(
        ADDON_NAME,
        ADDON.getLocalizedString(30350).format(title) if title else ADDON.getLocalizedString(30256),
        xbmcgui.NOTIFICATION_INFO, 3000,
    )
    xbmc.executebuiltin('Container.Refresh')


def _render_list(base_url, handle, action, params):
    status = _STATUS_BY_ACTION.get(action)
    if status is None:
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    # Categorie (Films/Series/Documentaires/... ou "Autres") - s'applique
    # de la meme facon a "En cours" et a "Historique", tous deux scindes
    # par categorie. Absent = toutes categories confondues.
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
        category_label = navigation.watch_category_label(category)
        if category_label:
            label = '%s - %s' % (label, category_label)
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
    """ListItem pour un film OU une SERIE suivi (jamais un episode precis -
    voir docstring en tete de module) - jamais navigation.build_list_item,
    qui suppose un chemin local (entry['path'] est None ici). Nom du module
    ("vstream") historique - le contenu vient de la source Pastebin,
    resolu directement (etapes 1/2 du chantier de suppression de vStream),
    jamais vStream lui-meme depuis ce point.

    Film : resolution directe (action play_pastebin_movie, voir
    pastebin_playback.py) - meme chemin que lists_gui.render_list().

    Serie : cible = notre propre ecran Saisons (action watch_show_seasons)
    - l'episode reel n'est connu qu'au clic sur un episode precis (voir
    _render_show_episodes)."""
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
        is_folder = True
    else:
        url = navigation.build_watch_action_url(
            base_url, 'play_pastebin_movie', tmdb_id=tmdb_id, title=title, thumb=poster.get('poster_url') or '',
        )
        is_folder = False
    return url, list_item, is_folder


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
    """Ecran "Episodes" d'UNE saison precise. Chaque item pointe vers
    l'action play_pastebin_episode (RunPlugin, resolution directe - voir
    navigation.py) : plus de reprise a semer dans une base tierce, notre
    propre dialogue (maybe_apply_resume_episode, precis par episode cote
    serveur) suffit desormais seul.

    Transmet aussi l'episode SUIVANT (dans cette meme saison, meme
    limite que build_list_item pour le local - jamais entre deux saisons)
    pour l'enchainement (voir navigation.py::play_pastebin_episode) -
    jusqu'ici uniquement cable pour la bibliotheque locale, jamais pour
    Pastebin."""
    tmdb_id_raw = params.get('tmdb_id', '')
    season_raw = params.get('season', '')
    title = params.get('title', '')

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

    items = []
    for i, entry in enumerate(episodes):
        episode = entry.get('episode')
        progress = entry.get('progress')

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

        url_params = dict(
            tmdb_id=tmdb_id_raw, season=season_raw, episode=episode,
            title=title, thumb=entry.get('poster_url') or '',
        )
        next_entry = episodes[i + 1] if i + 1 < len(episodes) else None
        if next_entry:
            next_episode = next_entry.get('episode')
            next_label = ADDON.getLocalizedString(30315) % next_episode
            if next_entry.get('name'):
                next_label += ' - {0}'.format(next_entry['name'])
            url_params.update(
                next_season=season_raw, next_episode=next_episode,
                next_title=next_label, next_thumb=next_entry.get('poster_url') or '',
            )
        url = navigation.build_watch_action_url(base_url, 'play_pastebin_episode', **url_params)
        items.append((url, li, False))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=bool(items), cacheToDisc=False)


def _add_remove_context_item(list_item, base_url, entry, watch_progress_info):
    # Titre transmis en parametre d'URL (pas relu depuis le serveur au
    # moment du clic) : sert uniquement a personnaliser la notification de
    # succes dans _action_clear() - un widget d'accueil (Arctic Horizon 2,
    # voir sa discussion) ne se rafraichit pas forcement tout de suite,
    # cette notification reste alors la seule confirmation visible que le
    # retrait a bien fonctionne cote serveur.
    poster = entry.get('poster') or {}
    title = poster.get('title') or entry.get('name') or ''
    if watch_progress_info.get('source') == 'vstream':
        tmdb_id = poster.get('tmdb_id')
        season, episode = poster.get('season'), poster.get('episode')
        if season is not None and episode is not None:
            url = navigation.build_watch_action_url(
                base_url, 'watch_clear', source='vstream', tmdb_id=tmdb_id,
                season=season, episode=episode, title=title,
            )
        else:
            url = navigation.build_watch_action_url(
                base_url, 'watch_clear', source='vstream', tmdb_id=tmdb_id, title=title,
            )
    else:
        url = navigation.build_watch_action_url(base_url, 'watch_clear', path=entry.get('path'), title=title)
    list_item.addContextMenuItems([
        (ADDON.getLocalizedString(30256), 'RunPlugin({0})'.format(url)),
        navigation.build_refresh_context_item(base_url),
    ])
