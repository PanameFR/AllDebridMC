# -*- coding: utf-8 -*-
"""Boites de dialogue partagees par la fonctionnalite Listes. Porte depuis
plugin.video.vstreamlists sans changement.
"""
import xbmcgui


def ask_text(heading, default=""):
    keyboard_result = xbmcgui.Dialog().input(heading, defaultt=default)
    return keyboard_result.strip() if keyboard_result else ""


def confirm(heading, message):
    return xbmcgui.Dialog().yesno(heading, message)


def notify(heading, message, icon=xbmcgui.NOTIFICATION_INFO):
    xbmcgui.Dialog().notification(heading, message, icon, 3000)


def choose_list(lists, heading="Choisir une liste", exclude_list_id=None, allow_create=True):
    """lists: resultat de ListsManager.get_lists(). Renvoie l'id de la
    liste choisie, la chaine "__create__" si l'utilisateur a demande une
    nouvelle liste, ou None si annule.
    """
    candidates = [l for l in lists if l["id"] != exclude_list_id]
    labels = [l["name"] for l in candidates]
    if allow_create:
        labels = ["+ Creer une nouvelle liste"] + labels

    index = xbmcgui.Dialog().select(heading, labels)
    if index < 0:
        return None
    if allow_create:
        if index == 0:
            return "__create__"
        return candidates[index - 1]["id"]
    return candidates[index]["id"]


def choose_tmdb_result(results, media_type):
    if not results:
        notify("AllDebrid Media Center", "Aucun resultat TMDB")
        return None

    labels = []
    for r in results:
        title = r.get("title") or "?"
        year = r.get("year")
        labels.append("%s (%s)" % (title, year) if year else title)

    index = xbmcgui.Dialog().select("Selectionner le bon resultat", labels)
    if index < 0:
        return None
    return results[index]
