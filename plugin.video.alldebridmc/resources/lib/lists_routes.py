# -*- coding: utf-8 -*-
"""Table de dispatch pour toutes les actions "lists_*" de la fonctionnalite
Listes (integree depuis plugin.video.vstreamlists - voir main.py de cet
addon pour la version d'origine). navigation.route() delegue ici toute
action dont le nom commence par "lists_" ; ce module ne connait rien du
reste de la navigation AllDebridMC (browse/play/movie_info).

action_add_local() est la seule action reellement nouvelle : elle relie
un item deja present dans la bibliotheque locale (choisi depuis la
navigation normale de l'addon, voir navigation.py) a une liste, avec
source="alldebridmc" - voir lists_gui.render_list() pour la redirection
qui en decoule a l'affichage.
"""
import xbmc
import xbmcaddon

from resources.lib.lists_db import DatabaseManager
from resources.lib.lists_manager import ListsManager
from resources.lib.media_manager import MediaManager
from resources.lib.tmdb_client import TmdbClient
from resources.lib.vstream_adapter import VStreamPastebinAdapter
from resources.lib import vstream_bridge
from resources.lib import lists_gui
from resources.lib import lists_dialogs as dialogs
from resources.lib import log

ADDON_NAME = "AllDebrid Media Center"
ADDON = xbmcaddon.Addon()

DB = DatabaseManager("special://profile/addon_data/%s/" % ADDON.getAddonInfo("id"))
LISTS = ListsManager(DB)
MEDIA = MediaManager(DB)


def _tmdb_client():
    api_key = ADDON.getSetting("lists_tmdb_api_key")
    language = ADDON.getSetting("lists_metadata_language") or "fr-FR"
    return TmdbClient(api_key, language=language)


def _cache_ttl_seconds():
    try:
        hours = int(ADDON.getSetting("lists_cache_duration") or "72")
    except ValueError:
        hours = 72
    return hours * 3600


def _show_count():
    try:
        return ADDON.getSettingBool("lists_show_item_count")
    except (AttributeError, TypeError):
        return True


def _refresh():
    xbmc.executebuiltin("Container.Refresh")


def _int(value):
    return int(value) if value is not None else None


# ---- gestion des listes ---------------------------------------------------


def action_create_list(base_url, params):
    name = dialogs.ask_text("Nom de la nouvelle liste")
    if name:
        try:
            LISTS.create_list(name)
        except ValueError:
            dialogs.notify(ADDON_NAME, "Le nom ne peut pas etre vide")
    _refresh()


def action_rename_list(base_url, params):
    list_id = _int(params.get("list_id"))
    current = LISTS.get_list(list_id)
    if not current:
        return
    name = dialogs.ask_text("Renommer la liste", default=current["name"])
    if name:
        LISTS.rename_list(list_id, name)
    _refresh()


def action_delete_list(base_url, params):
    list_id = _int(params.get("list_id"))
    current = LISTS.get_list(list_id)
    if not current:
        return
    if dialogs.confirm("Supprimer la liste", 'Supprimer la liste "%s" ?' % current["name"]):
        LISTS.delete_list(list_id)
    _refresh()


def action_move_list(base_url, params):
    LISTS.move_list(_int(params.get("list_id")), params.get("direction"))
    _refresh()


# ---- items d'une liste ------------------------------------------------------


def action_remove_item(base_url, params):
    LISTS.remove_item(_int(params.get("list_id")), params.get("media_type"), _int(params.get("tmdb_id")))
    _refresh()


def action_reorder_item(base_url, params):
    LISTS.move_item_position(
        _int(params.get("list_id")), params.get("media_type"), _int(params.get("tmdb_id")), params.get("direction"),
    )
    _refresh()


def action_move_item(base_url, params):
    list_id = _int(params.get("list_id"))
    media_type = params.get("media_type")
    tmdb_id = _int(params.get("tmdb_id"))

    target = dialogs.choose_list(LISTS.get_lists(), heading="Deplacer vers", exclude_list_id=list_id)
    if target is None:
        return
    if target == "__create__":
        name = dialogs.ask_text("Nom de la nouvelle liste")
        if not name:
            return
        target = LISTS.create_list(name)

    LISTS.move_item(list_id, target, media_type, tmdb_id)
    _refresh()


