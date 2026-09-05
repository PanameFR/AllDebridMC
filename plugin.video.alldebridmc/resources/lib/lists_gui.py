# -*- coding: utf-8 -*-
"""Rendu des écrans de la fonctionnalité Listes (accueil, contenu d'une
liste, résultats de recherche dans le catalogue Pastebin). Les listes
elles-mêmes sont stockées côté serveur (voir lists_store.py sur le Pi,
exposé via /api/kodi/lists/*) - partagées avec la page web /lists de
l'outil -, donc ce module ne fait qu'afficher ce que le serveur renvoie
déjà enrichi (titre/résumé/affiche), jamais de cache ou de logique TMDB
ici.

Le coeur de l'intégration reste dans render_list() : chaque item d'une
liste porte sa propre source ('vstream' - nom historique, le contenu vient
de la source Pastebin et est résolu directement depuis les étapes 1/2 du
chantier de suppression de vStream, plus jamais vStream lui-même -, ou
'alldebridmc', ajouté depuis la bibliothèque locale) et est redirigé en
conséquence, sans jamais mélanger les deux.
"""
import os
import urllib.parse

import xbmcaddon
import xbmcgui
import xbmcplugin

from resources.lib import navigation

# Jaquette de l'item "Page suivante >>" : empaquetee DANS l'addon
# (resources/media/nextpage.png), jamais servie par le Pi - contrairement
# a un poster TMDB, elle doit s'afficher meme sans connexion au serveur ni
# partage SMB monte (demande explicite : l'addon ne doit pas en dependre
# pour ca).
_NEXT_PAGE_ART = os.path.join(
    xbmcaddon.Addon().getAddonInfo('path'), 'resources', 'media', 'nextpage.png',
)


def _guess_lists_content(entries):
    """Meme constat deja fait et corrige ailleurs dans cet addon (voir
    navigation.py::_guess_search_content) : xbmcplugin.setContent(handle,
    'videos') - un type generique - fait retomber Arctic Horizon 2 sur une
    vue par defaut differente de celle d'un type reconnu ('movies',
    'tvshows'...), d'ou le "mur d'affiches" haut qui ne s'affichait plus
    correctement sur les ecrans Listes (contrairement a Stockage/Sagas, qui
    utilisent deja un type precis). vStream fait exactement pareil (voir
    resources/lib/gui/gui.py::setEndOfDirectory - setContent(handle,
    cGui.CONTENT) ou CONTENT vaut 'movies'/'tvshows'/'seasons', jamais
    'videos').
    """
    # Majorite, jamais any() : une liste de 40 films contenant une seule serie
    # basculait entierement dans la vue des series (voir
    # navigation.py::_dominant_content, meme correctif).
    comptes = {'movies': 0, 'tvshows': 0}

    for entry in entries:
        media_type = entry.get('media_type')

        if media_type == 'tv':
            comptes['tvshows'] += 1
        elif media_type in ('movie', 'collection'):
            comptes['movies'] += 1

    return navigation._dominant_content(comptes)


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
    if entry.get('rating'):
        info.setRating(float(entry['rating']))
    if entry.get('runtime'):
        info.setDuration(int(entry['runtime']) * 60)  # TMDB : minutes -> Kodi attend des secondes

    art = {}
    if entry.get('poster_url'):
        art['poster'] = art['thumb'] = entry['poster_url']
    if entry.get('fanart_url'):
        art['fanart'] = entry['fanart_url']
    if entry.get('landscape_url'):
        # Arctic Horizon 2 (variable Image_Landscape) affiche Art(landscape)
        # en priorite sur Art(fanart) pour les vignettes de widget - sans ca
        # les tuiles retombent sur le fanart (arriere-plan uni) au lieu du
        # visuel avec le titre incruste, comme sur les widgets vStream.
        art['landscape'] = entry['landscape_url']
    if art:
        li.setArt(art)

    return li


# ---- accueil : liste des listes -------------------------------------------

