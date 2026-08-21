# -*- coding: utf-8 -*-
"""Rendu des ecrans de la fonctionnalite Listes (accueil, contenu d'une
liste, resultats de recherche Pastebin). Consolide depuis les modules
gui/home.py, gui/lists.py, gui/search.py et gui/media.py de
plugin.video.vstreamlists.

Le coeur de l'integration avec AllDebridMC est dans render_list() : chaque
item d'une liste porte sa propre source ('vstream', ajoute via la
recherche Pastebin - comportement d'origine, ou 'alldebridmc', ajoute
depuis la bibliotheque locale du serveur) et est redirige en consequence,
sans jamais melanger les deux.
"""
import urllib.parse

import xbmcgui
import xbmcplugin

from resources.lib.vstream_adapter import VStreamPastebinAdapter
from resources.lib.tmdb_client import TmdbClient


def _url(base_url, **params):
    params = {k: v for k, v in params.items() if v is not None}
    return base_url + "?" + urllib.parse.urlencode(params)


# ---- rendu d'un item media (film/serie), commun a tous les ecrans --------

def enrich_list_item(li, media):
    """Renseigne les infos/arts issus de TMDB (plot, poster, note...) sur
    un ListItem existant, sans toucher a son label - utilise a la fois
    pour nos propres items de liste et pour les items de resultat de
    recherche de vStream, qui portent un titre mais aucune metadonnee
    propre (voir render_search).
    """
    title = media.get("title")

    info = {
        "plot": media.get("overview") or "",
        "mediatype": "movie" if media.get("media_type") == "movie" else "tvshow",
    }
    if title:
        info["title"] = title
        info["originaltitle"] = media.get("original_title") or title
    if media.get("year"):
        try:
            info["year"] = int(media["year"])
        except (TypeError, ValueError):
            pass
    if media.get("genres"):
        info["genre"] = media["genres"] if isinstance(media["genres"], list) else [media["genres"]]
    if media.get("runtime"):
        info["duration"] = int(media["runtime"]) * 60
    if media.get("rating") is not None:
        li.setRating("tmdb", float(media["rating"]))

    li.setInfo("video", info)

    art = {}
    poster = TmdbClient.image_url(media.get("poster_path"))
    fanart = TmdbClient.image_url(media.get("backdrop_path"), size="w1280")
    if poster:
        art["poster"] = poster
        art["thumb"] = poster
    if fanart:
        art["fanart"] = fanart
    if art:
        li.setArt(art)

    return li


def build_list_item(media):
    li = xbmcgui.ListItem(label=media.get("title") or "?")
    return enrich_list_item(li, media)


# ---- accueil : liste des listes -------------------------------------------

def render_home(base_url, handle, lists_manager, show_count=True):
    xbmcplugin.setContent(handle, "videos")

    li = xbmcgui.ListItem(label="+ Creer une liste")
    li.setArt({"icon": "DefaultAddSource.png"})
    xbmcplugin.addDirectoryItem(
        handle, _url(base_url, action="lists_create"), li, isFolder=False
    )

    li = xbmcgui.ListItem(label="Rechercher dans Pastebin")
    li.setArt({"icon": "DefaultAddonsSearch.png"})
    xbmcplugin.addDirectoryItem(
        handle, _url(base_url, action="lists_search_prompt"), li, isFolder=False
    )

    for lst in lists_manager.get_lists():
        label = lst["name"]
        if show_count:
            label = "%s   [COLOR grey](%d)[/COLOR]" % (label, lst["item_count"])

        li = xbmcgui.ListItem(label=label)
        li.setArt({"icon": "DefaultVideoPlaylists.png"})

        commands = [
            ("Renommer", "RunPlugin(%s)" % _url(base_url, action="lists_rename", list_id=lst["id"])),
            ("Supprimer", "RunPlugin(%s)" % _url(base_url, action="lists_delete", list_id=lst["id"])),
            (
                "Monter",
                "RunPlugin(%s)" % _url(base_url, action="lists_move", list_id=lst["id"], direction="up"),
            ),
            (
                "Descendre",
                "RunPlugin(%s)" % _url(base_url, action="lists_move", list_id=lst["id"], direction="down"),
            ),
            (
                "Mettre en premier",
                "RunPlugin(%s)" % _url(base_url, action="lists_move", list_id=lst["id"], direction="first"),
            ),
            (
                "Mettre en dernier",
                "RunPlugin(%s)" % _url(base_url, action="lists_move", list_id=lst["id"], direction="last"),
            ),
        ]
        li.addContextMenuItems(commands)

        xbmcplugin.addDirectoryItem(
            handle, _url(base_url, action="lists_show", list_id=lst["id"]), li, isFolder=True,
        )

    xbmcplugin.endOfDirectory(handle)


