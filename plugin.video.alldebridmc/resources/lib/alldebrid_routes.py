# -*- coding: utf-8 -*-
"""Étape 4 du chantier de suppression de vStream : menu "AllDebrid" de
l'addon - liens sauvegardés sur le compte (API v4 /v4/user/links, exposés
côté serveur par alldebrid_routes.py), chacun jouable directement
(résolution à la volée au clic, jamais en listant) et supprimable. Même
convention que lists_routes.py (dispatch + actions), à plus petite échelle -
un seul écran, pas de sous-navigation.
"""
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

from resources.lib import api_client
from resources.lib import lists_dialogs as dialogs
from resources.lib import navigation

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo('name')

# Secondes entre deux nouvelles tentatives d'un lien "delayed" (AllDebrid le
# prépare encore côté hébergeur) - mêmes délais et même raison que
# pastebin_playback.py::_resolve_with_retry (poll borné côté CLIENT, jamais
# le worker gunicorn du serveur).
_RETRY_DELAYS_SECONDS = (2, 3, 5, 5, 5)


def _resolve_with_retry(link):
    info = api_client.alldebrid_resolve_link(link)
    for delay in _RETRY_DELAYS_SECONDS:
        if not info.get('delayed'):
            break
        xbmc.sleep(delay * 1000)
        info = api_client.alldebrid_resolve_link(link)
    return info if info.get('link') else None


def render_home(base_url, handle, params):
    try:
        links = api_client.alldebrid_saved_links()
    except api_client.ApiError as exc:
        navigation.handle_api_error(exc)
        links = []

    xbmcplugin.setPluginCategory(handle, ADDON.getLocalizedString(30356))
    xbmcplugin.setContent(handle, 'videos')

    items = []
    for entry in links:
        link = entry.get('link') or ''
        filename = entry.get('filename') or '?'
        label = '{0}   [COLOR grey]{1}[/COLOR]'.format(filename, entry.get('size_human') or '')

        li = xbmcgui.ListItem(label=label, offscreen=True)
        li.setArt({'icon': 'DefaultVideo.png'})
        info = li.getVideoInfoTag()
        info.setTitle(filename)

        # RunPlugin implicite (jamais IsPlayable) : la resolution peut
        # echouer ou etre "delayed" (voir _resolve_with_retry), meme raison
        # que navigation.py::play_pastebin_movie - un contexte de resolution
        # de lecture afficherait le dialogue natif "Echec de lecture" de
        # Kodi au lieu d'une simple notification.
        play_url = navigation.build_watch_action_url(base_url, 'alldebrid_play', link=link, filename=filename)
        delete_url = navigation.build_watch_action_url(base_url, 'alldebrid_delete', link=link, filename=filename)
        li.addContextMenuItems([(ADDON.getLocalizedString(30367), 'RunPlugin({0})'.format(delete_url))])

        items.append((play_url, li, False))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=bool(items), cacheToDisc=False)


def action_play(base_url, params):
    link = params.get('link', '')
    filename = params.get('filename', '') or ADDON_NAME
    if not link:
        return

    try:
        resolved = _resolve_with_retry(link)
    except api_client.ApiError as exc:
        navigation.handle_api_error(exc)
        return

    if not resolved:
        xbmcgui.Dialog().notification(
            ADDON_NAME, ADDON.getLocalizedString(30371), xbmcgui.NOTIFICATION_INFO, 5000,
        )
        return

    list_item = xbmcgui.ListItem(label=filename, offscreen=True)
    info = list_item.getVideoInfoTag()
    info.setTitle(filename)
    list_item.setPath(resolved['link'])
    xbmc.Player().play(resolved['link'], list_item)


def action_delete(base_url, params):
    link = params.get('link', '')
    filename = params.get('filename', '')
    if not link:
        return

    if dialogs.confirm(ADDON.getLocalizedString(30367), ADDON.getLocalizedString(30368).format(filename)):
        try:
            api_client.alldebrid_delete_link(link)
        except api_client.ApiError as exc:
            navigation.handle_api_error(exc)
            return
        dialogs.notify(ADDON_NAME, ADDON.getLocalizedString(30369))
        xbmc.executebuiltin('Container.Refresh')


# Actions qui rendent un répertoire : (base_url, handle, params) -> None
_RENDER_ACTIONS = {
    'alldebrid_home': render_home,
}

# Actions qui ne rendent pas de répertoire (RunPlugin) : (base_url, params) -> None
_RUN_ACTIONS = {
    'alldebrid_play': action_play,
    'alldebrid_delete': action_delete,
}


def dispatch(base_url, handle, params):
    action = params.get('action')

    render_handler = _RENDER_ACTIONS.get(action)
    if render_handler is not None:
        render_handler(base_url, handle, params)
        return

    run_handler = _RUN_ACTIONS.get(action)
    if run_handler is not None:
        run_handler(base_url, params)
        xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)
        return

    xbmc.log('[alldebridmc] alldebrid_routes: unknown action %r' % action, xbmc.LOGWARNING)
    xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)
