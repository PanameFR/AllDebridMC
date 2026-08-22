# -*- coding: utf-8 -*-
"""Rendu des écrans de la fonctionnalité Listes (accueil, contenu d'une
liste, résultats de recherche vStream/Pastebin). Les listes elles-mêmes
sont stockées côté serveur (voir lists_store.py sur le Pi, exposé via
/api/kodi/lists/*) - partagées avec la page web /lists de l'outil -, donc
ce module ne fait qu'afficher ce que le serveur renvoie déjà enrichi
(titre/résumé/affiche), jamais de cache ou de logique TMDB ici.

Le coeur de l'intégration reste dans render_list() : chaque item d'une
liste porte sa propre source ('vstream', ajouté via la recherche
Pastebin - ou depuis la page web -, ou 'alldebridmc', ajouté depuis la
bibliothèque locale) et est redirigé en conséquence, sans jamais mélanger
les deux.
"""
import urllib.parse

import xbmcgui
import xbmcplugin

from resources.lib import navigation
from resources.lib.vstream_adapter import VStreamPastebinAdapter


def _url(base_url, **params):
    params = {k: v for k, v in params.items() if v is not None}
    return base_url + '?' + urllib.parse.urlencode(params)


def build_list_item(entry):
    title = entry.get('title') or '?'
    if entry.get('year'):
        title = '%s (%s)' % (title, entry['year'])

    li = xbmcgui.ListItem(label=title, offscreen=True)
    info = li.getVideoInfoTag()
    info.setTitle(title)
    info.setMediaType('movie' if entry.get('media_type') == 'movie' else 'tvshow')
    if entry.get('year'):
        try:
            info.setYear(int(entry['year']))
        except (TypeError, ValueError):
            pass
    if entry.get('overview'):
        info.setPlot(entry['overview'])

    if entry.get('poster_url'):
        li.setArt({'poster': entry['poster_url'], 'thumb': entry['poster_url']})

    return li


# ---- accueil : liste des listes -------------------------------------------

def render_home(base_url, handle, lists, show_count=True):
    xbmcplugin.setContent(handle, 'videos')

    li = xbmcgui.ListItem(label='+ Creer une liste')
    li.setArt({'icon': 'DefaultAddSource.png'})
    xbmcplugin.addDirectoryItem(handle, _url(base_url, action='lists_create'), li, isFolder=False)

    li = xbmcgui.ListItem(label='Rechercher dans vStream / Pastebin')
    li.setArt({'icon': 'DefaultAddonsSearch.png'})
    xbmcplugin.addDirectoryItem(handle, _url(base_url, action='lists_search_prompt'), li, isFolder=False)

    li = xbmcgui.ListItem(label='Rafraichir')
    li.setArt({'icon': 'DefaultAddonsUpdates.png'})
    xbmcplugin.addDirectoryItem(handle, _url(base_url, action='refresh_all'), li, isFolder=False)

    for lst in lists:
        label = lst['name']
        if show_count:
            label = '%s   [COLOR grey](%d)[/COLOR]' % (label, lst['item_count'])

        li = xbmcgui.ListItem(label=label)
        li.setArt({'icon': 'DefaultVideoPlaylists.png'})

        commands = [
            ('Renommer', 'RunPlugin(%s)' % _url(base_url, action='lists_rename', list_id=lst['id'], current_name=lst['name'])),
            ('Supprimer', 'RunPlugin(%s)' % _url(base_url, action='lists_delete', list_id=lst['id'], current_name=lst['name'])),
            ('Monter', 'RunPlugin(%s)' % _url(base_url, action='lists_move', list_id=lst['id'], direction='up')),
            ('Descendre', 'RunPlugin(%s)' % _url(base_url, action='lists_move', list_id=lst['id'], direction='down')),
            ('Mettre en premier', 'RunPlugin(%s)' % _url(base_url, action='lists_move', list_id=lst['id'], direction='first')),
            ('Mettre en dernier', 'RunPlugin(%s)' % _url(base_url, action='lists_move', list_id=lst['id'], direction='last')),
        ]
        li.addContextMenuItems(commands)

        xbmcplugin.addDirectoryItem(handle, _url(base_url, action='lists_show', list_id=lst['id']), li, isFolder=True)

    xbmcplugin.endOfDirectory(handle)


# ---- contenu d'une liste ---------------------------------------------------

