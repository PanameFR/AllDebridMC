# -*- coding: utf-8 -*-
"""Table de dispatch pour toutes les actions "lists_*" de la fonctionnalité
Listes. Les listes elles-mêmes vivent côté serveur (voir lists_store.py
sur le Pi, /api/kodi/lists/*) - partagées avec la page web /lists de
l'outil -, donc ce module ne fait qu'appeler l'API et afficher la
réponse, jamais de stockage ni de cache local.

action_add_local() relie un item déjà présent dans la bibliothèque locale
(choisi depuis la navigation normale, voir navigation.py) à une liste,
avec source="alldebridmc" - voir lists_gui.render_list() pour la
redirection qui en découle à l'affichage.
"""
import xbmc
import xbmcaddon

from resources.lib import api_client
from resources.lib.vstream_adapter import VStreamPastebinAdapter
from resources.lib import lists_gui
from resources.lib import lists_dialogs as dialogs
# Sans risque de cycle : lists_gui (importe juste au-dessus) importe deja
# navigation en tete, il est donc forcement charge a ce stade.
from resources.lib import navigation

ADDON_NAME = "AllDebrid Media Center"
ADDON = xbmcaddon.Addon()


def _show_count():
    try:
        return ADDON.getSettingBool("lists_show_item_count")
    except (AttributeError, TypeError):
        return True


def _refresh():
    xbmc.executebuiltin("Container.Refresh")


def _int(value):
    return int(value) if value is not None else None


def _handle_api_error(exc):
    """Delegue a l'implementation unique et localisee de navigation.py -
    ce module en avait sa propre copie avec des messages francais codes en
    dur. Wrapper conserve (plutot que 16 appels reecrits) : le nom local
    reste le point d'entree naturel ici."""
    navigation.handle_api_error(exc)


# ---- gestion des listes ---------------------------------------------------


def action_create_list(base_url, params):
    name = dialogs.ask_text("Nom de la nouvelle liste")
    if name:
        try:
            api_client.create_list(name)
        except api_client.ApiError as exc:
            _handle_api_error(exc)
    _refresh()


def action_rename_list(base_url, params):
    list_id = _int(params.get("list_id"))
    name = dialogs.ask_text("Renommer la liste", default=params.get("current_name", ""))
    if name:
        try:
            api_client.rename_list(list_id, name)
        except api_client.ApiError as exc:
            _handle_api_error(exc)
    _refresh()


def action_delete_list(base_url, params):
    list_id = _int(params.get("list_id"))
    current_name = params.get("current_name", "")
    if dialogs.confirm("Supprimer la liste", 'Supprimer la liste "%s" ?' % current_name):
        try:
            api_client.delete_list(list_id)
        except api_client.ApiError as exc:
            _handle_api_error(exc)
    _refresh()


def action_move_list(base_url, params):
    try:
        api_client.move_list(_int(params.get("list_id")), params.get("direction"))
    except api_client.ApiError as exc:
        _handle_api_error(exc)
    _refresh()


# ---- items d'une liste ------------------------------------------------------


def action_remove_item(base_url, params):
    try:
        api_client.remove_list_item(
            _int(params.get("list_id")), params.get("media_type"), _int(params.get("tmdb_id"))
        )
    except api_client.ApiError as exc:
        _handle_api_error(exc)
    _refresh()


def action_reorder_item(base_url, params):
    try:
        api_client.move_list_item(
            _int(params.get("list_id")), params.get("media_type"),
            _int(params.get("tmdb_id")), params.get("direction"),
        )
    except api_client.ApiError as exc:
        _handle_api_error(exc)
    _refresh()


def action_search_pastebin_prompt(base_url, params):
    query = dialogs.ask_text("Rechercher (vStream / Pastebin)")
    if query:
        import urllib.parse
        url = "%s?%s" % (base_url, urllib.parse.urlencode({"action": "lists_search", "query": query}))
        xbmc.executebuiltin("Container.Update(%s)" % url)


def action_add_search_result(base_url, params):
    media_type = params.get("media_type")
    tmdb_id = _int(params.get("tmdb_id"))
    # smedia n'est volontairement pas relu des params : le serveur le
    # redetermine depuis le catalogue Pastebin a l'ajout (voir
    # _validate_vstream dans lists_store.py).

    try:
        lists = api_client.list_lists()
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        return

    target = dialogs.choose_list(lists, heading="Ajouter a une liste")
    if target is None:
        return
    if target == "__create__":
        name = dialogs.ask_text("Nom de la nouvelle liste")
        if not name:
            return
        try:
            target = api_client.create_list(name)
        except api_client.ApiError as exc:
            _handle_api_error(exc)
            return

    try:
        api_client.add_list_item(target, media_type, tmdb_id, source="vstream")
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        return

    dialogs.notify(ADDON_NAME, "Ajoute.")


def action_add_local(base_url, params):
    """Relie un item de la bibliotheque locale AllDebridMC (choisi depuis
    la navigation normale, voir navigation.py) a une liste, cote serveur.
    """
    media_type = params.get("media_type")
    tmdb_id = _int(params.get("tmdb_id"))
    path = params.get("path")

    if not (media_type and tmdb_id and path):
        dialogs.notify(ADDON_NAME, "Element incomplet, impossible de l'ajouter")
        return

    try:
        lists = api_client.list_lists()
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        return

    target = dialogs.choose_list(lists, heading="Ajouter a une liste")
    if target is None:
        return
    if target == "__create__":
        name = dialogs.ask_text("Nom de la nouvelle liste")
        if not name:
            return
        try:
            target = api_client.create_list(name)
        except api_client.ApiError as exc:
            _handle_api_error(exc)
            return

    try:
        api_client.add_list_item(target, media_type, tmdb_id, source="alldebridmc", local_path=path)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        return

    dialogs.notify(ADDON_NAME, "Ajoute a la liste")


def action_open(base_url, params):
    # Atteint seulement quand vStream n'etait pas installe au moment du
    # rendu (sinon l'item pointe directement vers le repertoire de
    # vStream). Jamais atteint pour un item local, qui pointe toujours
    # vers action=browse. Reverifie au cas ou l'installation aurait
    # change depuis.
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
    try:
        lists = api_client.list_lists()
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        lists = []
    lists_gui.render_home(base_url, handle, lists, show_count=_show_count())


def _items_per_page():
    try:
        value = ADDON.getSettingInt("lists_items_per_page")
        return value if value and value > 0 else 50
    except (AttributeError, TypeError):
        return 50


def render_list(base_url, handle, params):
    list_id = _int(params.get("list_id"))
    page = _int(params.get("page")) or 1
    try:
        list_data = api_client.list_items(list_id, page=page, per_page=_items_per_page())
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        list_data = {"items": []}
    lists_gui.render_list(base_url, handle, list_id, list_data)


def render_search(base_url, handle, params):
    query = params.get("query")
    if not query:
        dialogs.notify(ADDON_NAME, "Recherche vide.")
        lists_gui.render_search(base_url, handle, [], query)
        return
    try:
        results = api_client.search_vstream_catalog(query)
    except api_client.ApiError as exc:
        _handle_api_error(exc)
        lists_gui.render_search(base_url, handle, [], query)
        return
    lists_gui.render_search(base_url, handle, results, query)


# Actions qui ne rendent pas de repertoire (RunPlugin) : (base_url, params) -> None
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