def action_copy_item(base_url, params):
    list_id = _int(params.get("list_id"))
    media_type = params.get("media_type")
    tmdb_id = _int(params.get("tmdb_id"))

    target = dialogs.choose_list(LISTS.get_lists(), heading="Ajouter a une autre liste", exclude_list_id=list_id)
    if target is None:
        return
    if target == "__create__":
        name = dialogs.ask_text("Nom de la nouvelle liste")
        if not name:
            return
        target = LISTS.create_list(name)

    # Copie vers une autre liste : on reprend la source/le chemin local
    # deja enregistres sur l'item d'origine plutot que de forcer 'vstream'.
    items = LISTS.get_items(list_id)
    existing = next((i for i in items if i["media_type"] == media_type and i["tmdb_id"] == tmdb_id), None)
    source = (existing or {}).get("source") or "vstream"
    local_path = (existing or {}).get("local_path")

    LISTS.add_item(target, media_type, tmdb_id, source=source, local_path=local_path)
    _refresh()


def action_search_pastebin_prompt(base_url, params):
    query = dialogs.ask_text("Rechercher dans Pastebin (tous medias)")
    if query:
        import urllib.parse

        url = "%s?%s" % (base_url, urllib.parse.urlencode({"action": "lists_search", "query": query}))
        xbmc.executebuiltin("Container.Update(%s)" % url)


def action_add_search_result(base_url, params):
    media_type = params.get("media_type")
    tmdb_id = _int(params.get("tmdb_id"))
    smedia = params.get("smedia")

    target = dialogs.choose_list(LISTS.get_lists(), heading="Ajouter a une liste")
    if target is None:
        return
    if target == "__create__":
        name = dialogs.ask_text("Nom de la nouvelle liste")
        if not name:
            return
        target = LISTS.create_list(name)

    LISTS.add_item(target, media_type, tmdb_id, source="vstream")

    client = _tmdb_client()
    if client.has_api_key():
        MEDIA.ensure_cached(client, media_type, tmdb_id, 0)
    # Separe de l'upsert TMDB de ensure_cached pour qu'une cle API absente
    # ou un TMDB injoignable ne bloque jamais la memorisation de la
    # categorie vStream (film/serie/anime/divers) d'origine de ce titre.
    MEDIA.set_smedia(media_type, tmdb_id, smedia)

    dialogs.notify(ADDON_NAME, "Ajoute.")


def action_add_local(base_url, params):
    """Relie un item de la bibliotheque locale AllDebridMC (choisi depuis
    la navigation normale, voir navigation.py) a une liste. Source =
    'alldebridmc' : lists_gui.render_list() rouvrira directement le
    dossier local (path) plutot que de passer par vStream.
    """
    media_type = params.get("media_type")
    tmdb_id = _int(params.get("tmdb_id"))
    path = params.get("path")
    title = params.get("title")

    if not (media_type and tmdb_id and path):
        dialogs.notify(ADDON_NAME, "Element incomplet, impossible de l'ajouter")
        return

    target = dialogs.choose_list(LISTS.get_lists(), heading="Ajouter a une liste")
    if target is None:
        return
    if target == "__create__":
        name = dialogs.ask_text("Nom de la nouvelle liste")
        if not name:
            return
        target = LISTS.create_list(name)

    LISTS.add_item(target, media_type, tmdb_id, source="alldebridmc", local_path=path)

    client = _tmdb_client()
    media = None
    if client.has_api_key():
        try:
            media = client.refresh_metadata(media_type, tmdb_id)
        except Exception:
            media = None
    if not media:
        # Repli : le titre deja connu localement suffit a ce que l'item ne
        # reste jamais totalement sans metadonnee affichable.
        media = {"media_type": media_type, "tmdb_id": tmdb_id, "title": title}
    MEDIA.upsert(media)

    dialogs.notify(ADDON_NAME, "Ajoute a la liste")


