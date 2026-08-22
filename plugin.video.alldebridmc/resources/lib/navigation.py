# -*- coding: utf-8 -*-
"""Routage plugin:// et construction des listes Kodi.

Toutes les métadonnées (jaquettes, saisons, épisodes) viennent déjà
enrichies par le serveur (api_client.browse) — ce module ne fait
qu'afficher ce qu'on lui donne, jamais de logique de correspondance TMDB
ici (elle vit uniquement côté outil, pour rester fusionnel avec lui).
"""
import urllib.parse
from datetime import datetime

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

from resources.lib import api_client, kodi_backup, playback, upnext

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo('name')


def route(base_url, handle, params):
    action = params.get('action', 'root')

    if action.startswith('lists_'):
        # Fonctionnalite Listes (integree depuis plugin.video.vstreamlists) :
        # entierement geree dans son propre module, navigation.py ne fait
        # que lui deleguer - voir lists_routes.py.
        from resources.lib import lists_routes
        lists_routes.dispatch(base_url, handle, params)
        return

    if action == 'watch_home':
        # Simple menu de navigation (En cours/Historique) - pas de donnees
        # a aller chercher, reste ici plutot que dans watch_progress.py.
        _list_watch_menu(base_url, handle)
        return

    if action.startswith('watch_'):
        # Reprise de lecture synchronisee : ecrans "En cours"/"Historique",
        # geres dans leur propre module - meme raison que l'import differe
        # ci-dessus (watch_progress importe navigation en tete, un import
        # en tete ici creerait un import circulaire).
        from resources.lib import watch_progress
        watch_progress.dispatch(base_url, handle, params)
        return

    if action == 'root':
        _list_root_menu(base_url, handle)
    elif action == 'browse':
        list_directory(base_url, handle, params.get('path', ''))
    elif action == 'play':
        play_item(base_url, handle, params)
    elif action == 'movie_info':
        show_movie_info(handle, params)
    elif action == 'test_connection':
        test_connection(handle)
    elif action == 'refresh_all':
        run_refresh_action(handle)
    elif action == 'open_settings':
        run_open_settings(handle)
    elif action == 'backup_home':
        _list_backup_menu(base_url, handle)
    elif action == 'backup_run':
        _run_backup_action(handle)
    elif action == 'backup_restore':
        _run_restore_action(handle, params.get('name', ''))
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


def _watch_progress_enabled():
    # Meme garde defensive que _show_count() dans lists_routes.py : un
    # reglage tout juste ajoute par une mise a jour peut ne pas encore
    # exister pour une install existante - ne jamais casser le menu
    # racine pour ca.
    try:
        return ADDON.getSettingBool('watch_progress_enabled')
    except (AttributeError, TypeError):
        return True


# ---- menu racine ------------------------------------------------------

def _list_root_menu(base_url, handle):
    """Racine de l'addon : uniquement des dossiers synthetiques (jamais
    d'appel serveur ici) - Medias (la vraie arborescence du serveur,
    anciennement affichee directement a la racine), Mes Listes, et
    Visionnage (En cours/Historique) si active."""
    xbmcplugin.setPluginCategory(handle, ADDON_NAME)
    xbmcplugin.setContent(handle, 'files')

    items = [_build_media_menu_item(base_url), _build_lists_menu_item(base_url)]
    if _watch_progress_enabled():
        items.append(_build_watch_home_menu_item(base_url))
    items.append(_build_backup_menu_item(base_url))
    items.append(_build_refresh_menu_item(base_url))
    items.append(_build_settings_menu_item(base_url))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


def _list_watch_menu(base_url, handle):
    """Sous-menu Visionnage : En cours / Historique - simple aiguillage,
    aucune donnee a aller chercher ici (voir watch_progress.dispatch)."""
    xbmcplugin.setPluginCategory(handle, ADDON.getLocalizedString(30260))
    xbmcplugin.setContent(handle, 'files')

    items = [
        _build_watch_menu_item(base_url, 'watch_in_progress', 30250, 'DefaultInProgressShows.png'),
        _build_watch_menu_item(base_url, 'watch_history', 30251, 'DefaultRecentlyAddedEpisodes.png'),
    ]
    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


def _build_media_menu_item(base_url):
    list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(30259), offscreen=True)
    list_item.setArt({'icon': 'DefaultHardDisk.png'})
    url = _build_url(base_url, action='browse', path='')
    return url, list_item, True


def _build_lists_menu_item(base_url):
    list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(30150), offscreen=True)
    list_item.setArt({'icon': 'DefaultVideoPlaylists.png'})
    url = _build_url(base_url, action='lists_home')
    return url, list_item, True


