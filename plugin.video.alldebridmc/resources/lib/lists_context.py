# -*- coding: utf-8 -*-
"""Point d'entree pour le menu contextuel systeme "Ajouter a mes listes"
affiche sur les items vStream/Pastebin (voir context.py et l'extension
kodi.context.item dans addon.xml). Porte depuis
plugin.video.vstreamlists/resources/lib/context/handler.py, chemins
d'import mis a jour. Ne touche jamais a vStream lui-meme.
"""
import xbmc
import xbmcaddon

from resources.lib.lists_db import DatabaseManager
from resources.lib.lists_manager import ListsManager
from resources.lib.media_manager import MediaManager
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
    db = DatabaseManager("special://profile/addon_data/%s/" % addon.getAddonInfo("id"))
    lists_manager = ListsManager(db)
    media_manager = MediaManager(db)

    smedia = adapter.extract_smedia(path)
    media_type = adapter.extract_media_type(path)
    tmdb_id = adapter.extract_tmdb_id(path)

    xbmc.log(
        "[alldebridmc] lists_context.run: path=%r title=%r -> media_type=%r tmdb_id=%r"
        % (path, title, media_type, tmdb_id),
        xbmc.LOGINFO,
    )

    client = TmdbClient(
        addon.getSetting("lists_tmdb_api_key"),
        language=addon.getSetting("lists_metadata_language") or "fr-FR",
    )

    media = None

    if tmdb_id:
        # ID deja connu : pas d'ambiguite, on ajoute immediatement et on
        # enrichit depuis TMDB ensuite (au mieux).
        if not media_type:
            media_type = "movie"
        try:
            media = client.refresh_metadata(media_type, tmdb_id)
        except Exception:
            media = {"media_type": media_type, "tmdb_id": tmdb_id, "title": title, "year": year or None}
        media["smedia"] = smedia
    else:
        if not title:
            dialogs.notify(ADDON_NAME, "Impossible d'identifier ce contenu")
            return

        if not media_type:
            media_type = "tv" if dbtype == "tvshow" else "movie"

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
        media = chosen
        media["smedia"] = smedia or ("film" if media_type == "movie" else "serie")
        tmdb_id = media["tmdb_id"]

    target = dialogs.choose_list(lists_manager.get_lists(), heading="Ajouter a mes listes")
    if target is None:
        return
    if target == "__create__":
        name = dialogs.ask_text("Nom de la nouvelle liste")
        if not name:
            return
        target = lists_manager.create_list(name)

    xbmc.log(
        "[alldebridmc] lists_context.run: adding media_type=%r tmdb_id=%r title=%r to list_id=%r"
        % (media_type, tmdb_id, media.get("title") if media else title, target),
        xbmc.LOGINFO,
    )

    if media:
        media_manager.upsert(media)
    lists_manager.add_item(target, media_type, tmdb_id, source="vstream")
    dialogs.notify(ADDON_NAME, "Ajoute a la liste")
