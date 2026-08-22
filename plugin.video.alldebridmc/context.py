# -*- coding: utf-8 -*-
"""Point d'entree du menu contextuel systeme "Ajouter a mes listes",
affiche sur les items vStream/Pastebin (voir l'extension kodi.context.item
dans addon.xml). Porte depuis plugin.video.vstreamlists/context.py.
"""
import xbmc

# Lire l'identite du ListItem selectionne D'ABORD, avant toute autre chose
# - meme les imports de resources.lib.lists_context (sqlite, client TMDB...)
# prennent assez de temps a charger pour que le focus du container
# sous-jacent derive vers un autre item entre-temps, ajoutant silencieusement
# le mauvais titre a une liste. xbmc est toujours deja charge par Kodi, donc
# ceci ne coute rien de plus.
_PATH = xbmc.getInfoLabel("ListItem.FolderPath") or xbmc.getInfoLabel("ListItem.Path")
_TITLE = xbmc.getInfoLabel("ListItem.Title") or xbmc.getInfoLabel("ListItem.Label")
_YEAR = xbmc.getInfoLabel("ListItem.Year")
_DBTYPE = xbmc.getInfoLabel("ListItem.DBTYPE")

from resources.lib.lists_context import run

if __name__ == "__main__":
    run(_PATH, _TITLE, _YEAR, _DBTYPE)
