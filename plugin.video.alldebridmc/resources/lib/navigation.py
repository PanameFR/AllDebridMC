# -*- coding: utf-8 -*-
"""Routage plugin:// et construction des listes Kodi.

Toutes les métadonnées (jaquettes, saisons, épisodes) viennent déjà
enrichies par le serveur (api_client.browse) — ce module ne fait
qu'afficher ce qu'on lui donne, jamais de logique de correspondance TMDB
ici (elle vit uniquement côté outil, pour rester fusionnel avec lui).
"""
import urllib.parse

import xbmcaddon
import xbmcgui
import xbmcplugin

from resources.lib import api_client, playback

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo('name')


def route(base_url, handle, params):
    action = params.get('action', 'browse')

    if action == 'browse':
        list_directory(base_url, handle, params.get('path', ''))
    elif action == 'play':
        play_item(handle, params)
    elif action == 'movie_info':
        show_movie_info(handle, params)
    elif action == 'test_connection':
        test_connection(handle)
    else:
        xbmcplugin.endOfDirectory(handle, succeeded=False)


def _build_url(base_url, **kwargs):
    return base_url + '?' + urllib.parse.urlencode(kwargs)


def _notify(message, error=False):
    icon = xbmcgui.NOTIFICATION_ERROR if error else xbmcgui.NOTIFICATION_INFO
    xbmcgui.Dialog().notification(ADDON_NAME, message, icon, 5000)


def _handle_api_error(exc):
    if isinstance(exc, api_client.AuthError):
        _notify(ADDON.getLocalizedString(30013), error=True)
    else:
        _notify(ADDON.getLocalizedString(30012), error=True)


# ---- browse ---------------------------------------------------------------

def list_directory(base_url, handle, path):
    try:
        data = api_client.browse(path)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    entries = [e for e in data.get('entries', []) if e.get('is_dir') or e.get('is_video')]

    xbmcplugin.setPluginCategory(handle, _category_label(data))
    xbmcplugin.setContent(handle, _guess_content(entries))

    items = [_build_list_item(base_url, entry) for entry in entries]
    xbmcplugin.addDirectoryItems(handle, items, len(items))
    # Le serveur trie déjà correctement (SxxExx, alphabétique) : on garde
    # cet ordre plutôt que de proposer le tri natif de Kodi.
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=True, updateListing=False, cacheToDisc=False)


def _category_label(data):
    breadcrumb = data.get('breadcrumb') or []
    return breadcrumb[-1]['name'] if breadcrumb else ADDON_NAME


def _guess_content(entries):
    if any(e.get('episode_info') for e in entries):
        return 'episodes'
    if any(e.get('season_info') for e in entries):
        return 'seasons'
    if any((e.get('poster') or {}).get('media_type') == 'tv' for e in entries):
        return 'tvshows'
    if any((e.get('poster') or {}).get('media_type') == 'movie' for e in entries):
        return 'movies'
    return 'files'


def _entry_title(entry):
    ep = entry.get('episode_info')
    if ep and ep.get('name'):
        se, epn = ep.get('season_number'), ep.get('episode_number')
        prefix = 'S{0:02d}E{1:02d} - '.format(se, epn) if se is not None and epn is not None else ''
        return prefix + ep['name']

    season = entry.get('season_info')
    if season and season.get('name'):
        return season['name']

    poster = entry.get('poster')
    if poster and poster.get('title'):
        year = poster.get('year')
        return '{0} ({1})'.format(poster['title'], year) if year else poster['title']

    return entry.get('name', '?')


def _entry_art(entry):
    ep = entry.get('episode_info')
    if ep and ep.get('still_url'):
        return {'thumb': ep['still_url'], 'icon': ep['still_url']}

    season = entry.get('season_info')
    if season and season.get('poster_url'):
        return {'thumb': season['poster_url'], 'poster': season['poster_url']}

    poster = entry.get('poster')
    if poster and poster.get('poster_url'):
        return {'thumb': poster['poster_url'], 'poster': poster['poster_url']}

    return {}


def _apply_metadata(info, entry):
    poster = entry.get('poster')
    season = entry.get('season_info')
    ep = entry.get('episode_info')

    if ep:
        info.setMediaType('episode')
        if poster and poster.get('title'):
            info.setTvShowTitle(poster['title'])
        if ep.get('season_number') is not None:
            info.setSeason(ep['season_number'])
        if ep.get('episode_number') is not None:
            info.setEpisode(ep['episode_number'])
        if ep.get('overview'):
            info.setPlot(ep['overview'])
        if ep.get('air_date'):
            info.setFirstAired(ep['air_date'])
            info.setPremiered(ep['air_date'])
        if ep.get('runtime'):
            info.setDuration(int(ep['runtime']) * 60)  # TMDB : minutes -> Kodi attend des secondes
        if ep.get('vote_average'):
            info.setRating(float(ep['vote_average']))
    elif season:
        info.setMediaType('season')
        if season.get('season_number') is not None:
            info.setSeason(season['season_number'])
        if season.get('air_date'):
            info.setPremiered(season['air_date'])
    elif poster:
        info.setMediaType('movie' if poster.get('media_type') == 'movie' else 'tvshow')
        if poster.get('year'):
            info.setYear(int(poster['year']))