def render_list(base_url, handle, list_id, list_data):
    xbmcplugin.setContent(handle, 'videos')

    adapter = VStreamPastebinAdapter()
    vstream_ok, _ = adapter.check_compatibility()

    for item in list_data.get('items', []):
        media_type = item['media_type']
        tmdb_id = item['tmdb_id']
        source = item.get('source') or 'vstream'

        li = build_list_item(item)
        common = dict(list_id=list_id, media_type=media_type, tmdb_id=tmdb_id)
        common_with_hints = dict(common, title=item.get('title'), smedia=item.get('smedia'))

        if source == 'alldebridmc' and item.get('local_path'):
            # Ajouté depuis la bibliothèque locale : on rouvre directement
            # le contenu du serveur (mêmes films/saisons que la navigation
            # normale de l'addon), jamais vStream - inconditionnellement,
            # que vStream soit installé ou non. Un film peut être rangé à
            # plat (fichier direct) ou dans son propre dossier - local_is_dir
            # dit lequel (calculé côté serveur, jamais fait confiance ici).
            if item.get('local_is_dir'):
                target_url = _url(base_url, action='browse', path=item['local_path'])
                is_folder = True
                play_label = 'Parcourir dans la bibliotheque locale'
                play_command = 'Container.Update(%s)' % target_url
            else:
                play_params = dict(action='play', path=item['local_path'], title=item.get('title') or '')
                if item.get('poster_url'):
                    play_params['thumb'] = item['poster_url']
                if item.get('overview'):
                    play_params['plot'] = item['overview']
                target_url = _url(base_url, **play_params)
                is_folder = False
                li.setProperty('IsPlayable', 'true')
                play_label = 'Lire depuis la bibliotheque locale'
                # RunPlugin ne met pas le plugin dans un contexte de
                # résolution de lecture (setResolvedUrl y serait sans
                # effet) - PlayMedia relance l'addon dans le bon contexte.
                play_command = 'PlayMedia(%s)' % target_url
        elif vstream_ok:
            if media_type == 'movie':
                # Verifie d'abord si le serveur connait une position plus
                # recente pour ce film (laissee sur un autre appareil) et
                # l'ecrit dans la base LOCALE de vStream, pour que SA
                # PROPRE reprise native se declenche - voir
                # watch_progress.py. Fait ICI, au rendu (pas dans une
                # action a part au clic, essaye avant : Kodi n'avait pas
                # fini d'empiler cet ecran relais quand la redirection
                # partait, et "Retour" depuis vStream remontait vers
                # vStream lui-meme plutot que vers cette liste) pour que
                # l'item pointe directement vers vStream, comme une serie.
                # Jamais pour une serie : aucune identite fiable ne survit
                # jusqu'a la lecture reelle d'un episode chez vStream.
                from resources.lib import watch_progress
                watch_progress.maybe_seed_vstream_resume(tmdb_id)
                target_url = adapter.movie_url(
                    tmdb_id, title=item.get('title'), poster_url=item.get('poster_url'),
                )
            else:
                target_url = adapter.tvshow_url(tmdb_id, title=item.get('title'), smedia=item.get('smedia'))
            is_folder = True
            play_label = 'Lire avec vStream / Pastebin'
            play_command = 'Container.Update(%s)' % target_url
        else:
            target_url = _url(base_url, action='lists_open', **common_with_hints)
            is_folder = False
            play_label = 'Lire avec vStream / Pastebin'
            play_command = 'RunPlugin(%s)' % target_url

        if not item.get('available', True):
            play_label = '[COLOR red]Introuvable actuellement[/COLOR]'

        commands = [
            (play_label, play_command),
            ('Retirer de cette liste', 'RunPlugin(%s)' % _url(base_url, action='lists_remove_item', **common)),
            ('Monter', 'RunPlugin(%s)' % _url(base_url, action='lists_reorder_item', direction='up', **common)),
            ('Descendre', 'RunPlugin(%s)' % _url(base_url, action='lists_reorder_item', direction='down', **common)),
            ('Mettre en premier', 'RunPlugin(%s)' % _url(base_url, action='lists_reorder_item', direction='first', **common)),
            ('Mettre en dernier', 'RunPlugin(%s)' % _url(base_url, action='lists_reorder_item', direction='last', **common)),
            navigation.build_refresh_context_item(base_url),
        ]
        li.addContextMenuItems(commands)

        xbmcplugin.addDirectoryItem(handle, target_url, li, isFolder=is_folder)

    if list_data.get('has_next'):
        # Meme convention que vStream (pastebin.py::showMovies, ITEM_PAR_PAGE) :
        # un item "Page suivante" en fin de liste plutot que tout charger
        # d'un coup - la pagination est faite cote SERVEUR (voir
        # lists_store.get_items_enriched), pas juste un decoupage a
        # l'affichage : les items des AUTRES pages ne sont meme pas
        # enrichis (le cout reel, cf. docstring serveur).
        next_page = list_data.get('page', 1) + 1
        li = xbmcgui.ListItem(label='Page suivante >>')
        xbmcplugin.addDirectoryItem(
            handle, _url(base_url, action='lists_show', list_id=list_id, page=next_page), li, isFolder=True,
        )

    xbmcplugin.endOfDirectory(handle)


# ---- résultats de recherche vStream/Pastebin -------------------------------

def render_search(base_url, handle, results, query):
    """Résultats de recherche dans le catalogue Pastebin (lesalkodiques),
    servis par le serveur (voir pastebin_catalog.py) - jamais construits
    depuis les modules internes de vStream : plus besoin que vStream soit
    installé pour chercher, seulement pour lire (voir plus bas).
    """
    xbmcplugin.setContent(handle, 'videos')
    xbmcplugin.setPluginCategory(handle, 'Recherche : "%s"' % query if query else 'Recherche')

    adapter = VStreamPastebinAdapter()
    vstream_ok, _ = adapter.check_compatibility()

    for entry in results:
        media_type = entry['media_type']
        tmdb_id = entry['tmdb_id']
        li = build_list_item(entry)

        add_url = _url(
            base_url, action='lists_add_search_result', media_type=media_type,
            tmdb_id=tmdb_id, title=entry.get('title'), smedia=entry.get('smedia'),
        )
        li.addContextMenuItems([('Ajouter a une liste', 'RunPlugin(%s)' % add_url)])

        if vstream_ok:
            if media_type == 'movie':
                # Voir le meme commentaire dans render_list() plus haut.
                from resources.lib import watch_progress
                watch_progress.maybe_seed_vstream_resume(tmdb_id)
                target_url = adapter.movie_url(tmdb_id, title=entry.get('title'))
            else:
                target_url = adapter.tvshow_url(tmdb_id, title=entry.get('title'), smedia=entry.get('smedia'))
            is_folder = True
        else:
            target_url = _url(
                base_url, action='lists_open', media_type=media_type, tmdb_id=tmdb_id,
                title=entry.get('title'), smedia=entry.get('smedia'),
            )
            is_folder = False

        xbmcplugin.addDirectoryItem(handle, target_url, li, isFolder=is_folder)

    xbmcplugin.endOfDirectory(handle, succeeded=bool(results), cacheToDisc=False)
