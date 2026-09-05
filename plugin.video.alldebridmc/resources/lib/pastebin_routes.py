# -*- coding: utf-8 -*-
"""Étape 3 du chantier de suppression de vStream : menu "Pastebin" de
l'addon - gestion des codes d'accès par catégorie, rafraîchissement manuel
du catalogue, et les sous-écrans par catégorie reprenant la structure
réelle de vStream (resources/sites/pastebin.py, inspecté directement) :
Rechercher/Rechercher-Sagas/Parcourir tout/Nouveautés/Populaires/Derniers
ajouts/Listes/Genres/Les mieux notés/Par diffuseur (conditionnel)/Années/
Alphabétique/Aléatoire. Côté serveur, tout s'appuie sur pastebin_catalog.py
(déjà mature) exposé via pastebin_routes.py - ce module-ci (côté Kodi) ne
fait qu'appeler l'API et afficher la réponse, même convention que
lists_routes.py/lists_gui.py pour la fonctionnalité Listes.

La plupart des sous-écrans de contenu délèguent à
lists_gui.render_pastebin_screen - même forme d'entrée (title/year/
media_type/tmdb_id/smedia/poster_url) et mêmes cibles de clic (lecture
directe/écran Saisons) que la recherche de la fonctionnalité Listes,
aucune duplication. Les écrans "de choix" (Genres, Listes, Années,
Alphabétique, Par diffuseur) sont rendus directement ici (pas de titre à
jouer, juste une navigation vers un sous-écran de contenu).
"""
import urllib.parse

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

from resources.lib import api_client
from resources.lib import lists_dialogs as dialogs
from resources.lib import lists_gui
from resources.lib import navigation

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo('name')


def _handle_api_error(exc):
    navigation.handle_api_error(exc)


# ---- accueil : catégories + actions globales -------------------------------

def render_home(base_url, handle, params):
    try:
        categories = api_client.pastebin_categories()
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        categories = []

    xbmcplugin.setPluginCategory(handle, ADDON.getLocalizedString(30355))
    xbmcplugin.setContent(handle, 'files')

    items = [_build_codes_menu_item(base_url), _build_refresh_menu_item(base_url)]
    items.extend(_build_category_menu_item(base_url, category) for category in categories)

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


def _build_codes_menu_item(base_url):
    li = xbmcgui.ListItem(label=ADDON.getLocalizedString(30361), offscreen=True)
    li.setArt({'icon': 'DefaultAddonProgram.png'})
    url = navigation.build_watch_action_url(base_url, 'pastebin_codes')
    return url, li, True


def _build_refresh_menu_item(base_url):
    li = xbmcgui.ListItem(label=ADDON.getLocalizedString(30362), offscreen=True)
    li.setArt({'icon': 'DefaultAddonsUpdates.png'})
    url = navigation.build_watch_action_url(base_url, 'pastebin_refresh')
    return url, li, False


def _build_category_menu_item(base_url, category):
    li = xbmcgui.ListItem(label=category.get('label') or category.get('key'), offscreen=True)
    li.setArt({'icon': 'DefaultFolder.png'})
    url = navigation.build_watch_action_url(
        base_url, 'pastebin_category', category=category.get('key'), label=category.get('label') or '',
    )
    return url, li, True


# ---- sous-menu d'une catégorie ---------------------------------------------