def _build_watch_home_menu_item(base_url):
    list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(30260), offscreen=True)
    # Icone differente de son propre enfant "En cours" (DefaultInProgressShows.png)
    # pour eviter d'avoir deux fois la meme icone a un niveau d'ecart.
    list_item.setArt({'icon': 'DefaultFavourites.png'})
    url = _build_url(base_url, action='watch_home')
    return url, list_item, True


def _build_watch_menu_item(base_url, action, label_id, icon):
    list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(label_id), offscreen=True)
    list_item.setArt({'icon': icon})
    return _build_url(base_url, action=action), list_item, True


def build_watch_action_url(base_url, action, **params):
    return _build_url(base_url, action=action, **params)


def _build_backup_menu_item(base_url):
    list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(30300), offscreen=True)
    # Icone differente des 3 autres items racine (HardDisk/VideoPlaylists/
    # Favourites) - meme logique que pour Visionnage/En cours plus haut.
    list_item.setArt({'icon': 'DefaultNetwork.png'})
    url = _build_url(base_url, action='backup_home')
    return url, list_item, True


def _build_refresh_menu_item(base_url):
    """Action directe (RunPlugin, jamais une vraie navigation - meme
    convention que test_connection), pas un sous-dossier : Container.Refresh
    rafraichit le conteneur ACTIF au moment du clic. Depuis ce menu racine,
    ca ne rafraichit que lui-meme (peu utile) - le vrai interet est de
    pouvoir pointer un raccourci de skin directement sur cette action (ou
    de l'utiliser via son item de menu contextuel, voir lists_gui.py/
    watch_progress.py) pendant qu'on est deja sur l'ecran a rafraichir."""
    list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(30316), offscreen=True)
    list_item.setArt({'icon': 'DefaultAddonsUpdates.png'})
    url = _build_url(base_url, action='refresh_all')
    return url, list_item, False


def _build_settings_menu_item(base_url):
    """Action directe (RunPlugin), ouvre les reglages de CET addon
    (Addon.OpenSettings, jamais un sous-dossier) - pour ne pas dependre de
    l'ecran "Gerer les extensions" de Kodi pour y acceder."""
    list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(30320), offscreen=True)
    list_item.setArt({'icon': 'DefaultAddonProgram.png'})
    url = _build_url(base_url, action='open_settings')
    return url, list_item, False


# ---- sauvegarde/restauration Kodi --------------------------------------

def _list_backup_menu(base_url, handle):
    """Dossier Sauvegarde : en premier une action "Sauvegarder maintenant",
    puis une entree par sauvegarde deja presente sur le serveur (voir
    kodi_backup.list_backups) - cliquer une entree lance sa restauration.
    Jamais de sous-dossier ici, tout est action directe (comme
    test_connection), pas une vraie navigation."""
    xbmcplugin.setPluginCategory(handle, ADDON.getLocalizedString(30300))
    xbmcplugin.setContent(handle, 'files')

    items = [_build_backup_run_item(base_url)]

    try:
        backups = kodi_backup.list_backups()
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        backups = []

    for backup in backups:
        items.append(_build_backup_restore_item(base_url, backup))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


def _build_backup_run_item(base_url):
    list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(30308), offscreen=True)
    list_item.setArt({'icon': 'DefaultAddSource.png'})
    url = _build_url(base_url, action='backup_run')
    return url, list_item, False


def _build_backup_restore_item(base_url, backup):
    label = '{0} — {1} — {2}'.format(
        backup.get('device') or '?',
        _format_backup_date(backup.get('created_at')),
        backup.get('size_human') or '',
    )
    list_item = xbmcgui.ListItem(label=label, offscreen=True)
    list_item.setArt({'icon': 'DefaultAddonsUpdates.png'})
    url = _build_url(base_url, action='backup_restore', name=backup.get('name', ''))
    return url, list_item, False


def _format_backup_date(iso_string):
    if not iso_string:
        return '?'
    try:
        parsed = datetime.fromisoformat(iso_string)
    except ValueError:
        return iso_string
    return parsed.strftime('%d/%m/%Y %H:%M')


def _run_backup_action(handle):
    confirmed = xbmcgui.Dialog().yesno(
        ADDON.getLocalizedString(30300), ADDON.getLocalizedString(30309),
    )
    if confirmed:
        progress = xbmcgui.DialogProgress()
        success, error = kodi_backup.run_backup(progress)
        if success:
            _notify(ADDON.getLocalizedString(30310), error=False)
        elif error:
            _notify(error, error=True)
    xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)