def render_home(base_url, handle, lists, show_count=True):
    # 'files' : ce sont des noms de listes (des dossiers), jamais des
    # films/series directement - meme convention que les autres ecrans de
    # menu de cet addon (voir navigation.py).
    xbmcplugin.setContent(handle, 'files')

    li = xbmcgui.ListItem(label='+ Creer une liste')
    li.setArt({'icon': 'DefaultAddSource.png'})
    xbmcplugin.addDirectoryItem(handle, _url(base_url, action='lists_create'), li, isFolder=False)

    li = xbmcgui.ListItem(label='Rechercher dans vStream / Pastebin')
    li.setArt({'icon': 'DefaultAddonsSearch.png'})
    xbmcplugin.addDirectoryItem(handle, _url(base_url, action='lists_search_prompt'), li, isFolder=False)

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
    xbmcplugin.setContent(handle, _guess_lists_content(list_data.get('items', [])))

    for item in list_data.get('items', []):
        media_type = item['media_type']
        tmdb_id = item['tmdb_id']
        source = item.get('source') or 'vstream'

        li = build_list_item(item)
        common = dict(list_id=list_id, media_type=media_type, tmdb_id=tmdb_id)

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
        elif media_type == 'movie':
            # Resolution directe (etape 1 du chantier de suppression de
            # vStream, voir pastebin_playback.py) - plus besoin que vStream
            # soit installe.
            target_url = navigation.build_watch_action_url(
                base_url, 'play_pastebin_movie', tmdb_id=tmdb_id,
                title=item.get('title') or '', thumb=item.get('poster_url') or '',
            )
            is_folder = False
            play_label = 'Lire'
            # RunPlugin (JAMAIS IsPlayable+PlayMedia, contrairement a la
            # bibliotheque locale juste au-dessus) : le choix de qualite
            # peut etre annule par l'utilisateur, et un contexte de
            # resolution de lecture afficherait alors le dialogue natif
            # "Echec de lecture" de Kodi au lieu d'un simple retour en
            # arriere - voir navigation.py::play_pastebin_movie.
            play_command = 'RunPlugin(%s)' % target_url
        else:
            # Serie : notre propre ecran Saisons (etape 2 du chantier de
            # suppression de vStream, voir watch_progress.py::
            # _render_show_seasons) - plus besoin que vStream soit
            # installe, meme raison que pour un film.
            target_url = navigation.build_watch_action_url(
                base_url, 'watch_show_seasons', tmdb_id=tmdb_id,
                title=item.get('title') or '', smedia=item.get('smedia') or '',
            )
            is_folder = True
            play_label = 'Parcourir les saisons'
            play_command = 'Container.Update(%s)' % target_url

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
        li.setArt({'poster': _NEXT_PAGE_ART, 'thumb': _NEXT_PAGE_ART})
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
    label = 'Recherche : "%s"' % query if query else 'Recherche'
    render_pastebin_screen(base_url, handle, results, label)


def render_pastebin_screen(base_url, handle, entries, category_label, next_page_url=None):
    """Meme rendu que render_search ci-dessus (items resolus directement,
    jamais vStream), reutilise par les 4 sous-ecrans du menu "Pastebin"
    (Rechercher/Parcourir tout/Nouveautes-Populaires/Derniers ajouts - voir
    pastebin_routes.py) : seules differences, un libelle d'ecran au lieu du
    texte de recherche, et une pagination optionnelle ("Parcourir tout"
    uniquement - page suivante deja calculee cote serveur, voir
    pastebin_routes.py::kodi_pastebin_category_browse), meme convention que
    render_list() plus haut pour la pagination.
    """
    xbmcplugin.setContent(handle, _guess_lists_content(entries))
    xbmcplugin.setPluginCategory(handle, category_label)

    for entry in entries:
        media_type = entry['media_type']
        tmdb_id = entry['tmdb_id']
        li = build_list_item(entry)

        add_url = _url(
            base_url, action='lists_add_search_result', media_type=media_type,
            tmdb_id=tmdb_id, title=entry.get('title'), smedia=entry.get('smedia'),
        )
        li.addContextMenuItems([('Ajouter a une liste', 'RunPlugin(%s)' % add_url)])

        if media_type == 'movie':
            # Voir le meme commentaire dans render_list() plus haut : jamais
            # IsPlayable ici (le choix de qualite peut etre annule).
            target_url = navigation.build_watch_action_url(
                base_url, 'play_pastebin_movie', tmdb_id=tmdb_id,
                title=entry.get('title') or '', thumb=entry.get('poster_url') or '',
            )
            is_folder = False
        else:
            target_url = navigation.build_watch_action_url(
                base_url, 'watch_show_seasons', tmdb_id=tmdb_id,
                title=entry.get('title') or '', smedia=entry.get('smedia') or '',
            )
            is_folder = True

        xbmcplugin.addDirectoryItem(handle, target_url, li, isFolder=is_folder)

    if next_page_url:
        li = xbmcgui.ListItem(label='Page suivante >>')
        li.setArt({'poster': _NEXT_PAGE_ART, 'thumb': _NEXT_PAGE_ART})
        xbmcplugin.addDirectoryItem(handle, next_page_url, li, isFolder=True)

    xbmcplugin.endOfDirectory(handle, succeeded=bool(entries or next_page_url), cacheToDisc=False)
