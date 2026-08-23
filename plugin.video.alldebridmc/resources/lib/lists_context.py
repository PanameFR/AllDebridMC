# -*- coding: utf-8 -*-
"""Point d'entree pour le menu contextuel systeme "Ajouter a une liste"
affiche sur les items vStream/Pastebin (voir context.py et l'extension
kodi.context.item dans addon.xml). Les listes vivent cote serveur (voir
lists_store.py sur le Pi) - l'ajout n'est accepte que si le tmdb_id existe
reellement dans la source Pastebin lesalkodiques (voir pastebin_catalog.py
sur le Pi), exactement comme pour la recherche (lists_routes.py) et
l'ajout depuis la bibliotheque locale (navigation.py).
"""
import xbmc
import xbmcaddon

from resources.lib import api_client
from resources.lib.tmdb_client import TmdbClient
from resources.lib.vstream_adapter import VStreamPastebinAdapter
from resources.lib import lists_dialogs as dialogs

ADDON_NAME = "AllDebrid Media Center"


def run(path, title, year, dbtype):
    """path/title/year/dbtype sont les infolabels du ListItem selectionne,
    lus par context.py avant toute autre chose - voir son commentaire sur
    l'importance de cet ordre (le focus du container peut deriver pendant
    que les imports de ce module se chargent, sinon).
    """
    adapter = VStreamPastebinAdapter()

    if not adapter.is_pastebin_item(path):
        dialogs.notify(ADDON_NAME, "Cet element ne provient pas de la source Pastebin de vStream")
        return

    addon = xbmcaddon.Addon()
    # Pas de smedia extrait ici : le serveur le redetermine lui-meme depuis
    # le catalogue Pastebin a l'ajout (voir _validate_vstream dans
    # lists_store.py), il n'a donc jamais besoin d'etre transmis.
    media_type = adapter.extract_media_type(path)
    tmdb_id = adapter.extract_tmdb_id(path)

    xbmc.log(
        "[alldebridmc] lists_context.run: path=%r title=%r -> media_type=%r tmdb_id=%r"
        % (path, title, media_type, tmdb_id),
        xbmc.LOGINFO,
    )

    if not tmdb_id:
        # L'URL vStream de cet item n'embarquait pas son tmdb_id : dernier
        # recours, une recherche TMDB par titre pour l'identifier.
        if not title:
            dialogs.notify(ADDON_NAME, "Impossible d'identifier ce contenu")
            return
        if not media_type:
            media_type = "tv" if dbtype == "tvshow" else "movie"

        client = TmdbClient(
            addon.getSetting("lists_tmdb_api_key"),
            language=addon.getSetting("lists_metadata_language") or "fr-FR",
        )
        if not client.has_api_key():
            dialogs.notify(ADDON_NAME, "Aucune cle API TMDB configuree")
            return
        try:
            results = (
                client.search_movie(title, year=year or None)
                if media_type == "movie"
                else client.search_tv(title, year=year or None)
            )
        except Exception:
            dialogs.notify(ADDON_NAME, "TMDB est actuellement inaccessible")
            return

        chosen = dialogs.choose_tmdb_result(results, media_type)
        if not chosen:
            return  # l'utilisateur doit choisir explicitement, jamais deviner
        tmdb_id = chosen["tmdb_id"]
        title = chosen.get("title") or title
    elif not media_type:
        media_type = "movie"

    try:
        lists = api_client.list_lists()
    except api_client.ApiError as exc:
        dialogs.notify(ADDON_NAME, "Impossible de joindre le serveur." if not isinstance(exc, api_client.AuthError)
                        else "Identifiants serveur invalides (reglages de l'addon).")
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
        except api_client.ApiError:
            dialogs.notify(ADDON_NAME, "Impossible de creer la liste.")
            return

    xbmc.log(
        "[alldebridmc] lists_context.run: adding media_type=%r tmdb_id=%r title=%r to list_id=%r"
        % (media_type, tmdb_id, title, target),
        xbmc.LOGINFO,
    )

    try:
        api_client.add_list_item(target, media_type, tmdb_id, source="vstream")
    except api_client.ValidationError as exc:
        dialogs.notify(ADDON_NAME, str(exc))
        return
    except api_client.ApiError:
        dialogs.notify(ADDON_NAME, "Impossible de joindre le serveur.")
        return

    dialogs.notify(ADDON_NAME, "Ajoute a la liste")