def _run_restore_action(handle, backup_name):
    if backup_name:
        confirmed = xbmcgui.Dialog().yesno(
            ADDON.getLocalizedString(30300), ADDON.getLocalizedString(30311),
        )
        if confirmed:
            progress = xbmcgui.DialogProgress()
            success, error = kodi_backup.run_restore(progress, backup_name)
            if success:
                if xbmcgui.Dialog().yesno(
                    ADDON.getLocalizedString(30312), ADDON.getLocalizedString(30313)
                ):
                    xbmc.executebuiltin('Quit')
            elif error:
                _notify(error, error=True)
    xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)


# ---- browse (Medias) ----------------------------------------------------

def list_directory(base_url, handle, path):
    try:
        data = api_client.browse(path)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    entries = [e for e in data.get('entries', []) if e.get('is_dir') or e.get('is_video')]

    xbmcplugin.setPluginCategory(handle, _category_label(data, path))
    xbmcplugin.setContent(handle, _guess_content(entries))

    items = [
        build_list_item(base_url, entry, entries[i + 1] if i + 1 < len(entries) else None)
        for i, entry in enumerate(entries)
    ]
    xbmcplugin.addDirectoryItems(handle, items, len(items))
    # Le serveur trie déjà correctement (SxxExx, alphabétique) : on garde
    # cet ordre plutôt que de proposer le tri natif de Kodi.
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=True, updateListing=False, cacheToDisc=False)


def _category_label(data, path):
    if not path:
        # Racine du vrai serveur (ecran "Medias") - le fil d'Ariane du
        # serveur est vide a ce niveau, jamais tres parlant comme categorie.
        return ADDON.getLocalizedString(30259)
    breadcrumb = data.get('breadcrumb') or []
    return breadcrumb[-1]['name'] if breadcrumb else ADDON_NAME


def _guess_content(entries):
    if any(e.get('episode_info') for e in entries):
        return 'episodes'
    if any(e.get('season_info') for e in entries):
        # 'seasons' n'est pas un type de contenu officiellement reconnu par
        # Kodi (contrairement à movies/tvshows/episodes) — le skin Estuary
        # n'affichait alors pas le résumé des saisons dans le panneau
        # d'info, même si la donnée était bien présente sur le ListItem
        # (confirmé en direct : setPlot()/getPlot() concordaient déjà).
        # 'tvshows' déclenche le même panneau d'info que pour les séries,
        # avec résumé, et convient tout aussi bien visuellement à une
        # liste de saisons (affiches + titre + résumé).
        return 'tvshows'
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
        if season.get('overview'):
            info.setPlot(season['overview'])
    elif poster:
        info.setMediaType('movie' if poster.get('media_type') == 'movie' else 'tvshow')
        if poster.get('year'):
            info.setYear(int(poster['year']))
        if poster.get('overview'):
            info.setPlot(poster['overview'])


def build_list_item(base_url, entry, next_entry=None):
    title = _entry_title(entry)
    list_item = xbmcgui.ListItem(label=title, offscreen=True)

    art = _entry_art(entry)
    if art:
        list_item.setArt(art)

    info = list_item.getVideoInfoTag()
    info.setTitle(title)
    _apply_metadata(info, entry)

    poster = entry.get('poster') or {}
    context_items = []
    if poster.get('media_type') == 'movie' and poster.get('tmdb_id'):
        info_url = _build_url(
            base_url, action='movie_info', tmdb_id=poster['tmdb_id'],
            title=title, thumb=art.get('thumb', ''),
        )
        context_items.append(
            (ADDON.getLocalizedString(30014), 'RunPlugin({0})'.format(info_url))
        )
    if poster.get('tmdb_id'):
        # Deja associe a une fiche TMDB (film - fichier ou dossier selon
        # l'organisation de la bibliotheque - ou racine de serie) : peut
        # etre relie a une liste. is_dir est transmis (pas utilise comme
        # condition : un film est parfois un fichier direct, parfois un
        # dossier) pour que la redirection sache plus tard si elle doit
        # ouvrir un dossier ou lancer la lecture directement (voir
        # lists_routes.action_add_local / lists_gui.render_list).
        add_to_list_url = _build_url(
            base_url, action='lists_add_local', path=entry['path'],
            tmdb_id=poster['tmdb_id'], media_type=poster.get('media_type'), title=title,
            is_dir='1' if entry.get('is_dir') else '0',
        )
        context_items.append(
            (ADDON.getLocalizedString(30151), 'RunPlugin({0})'.format(add_to_list_url))
        )
    if context_items:
        list_item.addContextMenuItems(context_items)

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
        if poster.get('title'):
            play_params['showtitle'] = poster['title']
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
        # UpNext (service.upnext) : episode suivant deja connu ici (meme
        # dossier de saison, deja trie SxxExx par le serveur) - transmis a
        # travers l'URL de lecture plutot que recalcule au moment de jouer,
        # pour eviter un aller-retour serveur supplementaire depuis
        # play_item(). Jamais envoye si l'entree suivante n'est pas un
        # episode (fin de saison).
        next_ep = (next_entry or {}).get('episode_info')
        if next_ep:
            play_params['next_path'] = next_entry['path']
            play_params['next_title'] = next_ep.get('name') or ''
            play_params['next_plot'] = next_ep.get('overview') or ''
            if next_ep.get('season_number') is not None:
                play_params['next_season'] = next_ep['season_number']
            if next_ep.get('episode_number') is not None:
                play_params['next_episode'] = next_ep['episode_number']
            next_thumb = (next_ep.get('still_url') or poster.get('poster_url') or '')
            if next_thumb:
                play_params['next_thumb'] = next_thumb
    url = _build_url(base_url, **play_params)
    return url, list_item, False