# ---- contenu d'une liste ---------------------------------------------------

def render_list(base_url, handle, list_id, lists_manager):
    xbmcplugin.setContent(handle, "videos")

    adapter = VStreamPastebinAdapter()
    vstream_ok, vstream_error = adapter.check_compatibility()

    items = lists_manager.get_items(list_id)
    for item in items:
        media_type = item["media_type"]
        tmdb_id = item["tmdb_id"]
        source = item.get("source") or "vstream"
        local_path = item.get("local_path")

        if item.get("title"):
            li = build_list_item(item)
        else:
            # Metadonnees pas encore en cache (ex: TMDB injoignable a l'ajout).
            li = xbmcgui.ListItem(label="movie/%s" % tmdb_id if media_type == "movie" else "tv/%s" % tmdb_id)

        common = dict(list_id=list_id, media_type=media_type, tmdb_id=tmdb_id)
        common_with_hints = dict(common, title=item.get("title"), smedia=item.get("smedia"))

        if source == "alldebridmc" and local_path:
            # Ajoute depuis la bibliotheque locale : on rouvre directement
            # le contenu du serveur (memes films/saisons que la navigation
            # normale de l'addon), jamais vStream - inconditionnellement,
            # que vStream soit installe ou non. Un film peut etre range a
            # plat (fichier direct, pas de sous-dossier) ou dans son propre
            # dossier selon la bibliotheque - local_is_dir dit lequel.
            if item.get("local_is_dir"):
                target_url = _url(base_url, action="browse", path=local_path)
                is_folder = True
                play_label = "Parcourir dans la bibliotheque locale"
                play_command = "Container.Update(%s)" % target_url
            else:
                play_params = dict(
                    action="play", path=local_path, title=item.get("title") or "",
                    thumb=TmdbClient.image_url(item.get("poster_path")) or "",
                )
                if item.get("overview"):
                    play_params["plot"] = item["overview"]
                if item.get("runtime"):
                    play_params["duration"] = item["runtime"]
                if item.get("rating") is not None:
                    play_params["rating"] = item["rating"]
                target_url = _url(base_url, **play_params)
                is_folder = False
                li.setProperty("IsPlayable", "true")
                play_label = "Lire depuis la bibliotheque locale"
                # RunPlugin ne met pas le plugin dans un contexte de
                # resolution de lecture (setResolvedUrl y serait sans
                # effet) - PlayMedia relance l'addon dans le bon contexte,
                # exactement comme un clic direct sur l'item.
                play_command = "PlayMedia(%s)" % target_url
        elif vstream_ok:
            # Pointe l'item directement vers le repertoire de vStream -
            # Kodi y navigue nativement, sans repasser par notre plugin.
            if media_type == "movie":
                poster_url = TmdbClient.image_url(item.get("poster_path"))
                target_url = adapter.movie_url(tmdb_id, title=item.get("title"), poster_url=poster_url)
            else:
                target_url = adapter.tvshow_url(
                    tmdb_id, title=item.get("title"), smedia=item.get("smedia")
                )
            is_folder = True
            play_label = "Lire avec vStream / Pastebin"
            play_command = "Container.Update(%s)" % target_url
        else:
            # vStream non installe et item non local : on garde l'item sur
            # place et on n'affiche l'avertissement qu'a la tentative de
            # lecture reelle.
            target_url = _url(base_url, action="lists_open", **common_with_hints)
            is_folder = False
            play_label = "Lire avec vStream / Pastebin"
            play_command = "RunPlugin(%s)" % target_url

        commands = [
            (play_label, play_command),
            ("Ajouter a une autre liste", "RunPlugin(%s)" % _url(base_url, action="lists_copy_item", **common)),
            ("Deplacer vers...", "RunPlugin(%s)" % _url(base_url, action="lists_move_item", **common)),
            ("Retirer de cette liste", "RunPlugin(%s)" % _url(base_url, action="lists_remove_item", **common)),
            (
                "Monter",
                "RunPlugin(%s)" % _url(base_url, action="lists_reorder_item", direction="up", **common),
            ),
            (
                "Descendre",
                "RunPlugin(%s)" % _url(base_url, action="lists_reorder_item", direction="down", **common),
            ),
            (
                "Mettre en premier",
                "RunPlugin(%s)" % _url(base_url, action="lists_reorder_item", direction="first", **common),
            ),
            (
                "Mettre en dernier",
                "RunPlugin(%s)" % _url(base_url, action="lists_reorder_item", direction="last", **common),
            ),
            (
                "Actualiser les informations TMDB",
                "RunPlugin(%s)" % _url(base_url, action="lists_refresh_metadata", **common),
            ),
        ]
        li.addContextMenuItems(commands)

        xbmcplugin.addDirectoryItem(handle, target_url, li, isFolder=is_folder)

    xbmcplugin.endOfDirectory(handle)


