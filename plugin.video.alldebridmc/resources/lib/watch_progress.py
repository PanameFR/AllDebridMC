# -*- coding: utf-8 -*-
"""Reprise de lecture synchronisée entre appareils Kodi, via le serveur
(watch_progress.py côté Pi) - et écrans "En cours"/"Historique" pour le
contenu du MediaCenter (équivalent, pour notre addon, de ce que vStream
propose déjà pour son propre contenu - vStream n'est ni modifié ni
intégré, on construit juste le même genre d'écran chez nous).

Suivi de lecture : pas de service.py séparé. main.py appelle juste
navigation.route(...) puis termine - rien n'oblige le script à revenir
vite après xbmcplugin.setResolvedUrl() (qui débloque immédiatement le
lecteur Kodi ; le timeout de résolution ne s'applique qu'à la phase AVANT
cet appel). track_playback() est donc appelée à la suite, dans le même
script, et bloque jusqu'à la fin de la lecture - pattern réel, déjà
utilisé par des addons de scrobbling Kodi. Un service.py apporterait plus
de robustesse théorique mais demanderait un nouveau point d'extension et
un filtrage par chemin SMB (un service voit toute la lecture Kodi, y
compris celle de vStream) ; pas nécessaire ici, le scope est déjà limité
à la lecture qu'on a nous-mêmes résolue.

Import de navigation en tête (build_list_item) : c'est pour ça que
navigation.py importe CE module en différé (voir route()/play_item()) et
jamais l'inverse, pour éviter un cycle.
"""
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

from resources.lib import api_client, navigation

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo('name')

HEARTBEAT_INTERVAL = 20  # secondes entre deux rapports pendant la lecture
START_TIMEOUT = 45  # secondes max d'attente que la lecture demarre vraiment

_STATUS_BY_ACTION = {'watch_in_progress': 'in_progress', 'watch_history': 'watched'}
_LABEL_BY_ACTION = {'watch_in_progress': 30250, 'watch_history': 30251}


def _enabled():
    try:
        return ADDON.getSettingBool('watch_progress_enabled')
    except (AttributeError, TypeError):
        return True


def _device_name():
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


def track_playback(relative_path):
    if not relative_path or not _enabled():
        return

    player = _ProgressPlayer()
    monitor = xbmc.Monitor()
    device = _device_name()

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

    _render_list(base_url, handle, action)


def _action_clear(params):
    relative_path = params.get('path', '')
    if not relative_path:
        return
    try:
        api_client.clear_watch_progress(relative_path)
    except api_client.ApiError:
        xbmcgui.Dialog().notification(
            ADDON_NAME, ADDON.getLocalizedString(30012), xbmcgui.NOTIFICATION_ERROR, 5000,
        )
        return
    xbmc.executebuiltin('Container.Refresh')


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
        url, list_item, is_folder = navigation.build_list_item(base_url, entry)
        _apply_visuals(list_item, entry.get('watch_progress'), watched=(status == 'watched'))
        _add_remove_context_item(list_item, base_url, entry['path'])
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


def _add_remove_context_item(list_item, base_url, relative_path):
    url = navigation.build_watch_clear_url(base_url, relative_path)
    list_item.addContextMenuItems([
        (ADDON.getLocalizedString(30256), 'RunPlugin({0})'.format(url)),
    ])