# ---- play -------------------------------------------------------------

def play_item(base_url, handle, params):
    title = params.get('title', '')
    relative_path = params.get('path', '')
    list_item = xbmcgui.ListItem(label=title, offscreen=True)

    thumb = params.get('thumb')
    if thumb:
        list_item.setArt({'thumb': thumb, 'icon': thumb})

    info = list_item.getVideoInfoTag()
    if title:
        info.setTitle(title)
    if params.get('showtitle'):
        info.setTvShowTitle(params['showtitle'])
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

    # Reprise de lecture synchronisee : import differe (meme raison que
    # pour lists_routes/watch_progress dans route() - le module importe
    # navigation en tete, un import en tete ici créerait un cycle).
    from resources.lib import watch_progress
    watch_progress.maybe_apply_resume(info, relative_path, title)

    list_item.setPath(playback.build_smb_url(relative_path))
    xbmcplugin.setResolvedUrl(handle, True, list_item)

    _notify_upnext(base_url, params)

    # Bloque jusqu'a la fin de la lecture pour suivre la progression - le
    # script du plugin n'est pas oblige de revenir vite apres
    # setResolvedUrl (voir le commentaire en tete de watch_progress.py).
    watch_progress.track_playback(relative_path)


def _notify_upnext(base_url, params):
    """Signale l'episode suivant a service.upnext (voir upnext.py) - rien
    n'est envoye si next_path est absent (fin de saison, ou entree
    suivante qui n'est pas un episode - voir build_list_item)."""
    if not params.get('next_path'):
        return

    next_play_params = {
        'action': 'play', 'path': params['next_path'],
        'title': params.get('next_title', ''), 'thumb': params.get('next_thumb', ''),
        'plot': params.get('next_plot', ''), 'showtitle': params.get('showtitle', ''),
    }
    if params.get('next_season'):
        next_play_params['season'] = params['next_season']
    if params.get('next_episode'):
        next_play_params['episode'] = params['next_episode']

    upnext.notify(
        current={
            'showtitle': params.get('showtitle', ''), 'season': params.get('season', ''),
            'episode': params.get('episode', ''), 'title': params.get('title', ''),
            'plot': params.get('plot', ''), 'thumb': params.get('thumb', ''),
        },
        next_={
            'showtitle': params.get('showtitle', ''), 'season': params.get('next_season', ''),
            'episode': params.get('next_episode', ''), 'title': params.get('next_title', ''),
            'plot': params.get('next_plot', ''), 'thumb': params.get('next_thumb', ''),
            'play_url': _build_url(base_url, **next_play_params),
        },
    )


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


# ---- action "Rafraichir" (menu racine + menu contextuel Mes Listes/En cours) --

def run_refresh_action(handle):
    """Container.Refresh rafraichit le conteneur ACTIF au moment de
    l'appel - donc CET ecran-ci si declenchee depuis son propre menu
    contextuel (Mes Listes, En cours), ou le conteneur cible d'un
    raccourci de skin pointant directement sur cette action. Ne fait
    jamais rien d'autre : notre contenu n'est deja jamais mis en cache
    (cacheToDisc=False partout) - le seul interet ici est de forcer Kodi
    a re-executer la requete tout de suite, sans attendre un eventuel
    rafraichissement automatique de widget de skin."""
    xbmc.executebuiltin('Container.Refresh')
    _notify(ADDON.getLocalizedString(30317), error=False)
    xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)


def run_open_settings(handle):
    ADDON.openSettings()
    xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)


def build_refresh_context_item(base_url):
    """A ajouter dans addContextMenuItems() d'un ecran qu'on veut pouvoir
    rafraichir depuis lui-meme (voir lists_gui.py/watch_progress.py)."""
    url = _build_url(base_url, action='refresh_all')
    return (ADDON.getLocalizedString(30316), 'RunPlugin({0})'.format(url))