# ---- resultats de recherche Pastebin ---------------------------------------

def render_search(base_url, handle, listing, query, tmdb_client=None, media_manager=None, cache_ttl=0):
    """Rend une recherche comme un simple repertoire Kodi - rien n'est
    enregistre ici : elle n'existe que pour cet affichage, exactement
    comme parcourir vStream directement. Ajouter un item a une de ses
    listes reste possible par item (menu contextuel ci-dessous), mais les
    resultats eux-memes ne sont pas une liste et ne laissent rien une fois
    qu'on quitte l'ecran.

    Les items Pastebin de vStream ne portent qu'un titre nu (pas de plot,
    poster ou note - voir vstream_bridge), donc quand le TMDB id d'un
    resultat peut etre lu depuis sa propre URL, il est enrichi sur place
    depuis notre cache TMDB avant d'etre ajoute.
    """
    xbmcplugin.setContent(handle, "videos")
    xbmcplugin.setPluginCategory(handle, 'Recherche Pastebin : "%s"' % query if query else "Recherche Pastebin")

    adapter = VStreamPastebinAdapter()
    for item_url, list_item, is_folder in listing:
        tmdb_id = adapter.extract_tmdb_id(item_url)
        media_type = adapter.extract_media_type(item_url)
        if tmdb_id and media_type:
            smedia = adapter.extract_smedia(item_url)
            add_url = _url(
                base_url,
                action="lists_add_search_result",
                media_type=media_type,
                tmdb_id=tmdb_id,
                smedia=smedia,
            )
            # replaceItems reste a False par defaut : on ne fait qu'ajouter
            # aux items contextuels que vStream a peut-etre deja mis,
            # jamais les retirer.
            list_item.addContextMenuItems([("Ajouter a une liste", "RunPlugin(%s)" % add_url)])

            if tmdb_client is not None and tmdb_client.has_api_key() and media_manager is not None:
                media = media_manager.ensure_cached(tmdb_client, media_type, tmdb_id, cache_ttl)
                if media:
                    enrich_list_item(list_item, media)

        xbmcplugin.addDirectoryItem(handle, item_url, list_item, isFolder=is_folder)

    if not listing:
        xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)
        return

    xbmcplugin.endOfDirectory(handle, cacheToDisc=False)