def render_category(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category

    xbmcplugin.setPluginCategory(handle, label)
    xbmcplugin.setContent(handle, 'files')

    items = [
        _build_search_menu_item(base_url, category, label),
        _build_saga_search_menu_item(base_url, category, label),
        _build_browse_menu_item(base_url, category, label),
        _build_news_menu_item(base_url, category, label),
        _build_trending_menu_item(base_url, category, label),
        _build_recent_menu_item(base_url, category, label),
        _build_groups_menu_item(base_url, category, label),
        _build_genres_menu_item(base_url, category, label),
        _build_top_rated_menu_item(base_url, category, label),
    ]

    # "Par diffuseur" (vStream::showNetwork) - visible seulement si la
    # source Pastebin porte reellement des diffuseurs pour cette categorie
    # (colonne NETWORK optionnelle, souvent absente - voir pastebin_catalog.py) :
    # un menu qui ne mene jamais qu'a un ecran vide serait pire que son
    # absence. Meme logique conditionnelle que vStream lui-meme (containFilmNetwork
    # etc. dans getPasteBin()), jamais un affichage inconditionnel.
    try:
        has_networks = bool(api_client.pastebin_networks(category))
    except api_client.ApiError:
        has_networks = False
    if has_networks:
        items.append(_build_networks_menu_item(base_url, category, label))

    items.append(_build_years_menu_item(base_url, category, label))
    items.append(_build_alpha_menu_item(base_url, category, label))
    items.append(_build_random_menu_item(base_url, category, label))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


def _build_search_menu_item(base_url, category, label):
    li = xbmcgui.ListItem(label=ADDON.getLocalizedString(30338), offscreen=True)
    li.setArt({'icon': 'DefaultAddonsSearch.png'})
    url = navigation.build_watch_action_url(
        base_url, 'pastebin_category_search_prompt', category=category, label=label,
    )
    return url, li, False


def _build_saga_search_menu_item(base_url, category, label):
    li = xbmcgui.ListItem(label=ADDON.getLocalizedString(30376), offscreen=True)
    li.setArt({'icon': 'DefaultSets.png'})
    url = navigation.build_watch_action_url(
        base_url, 'pastebin_category_saga_search_prompt', category=category, label=label,
    )
    return url, li, False


def _build_groups_menu_item(base_url, category, label):
    li = xbmcgui.ListItem(label=ADDON.getLocalizedString(30377), offscreen=True)
    li.setArt({'icon': 'DefaultVideoPlaylists.png'})
    url = navigation.build_watch_action_url(base_url, 'pastebin_category_groups', category=category, label=label)
    return url, li, True


def _build_years_menu_item(base_url, category, label):
    li = xbmcgui.ListItem(label=ADDON.getLocalizedString(30378), offscreen=True)
    li.setArt({'icon': 'DefaultYear.png'})
    url = navigation.build_watch_action_url(base_url, 'pastebin_category_years', category=category, label=label)
    return url, li, True


def _build_alpha_menu_item(base_url, category, label):
    li = xbmcgui.ListItem(label=ADDON.getLocalizedString(30379), offscreen=True)
    li.setArt({'icon': 'DefaultPlaylist.png'})
    url = navigation.build_watch_action_url(base_url, 'pastebin_category_alpha', category=category, label=label)
    return url, li, True


def _build_random_menu_item(base_url, category, label):
    li = xbmcgui.ListItem(label=ADDON.getLocalizedString(30380), offscreen=True)
    li.setArt({'icon': 'DefaultAddSource.png'})
    url = navigation.build_watch_action_url(base_url, 'pastebin_category_random', category=category, label=label)
    return url, li, True


def _build_browse_menu_item(base_url, category, label):
    li = xbmcgui.ListItem(label=ADDON.getLocalizedString(30358), offscreen=True)
    li.setArt({'icon': 'DefaultFolder.png'})
    url = navigation.build_watch_action_url(
        base_url, 'pastebin_category_browse', category=category, label=label, page=1,
    )
    return url, li, True


def _build_trending_menu_item(base_url, category, label):
    li = xbmcgui.ListItem(label=ADDON.getLocalizedString(30359), offscreen=True)
    li.setArt({'icon': 'DefaultRecentlyAddedMovies.png'})
    url = navigation.build_watch_action_url(base_url, 'pastebin_category_trending', category=category, label=label)
    return url, li, True


def _build_recent_menu_item(base_url, category, label):
    li = xbmcgui.ListItem(label=ADDON.getLocalizedString(30360), offscreen=True)
    li.setArt({'icon': 'DefaultRecentlyAddedEpisodes.png'})
    url = navigation.build_watch_action_url(base_url, 'pastebin_category_recent', category=category, label=label)
    return url, li, True


def _build_news_menu_item(base_url, category, label):
    li = xbmcgui.ListItem(label=ADDON.getLocalizedString(30372), offscreen=True)
    li.setArt({'icon': 'DefaultAddonsUpdates.png'})
    url = navigation.build_watch_action_url(base_url, 'pastebin_category_news', category=category, label=label)
    return url, li, True


def _build_genres_menu_item(base_url, category, label):
    li = xbmcgui.ListItem(label=ADDON.getLocalizedString(30373), offscreen=True)
    li.setArt({'icon': 'DefaultGenre.png'})
    url = navigation.build_watch_action_url(base_url, 'pastebin_category_genres', category=category, label=label)
    return url, li, True


def _build_top_rated_menu_item(base_url, category, label):
    li = xbmcgui.ListItem(label=ADDON.getLocalizedString(30374), offscreen=True)
    li.setArt({'icon': 'DefaultFavourites.png'})
    url = navigation.build_watch_action_url(base_url, 'pastebin_category_top_rated', category=category, label=label)
    return url, li, True


def _build_networks_menu_item(base_url, category, label):
    li = xbmcgui.ListItem(label=ADDON.getLocalizedString(30375), offscreen=True)
    li.setArt({'icon': 'DefaultNetwork.png'})
    url = navigation.build_watch_action_url(base_url, 'pastebin_category_networks', category=category, label=label)
    return url, li, True


# ---- 4 sous-écrans de contenu -----------------------------------------------

def render_browse(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category
    page = int(params.get('page') or 1)

    try:
        data = api_client.pastebin_browse(category, page=page)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        data = {'entries': [], 'has_next': False}

    next_page_url = None
    if data.get('has_next'):
        next_page_url = navigation.build_watch_action_url(
            base_url, 'pastebin_category_browse', category=category, label=label, page=page + 1,
        )
    lists_gui.render_pastebin_screen(base_url, handle, data.get('entries', []), label, next_page_url=next_page_url)


def render_trending(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category
    try:
        entries = api_client.pastebin_trending(category)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        entries = []
    screen_label = '{0} — {1}'.format(label, ADDON.getLocalizedString(30359))
    lists_gui.render_pastebin_screen(base_url, handle, entries, screen_label)


def render_news(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category
    try:
        entries = api_client.pastebin_news(category)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        entries = []
    screen_label = '{0} — {1}'.format(label, ADDON.getLocalizedString(30372))
    lists_gui.render_pastebin_screen(base_url, handle, entries, screen_label)


def render_top_rated(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category
    try:
        entries = api_client.pastebin_top_rated(category)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        entries = []
    screen_label = '{0} — {1}'.format(label, ADDON.getLocalizedString(30374))
    lists_gui.render_pastebin_screen(base_url, handle, entries, screen_label)


# ---- Genres (écran de choix, puis titres du genre choisi) ------------------

def render_genres(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category

    try:
        genres = api_client.pastebin_genres(category)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        genres = []

    xbmcplugin.setPluginCategory(handle, '{0} — {1}'.format(label, ADDON.getLocalizedString(30373)))
    xbmcplugin.setContent(handle, 'genres')

    items = []
    for genre in genres:
        li = xbmcgui.ListItem(label=genre.get('name') or '?', offscreen=True)
        li.setArt({'icon': 'DefaultGenre.png'})
        url = navigation.build_watch_action_url(
            base_url, 'pastebin_category_genre', category=category, label=label,
            genre_name=genre.get('name') or '',
            movie_genre_id=genre.get('movie_genre_id') or '', tv_genre_id=genre.get('tv_genre_id') or '',
        )
        items.append((url, li, True))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=bool(items), cacheToDisc=False)


def render_genre_browse(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category
    genre_name = params.get('genre_name') or ''
    movie_genre_id = params.get('movie_genre_id') or None
    tv_genre_id = params.get('tv_genre_id') or None

    try:
        entries = api_client.pastebin_genre_browse(category, movie_genre_id=movie_genre_id, tv_genre_id=tv_genre_id)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        entries = []

    screen_label = '{0} — {1}'.format(label, genre_name) if genre_name else label
    lists_gui.render_pastebin_screen(base_url, handle, entries, screen_label)


# ---- Par diffuseur (écran de choix, puis titres du diffuseur choisi) -------

def render_networks(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category

    try:
        networks = api_client.pastebin_networks(category)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        networks = []

    xbmcplugin.setPluginCategory(handle, '{0} — {1}'.format(label, ADDON.getLocalizedString(30375)))
    xbmcplugin.setContent(handle, 'files')

    items = []
    for network in networks:
        li = xbmcgui.ListItem(label=network.get('name') or '?', offscreen=True)
        li.setArt({'icon': 'DefaultNetwork.png'})
        url = navigation.build_watch_action_url(
            base_url, 'pastebin_category_network', category=category, label=label,
            network_id=network.get('id'), network_name=network.get('name') or '',
        )
        items.append((url, li, True))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=bool(items), cacheToDisc=False)


def render_network_browse(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category
    network_id = params.get('network_id', '')
    network_name = params.get('network_name') or ''

    try:
        entries = api_client.pastebin_network_browse(category, network_id) if network_id else []
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        entries = []

    screen_label = '{0} — {1}'.format(label, network_name) if network_name else label
    lists_gui.render_pastebin_screen(base_url, handle, entries, screen_label)


def render_recent(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category
    try:
        entries = api_client.pastebin_recent(category)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        entries = []
    screen_label = '{0} — {1}'.format(label, ADDON.getLocalizedString(30360))
    lists_gui.render_pastebin_screen(base_url, handle, entries, screen_label)


def action_search_prompt(base_url, params):
    category = params.get('category', '')
    label = params.get('label') or category
    query = dialogs.ask_text(ADDON.getLocalizedString(30338))
    if query:
        url = base_url + '?' + urllib.parse.urlencode({
            'action': 'pastebin_category_search', 'category': category, 'label': label, 'query': query,
        })
        xbmc.executebuiltin('Container.Update({0})'.format(url))


def render_search(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category
    query = params.get('query', '')

    try:
        entries = api_client.pastebin_search(category, query) if query else []
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        entries = []

    screen_label = (
        '{0} — {1}'.format(label, ADDON.getLocalizedString(30341).format(query)) if query else label
    )
    lists_gui.render_pastebin_screen(base_url, handle, entries, screen_label)


# ---- Rechercher - Sagas (vStream::showSearchSaga/showSaga) -----------------

def action_saga_search_prompt(base_url, params):
    category = params.get('category', '')
    label = params.get('label') or category
    query = dialogs.ask_text(ADDON.getLocalizedString(30376))
    if not query:
        return

    try:
        collections = api_client.pastebin_saga_search(category, query)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        return

    if not collections:
        dialogs.notify(ADDON_NAME, ADDON.getLocalizedString(30381))
        return

    labels = [c.get('name') or '?' for c in collections]
    index = xbmcgui.Dialog().select(ADDON.getLocalizedString(30376), labels)
    if index < 0:
        return

    chosen = collections[index]
    url = base_url + '?' + urllib.parse.urlencode({
        'action': 'pastebin_category_saga', 'category': category, 'label': label,
        'collection_id': chosen.get('id'), 'saga_name': chosen.get('name') or '',
    })
    xbmc.executebuiltin('Container.Update({0})'.format(url))


def render_saga_browse(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category
    collection_id = params.get('collection_id', '')
    saga_name = params.get('saga_name') or ''

    try:
        entries = api_client.pastebin_saga_browse(category, collection_id) if collection_id else []
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        entries = []

    screen_label = '{0} — {1}'.format(label, saga_name) if saga_name else label
    lists_gui.render_pastebin_screen(base_url, handle, entries, screen_label)


# ---- Listes (vStream::showGroupes/showGroupeDetails) -----------------------

def render_groups(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category

    try:
        groups = api_client.pastebin_groups(category)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        groups = []

    xbmcplugin.setPluginCategory(handle, '{0} — {1}'.format(label, ADDON.getLocalizedString(30377)))
    xbmcplugin.setContent(handle, 'files')

    items = []
    for group in groups:
        li = xbmcgui.ListItem(label=group.get('name') or '?', offscreen=True)
        li.setArt({'icon': 'DefaultVideoPlaylists.png'})
        if group.get('kind') == 'parent':
            url = navigation.build_watch_action_url(
                base_url, 'pastebin_category_group_children', category=category, label=label,
                parent=group.get('name') or '',
            )
        else:
            url = navigation.build_watch_action_url(
                base_url, 'pastebin_category_group_items', category=category, label=label,
                group=group.get('name') or '', group_display=group.get('name') or '',
            )
        items.append((url, li, True))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=bool(items), cacheToDisc=False)


def render_group_children(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category
    parent = params.get('parent') or ''

    try:
        children = api_client.pastebin_group_children(category, parent)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        children = []

    xbmcplugin.setPluginCategory(handle, '{0} — {1}'.format(label, parent))
    xbmcplugin.setContent(handle, 'files')

    items = []
    for child in children:
        li = xbmcgui.ListItem(label=child.get('display') or '?', offscreen=True)
        li.setArt({'icon': 'DefaultVideoPlaylists.png'})
        url = navigation.build_watch_action_url(
            base_url, 'pastebin_category_group_items', category=category, label=label,
            group=child.get('full_name') or '', group_display=child.get('display') or '',
        )
        items.append((url, li, True))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=bool(items), cacheToDisc=False)


def render_group_items(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category
    group = params.get('group') or ''
    group_display = params.get('group_display') or group

    try:
        entries = api_client.pastebin_group_items(category, group) if group else []
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        entries = []

    screen_label = '{0} — {1}'.format(label, group_display) if group_display else label
    lists_gui.render_pastebin_screen(base_url, handle, entries, screen_label)


# ---- Années (vStream::showYears) -------------------------------------------

def render_years(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category

    try:
        years = api_client.pastebin_years(category)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        years = []

    xbmcplugin.setPluginCategory(handle, '{0} — {1}'.format(label, ADDON.getLocalizedString(30378)))
    xbmcplugin.setContent(handle, 'files')

    items = []
    for year in years:
        li = xbmcgui.ListItem(label=str(year), offscreen=True)
        li.setArt({'icon': 'DefaultYear.png'})
        url = navigation.build_watch_action_url(
            base_url, 'pastebin_category_year', category=category, label=label, year=year,
        )
        items.append((url, li, True))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=bool(items), cacheToDisc=False)


def render_year_browse(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category
    year = params.get('year', '')

    try:
        entries = api_client.pastebin_year_browse(category, year) if year else []
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        entries = []

    screen_label = '{0} — {1}'.format(label, year) if year else label
    lists_gui.render_pastebin_screen(base_url, handle, entries, screen_label)


# ---- Alphabétique (vStream::alphaList) --------------------------------------

_ALPHA_LETTERS = tuple('ABCDEFGHIJKLMNOPQRSTUVWXYZ') + ('#',)


def render_alpha(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category

    xbmcplugin.setPluginCategory(handle, '{0} — {1}'.format(label, ADDON.getLocalizedString(30379)))
    xbmcplugin.setContent(handle, 'files')

    items = []
    for letter in _ALPHA_LETTERS:
        li = xbmcgui.ListItem(label=letter, offscreen=True)
        li.setArt({'icon': 'DefaultPlaylist.png'})
        url = navigation.build_watch_action_url(
            base_url, 'pastebin_category_letter', category=category, label=label, letter=letter,
        )
        items.append((url, li, True))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


def render_letter_browse(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category
    letter = params.get('letter', '')

    try:
        entries = api_client.pastebin_letter_browse(category, letter) if letter else []
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        entries = []

    screen_label = '{0} — {1}'.format(label, letter) if letter else label
    lists_gui.render_pastebin_screen(base_url, handle, entries, screen_label)


# ---- Aléatoire (vStream::showMovies bRandom=True) ---------------------------

def render_random(base_url, handle, params):
    category = params.get('category', '')
    label = params.get('label') or category

    try:
        entries = api_client.pastebin_random(category)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        entries = []

    screen_label = '{0} — {1}'.format(label, ADDON.getLocalizedString(30380))
    lists_gui.render_pastebin_screen(base_url, handle, entries, screen_label)


# ---- codes d'accès -----------------------------------------------------------

def render_codes(base_url, handle, params):
    try:
        codes = api_client.pastebin_codes()
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        codes = []

    xbmcplugin.setPluginCategory(handle, ADDON.getLocalizedString(30361))
    xbmcplugin.setContent(handle, 'files')

    items = []
    for entry in codes:
        label = '{0}   [COLOR grey]{1}[/COLOR]'.format(entry.get('label') or entry.get('key'), entry.get('code') or '—')
        li = xbmcgui.ListItem(label=label, offscreen=True)
        li.setArt({'icon': 'DefaultAddonProgram.png'})
        url = navigation.build_watch_action_url(
            base_url, 'pastebin_code_edit', category=entry.get('key'),
            label=entry.get('label') or '', current_code=entry.get('code') or '',
        )
        items.append((url, li, False))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


def action_edit_code(base_url, params):
    category = params.get('category', '')
    label = params.get('label') or category
    current_code = params.get('current_code', '')

    new_code = dialogs.ask_text(ADDON.getLocalizedString(30364).format(label), default=current_code)
    if not new_code or new_code == current_code:
        return

    try:
        api_client.pastebin_set_code(category, new_code)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        return

    dialogs.notify(ADDON_NAME, ADDON.getLocalizedString(30365))
    xbmc.executebuiltin('Container.Refresh')


def action_refresh(base_url, params):
    try:
        api_client.pastebin_refresh()
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        return
    dialogs.notify(ADDON_NAME, ADDON.getLocalizedString(30363))
    xbmc.executebuiltin('Container.Refresh')


# ---- dispatch ----------------------------------------------------------------

# Actions qui rendent un répertoire : (base_url, handle, params) -> None
_RENDER_ACTIONS = {
    'pastebin_home': render_home,
    'pastebin_category': render_category,
    'pastebin_category_browse': render_browse,
    'pastebin_category_trending': render_trending,
    'pastebin_category_news': render_news,
    'pastebin_category_top_rated': render_top_rated,
    'pastebin_category_genres': render_genres,
    'pastebin_category_genre': render_genre_browse,
    'pastebin_category_networks': render_networks,
    'pastebin_category_network': render_network_browse,
    'pastebin_category_recent': render_recent,
    'pastebin_category_search': render_search,
    'pastebin_category_saga': render_saga_browse,
    'pastebin_category_groups': render_groups,
    'pastebin_category_group_children': render_group_children,
    'pastebin_category_group_items': render_group_items,
    'pastebin_category_years': render_years,
    'pastebin_category_year': render_year_browse,
    'pastebin_category_alpha': render_alpha,
    'pastebin_category_letter': render_letter_browse,
    'pastebin_category_random': render_random,
    'pastebin_codes': render_codes,
}

# Actions qui ne rendent pas de répertoire (RunPlugin) : (base_url, params) -> None
_RUN_ACTIONS = {
    'pastebin_category_search_prompt': action_search_prompt,
    'pastebin_category_saga_search_prompt': action_saga_search_prompt,
    'pastebin_code_edit': action_edit_code,
    'pastebin_refresh': action_refresh,
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

    xbmc.log('[alldebridmc] pastebin_routes: unknown action %r' % action, xbmc.LOGWARNING)
    xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)