def action_refresh_metadata(base_url, params):
    media_type = params.get("media_type")
    tmdb_id = _int(params.get("tmdb_id"))
    client = _tmdb_client()
    try:
        fresh = client.refresh_metadata(media_type, tmdb_id)
        if fresh:
            MEDIA.upsert(fresh)
    except Exception:
        dialogs.notify(ADDON_NAME, "TMDB est actuellement inaccessible")
    _refresh()


def action_open(base_url, params):
    # Atteint seulement quand vStream n'etait pas installe au moment du
    # rendu (sinon l'item pointe directement vers le repertoire de
    # vStream - voir lists_gui.render_list). Jamais atteint pour un item
    # local (source='alldebridmc'), qui pointe toujours vers action=browse.
    # Reverifie au cas ou l'installation aurait change depuis.
    media_type = params.get("media_type")
    tmdb_id = _int(params.get("tmdb_id"))
    title = params.get("title")
    smedia = params.get("smedia")

    adapter = VStreamPastebinAdapter()
    ok, message = adapter.check_compatibility()
    if not ok:
        dialogs.notify(ADDON_NAME, message)
    else:
        if media_type == "movie":
            url = adapter.movie_url(tmdb_id, title=title)
        else:
            url = adapter.tvshow_url(tmdb_id, title=title, smedia=smedia)
        xbmc.executebuiltin("Container.Update(%s)" % url)


# ---- rendu de repertoires ---------------------------------------------------


def render_home(base_url, handle, params):
    lists_gui.render_home(base_url, handle, LISTS, show_count=_show_count())


def render_list(base_url, handle, params):
    list_id = _int(params.get("list_id"))
    ttl = _cache_ttl_seconds()
    client = _tmdb_client()
    if client.has_api_key():
        for item in LISTS.get_items(list_id):
            MEDIA.ensure_cached(client, item["media_type"], item["tmdb_id"], ttl)
    lists_gui.render_list(base_url, handle, list_id, LISTS)


def render_search(base_url, handle, params):
    query = params.get("query")
    if not query:
        dialogs.notify(ADDON_NAME, "Recherche vide.")
        lists_gui.render_search(base_url, handle, [], query)
        return
    try:
        listing = vstream_bridge.search_all_categories(query)
    except RuntimeError as exc:
        dialogs.notify(ADDON_NAME, str(exc))
        lists_gui.render_search(base_url, handle, [], query)
        return
    except Exception as exc:
        log.error("render_search: unexpected failure: %s" % exc)
        dialogs.notify(ADDON_NAME, "La recherche Pastebin a echoue.")
        lists_gui.render_search(base_url, handle, [], query)
        return
    lists_gui.render_search(
        base_url, handle, listing, query,
        tmdb_client=_tmdb_client(), media_manager=MEDIA, cache_ttl=_cache_ttl_seconds(),
    )


# Actions qui ne rendent pas de repertoire (RunPlugin) : (fonction, params) -> None
_RUN_ACTIONS = {
    "lists_create": action_create_list,
    "lists_rename": action_rename_list,
    "lists_delete": action_delete_list,
    "lists_move": action_move_list,
    "lists_search_prompt": action_search_pastebin_prompt,
    "lists_add_search_result": action_add_search_result,
    "lists_add_local": action_add_local,
    "lists_remove_item": action_remove_item,
    "lists_reorder_item": action_reorder_item,
    "lists_move_item": action_move_item,
    "lists_copy_item": action_copy_item,
    "lists_refresh_metadata": action_refresh_metadata,
    "lists_open": action_open,
}

# Actions qui rendent un repertoire : (base_url, handle, params) -> None
_RENDER_ACTIONS = {
    "lists_home": render_home,
    "lists_show": render_list,
    "lists_search": render_search,
}


def dispatch(base_url, handle, params):
    action = params.get("action")

    render_handler = _RENDER_ACTIONS.get(action)
    if render_handler is not None:
        render_handler(base_url, handle, params)
        return

    run_handler = _RUN_ACTIONS.get(action)
    if run_handler is not None:
        run_handler(base_url, params)
        return

    xbmc.log("[alldebridmc] lists_routes: unknown action %r" % action, xbmc.LOGWARNING)
