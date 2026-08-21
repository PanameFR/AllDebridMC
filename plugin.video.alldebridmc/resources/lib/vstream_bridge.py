# -*- coding: utf-8 -*-
"""Lit directement le moteur de recherche Pastebin de vStream (jamais ses
fichiers - seulement ses modules Python deja installes, importes a
l'execution) pour couvrir toutes les categories (film/serie/anime/divers)
en une seule liste fusionnee au lieu du menu categorie-par-categorie que
vStream propose lui-meme. Porte depuis plugin.video.vstreamlists sans
changement de logique (seul le chemin d'import de VStreamPastebinAdapter
est mis a jour).

Le piege : les deux addons utilisent le meme nom de paquet top-level
"resources" pour leur propre code (resources.lib.xxx). Le process Python
de Kodi cache les modules importes dans sys.modules sous ce nom, donc un
simple "import resources.sites.pastebin" resoudrait contre le "resources"
deja en cache - le notre, puisque c'est nous qui tournons. _ImportScope
ci-dessous evacue nos propres entrees "resources.*" de sys.modules et met
le dossier de l'addon vStream en tete de sys.path le temps de l'import
seulement, puis restaure tout exactement comme avant. Une fois les
classes/fonctions de vStream importees dans des variables locales ici,
les appeler plus tard n'a plus besoin de rien de tout ca - un appel de
fonction Python ne re-consulte pas sys.modules, seule une instruction
"import" fraiche le fait.

Fragilite acceptee : showMovies() de vStream est un detail d'implementation
prive, pas une API publiee. Si une future version de vStream la renomme,
change ses parametres, ou revoit son filtrage/sa pagination, cette
recherche casse jusqu'a mise a jour - silencieusement, jusqu'a ce que
quelque chose l'appelle. Ce compromis est intentionnel : c'est le seul
moyen d'obtenir une liste vraiment fusionnee plutot que quatre separees,
sans toucher aux fichiers de vStream.
"""
import sys
import urllib.parse

import xbmcaddon

from resources.lib import log
from resources.lib.vstream_adapter import VSTREAM_ADDON_ID, VStreamPastebinAdapter

_CATEGORIES = ("film", "serie", "anime", "divers")


class _ImportScope:
    """Gestionnaire de contexte : confie temporairement l'espace de noms
    "resources" au dossier de l'addon vStream, puis le rend - voir la
    docstring du module ci-dessus."""

    def __enter__(self):
        self._saved_path = list(sys.path)
        self._saved_modules = {}
        for name in list(sys.modules):
            if name == "resources" or name.startswith("resources."):
                self._saved_modules[name] = sys.modules.pop(name)

        vstream_root = xbmcaddon.Addon(VSTREAM_ADDON_ID).getAddonInfo("path")
        sys.path.insert(0, vstream_root)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for name in list(sys.modules):
            if name == "resources" or name.startswith("resources."):
                del sys.modules[name]
        sys.path[:] = self._saved_path
        sys.modules.update(self._saved_modules)
        return False


def search_all_categories(query):
    """Cherche dans les sources Pastebin de vStream, toutes categories a
    la fois. Renvoie une liste de tuples (item_url, xbmcgui.ListItem,
    is_folder) - exactement la forme attendue par
    xbmcplugin.addDirectoryItems - construite entierement par le code de
    vStream (titres, vignettes, URL de navigation), pour qu'un item
    selectionne se lance ou s'ouvre exactement comme depuis vStream lui-meme.

    Leve RuntimeError avec un message affichable a l'utilisateur si
    vStream n'est pas installe ou si la recherche elle-meme echoue.
    """
    ok, message = VStreamPastebinAdapter().check_compatibility()
    if not ok:
        raise RuntimeError(message)

    quoted = urllib.parse.quote(query, safe="")

    with _ImportScope():
        try:
            from resources.sites import pastebin as vstream_pastebin
        except Exception as exc:
            log.error("vstream_bridge: could not import vStream's pastebin module: %s" % exc)
            raise RuntimeError("Impossible de lire le module Pastebin de vStream (vStream a peut-etre change).")

        # Accumulateur frais pour cette recherche seulement - voir la
        # docstring du module : cette liste est un attribut de classe
        # partage par chaque instance de cGui, donc elle doit etre
        # reinitialisee avant reutilisation, et entierement videe une fois
        # lue (pour qu'une simple navigation vStream plus tard dans la
        # meme session Kodi, si le process est reutilise, n'herite pas
        # d'entrees perimees).
        vstream_pastebin.cGui.listing = []

        for category in _CATEGORIES:
            site_url = "vstreamlists&sMedia=%s&sSearch=%s" % (category, quoted)
            try:
                vstream_pastebin.showMovies(sSearch=site_url)
            except Exception as exc:
                log.error("vstream_bridge: search failed for category '%s': %s" % (category, exc))
                # Une categorie qui echoue (ex: une source Pastebin
                # injoignable) ne doit pas faire perdre les resultats deja
                # trouves dans les autres.
                continue

        results = list(vstream_pastebin.cGui.listing)
        vstream_pastebin.cGui.listing = []

    return results