def _build_list_item(base_url, entry):
    title = _entry_title(entry)
    list_item = xbmcgui.ListItem(label=title, offscreen=True)

    art = _entry_art(entry)
    if art:
        list_item.setArt(art)

    info = list_item.getVideoInfoTag()
    info.setTitle(title)
    _apply_metadata(info, entry)

    poster = entry.get('poster') or {}
    if poster.get('media_type') == 'movie' and poster.get('tmdb_id'):
        info_url = _build_url(
            base_url, action='movie_info', tmdb_id=poster['tmdb_id'],
            title=title, thumb=art.get('thumb', ''),
        )
        list_item.addContextMenuItems([
            (ADDON.getLocalizedString(30014), 'RunPlugin({0})'.format(info_url))
        ])

    if entry.get('is_dir'):
        url = _build_url(base_url, action='browse', path=entry['path'])
        return url, list_item, True

    list_item.setProperty('IsPlayable', 'true')
    play_params = {
        'action': 'play', 'path': entry['path'], 'title': title,
        'thumb': art.get('thumb', ''),
    }
    ep = entry.get('episode_info')
    if ep:
        if ep.get('overview'):
            play_params['plot'] = ep['overview']
        if ep.get('season_number') is not None:
            play_params['season'] = ep['season_number']
        if ep.get('episode_number') is not None:
            play_params['episode'] = ep['episode_number']
        if ep.get('air_date'):
            play_params['aired'] = ep['air_date']
        if ep.get('runtime'):
            play_params['duration'] = ep['runtime']
        if ep.get('vote_average'):
            play_params['rating'] = ep['vote_average']
    url = _build_url(base_url, **play_params)
    return url, list_item, False


# ---- play -------------------------------------------------------------

def play_item(handle, params):
    title = params.get('title', '')
    list_item = xbmcgui.ListItem(label=title, offscreen=True)

    thumb = params.get('thumb')
    if thumb:
        list_item.setArt({'thumb': thumb, 'icon': thumb})

    info = list_item.getVideoInfoTag()
    if title:
        info.setTitle(title)
    if params.get('plot'):
        info.setPlot(params['plot'])
    if params.get('season'):
        info.setSeason(int(params['season']))
    if params.get('episode'):
        info.setEpisode(int(params['episode']))
    if params.get('aired'):
        info.setFirstAired(params['aired'])
    if params.get('duration'):
        info.setDuration(int(float(params['duration'])) * 60)  # minutes -> secondes
    if params.get('rating'):
        info.setRating(float(params['rating']))

    list_item.setPath(playback.build_smb_url(params.get('path', '')))
    xbmcplugin.setResolvedUrl(handle, True, list_item)


# ---- infos film à la demande -------------------------------------------

def show_movie_info(handle, params):
    tmdb_id = params.get('tmdb_id')

    try:
        data = api_client.movie_info(tmdb_id)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    list_item = xbmcgui.ListItem(label=params.get('title', ''), offscreen=True)
    thumb = params.get('thumb')
    if thumb:
        list_item.setArt({'thumb': thumb, 'poster': thumb})

    info = list_item.getVideoInfoTag()
    info.setMediaType('movie')
    if params.get('title'):
        info.setTitle(params['title'])
    if data.get('overview'):
        info.setPlot(data['overview'])
    if data.get('genres'):
        info.setGenres(data['genres'])
    if data.get('vote_average'):
        info.setRating(float(data['vote_average']))
    if data.get('runtime'):
        info.setDuration(int(data['runtime']) * 60)  # minutes -> secondes
    if data.get('release_date'):
        info.setPremiered(data['release_date'])

    xbmcgui.Dialog().info(list_item)
    xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)


# ---- bouton "Tester la connexion" des réglages -------------------------

def test_connection(handle):
    try:
        api_client.ping()
    except api_client.AuthError:
        _notify(ADDON.getLocalizedString(30013), error=True)
    except api_client.ApiError:
        _notify(ADDON.getLocalizedString(30012), error=True)
    else:
        _notify(ADDON.getLocalizedString(30011), error=False)
    xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)
