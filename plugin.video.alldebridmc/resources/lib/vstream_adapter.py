# -*- coding: utf-8 -*-
"""Seul module autorise a connaitre le routage de vStream. Porte depuis
plugin.video.vstreamlists (resources/lib/adapters/vstream.py) sans
changement de logique. Si un futur vStream change ses parametres, seul ce
fichier doit changer - lists_manager/lists_gui ne construisent jamais
d'URL vStream eux-memes.

Verifie contre la source publique de vStream (Kodi-vStream/venom-xbmc-addons) :
  - plugin.video.vstream/default.py                    (dispatcher: site=, function=)
  - plugin.video.vstream/resources/sites/pastebin.py    (site=pastebin)

showMovies() lit un parametre "sTmdbId" et, s'il est present, filtre le
contenu du paste sur les entrees dont le TMDB id correspond - a travers
TOUS les codes/groupes Pastebin configures dans vStream (pas besoin de
pasteID). Pour un film, showMovies() ne fait qu'un saut supplementaire
(function=showHosters) une fois un match trouve, et getHosterList() -
que showHosters() appelle - accepte ce meme filtre idTMDB directement, en
court-circuitant sa propre correspondance titre/annee. On appelle donc
directement showHosters pour les films : un ecran de moins qu'en passant
par showMovies.

Series/animes vont un saut plus loin : showSerieSaisons() (vers laquelle
showMovies menerait autrement) lit exactement le meme filtre idTMDB
integre a siteUrl, donc elle aussi peut etre appelee directement - en
sautant l'ecran redondant "recliquer sur le meme titre", tout en
atterrissant sur la liste des saisons, puisque choisir une saison/episode
reste incontournable.

getHosterList() exige que siteUrl porte sMedia, idTMDB et sTitle (acces
dict simple, sans defaut - l'omettre y leve un KeyError), et showHosters()
exige separement un parametre sMovieTitle au niveau superieur pour
l'affichage. On ne voit, choisit ou stocke jamais un serveur, code ou
lien Pastebin nous-memes - vStream continue de tout faire.
"""
import re
import urllib.parse

import xbmcaddon

from resources.lib import log

VSTREAM_ADDON_ID = "plugin.video.vstream"
VSTREAM_PLUGIN_URL = "plugin://%s/" % VSTREAM_ADDON_ID
PASTEBIN_SITE_IDENTIFIER = "pastebin"

# Categories Pastebin propres a vStream. "anime" suit la meme navigation
# saison/episode (showSerieSaisons) que "serie", mais ce sont deux
# catalogues distincts dans le contenu Pastebin lui-meme - un titre
# uniquement tague sMedia=anime ne sera jamais trouve en cherchant sous
# sMedia=serie. On mappe les deux sur notre propre media_type "tv" (TMDB
# ne les distingue pas non plus), mais la categorie d'origine est
# conservee separement (voir MediaManager.set_smedia) pour que rouvrir un
# titre cherche dans la bonne categorie.
_SMEDIA_TO_MEDIA_TYPE = {"film": "movie", "serie": "tv", "anime": "tv"}
DEFAULT_SMEDIA_FOR_TV = "serie"

_TMDB_ID_RE = re.compile(r"(?:sTmdbId|idTMDB)=(\d+)")
_SMEDIA_RE = re.compile(r"sMedia=([a-zA-Z]+)")


class VStreamPastebinAdapter(object):
    """Seul pont entre notre extension et vStream. Construit des URL
    plugin:// vStream et lit les chemins de ListItem de vStream ; ne
    touche jamais aux fichiers, reglages ou base de donnees de vStream.
    """

    def is_vstream_installed(self):
        try:
            xbmcaddon.Addon(VSTREAM_ADDON_ID)
            return True
        except RuntimeError:
            return False

    def get_vstream_version(self):
        try:
            return xbmcaddon.Addon(VSTREAM_ADDON_ID).getAddonInfo("version")
        except RuntimeError:
            return None

    def check_compatibility(self):
        """Verification au mieux. Ne doit jamais supprimer ou masquer une
        liste - au pire, permet d'afficher un avertissement avant une
        tentative de lecture.
        """
        if not self.is_vstream_installed():
            return False, "vStream n'est pas installe."
        return True, None

    # ---- lecture des items vStream/Pastebin (menu contextuel) ----------

    def is_vstream_item(self, path):
        return bool(path) and VSTREAM_ADDON_ID in path

    def is_pastebin_item(self, path):
        if not self.is_vstream_item(path):
            return False
        unquoted = urllib.parse.unquote(path)
        return ("site=%s" % PASTEBIN_SITE_IDENTIFIER) in unquoted

    def extract_tmdb_id(self, path):
        if not path:
            return None
        unquoted = urllib.parse.unquote(path)
        match = _TMDB_ID_RE.search(unquoted)
        return int(match.group(1)) if match else None

    def extract_smedia(self, path):
        """La categorie vStream brute (film/serie/anime/divers), non
        mappee - voir MediaManager.set_smedia pour la raison de la garder
        separee du regroupement movie/tv de extract_media_type().
        """
        if not path:
            return None
        unquoted = urllib.parse.unquote(path)
        match = _SMEDIA_RE.search(unquoted)
        return match.group(1) if match else None

    def extract_media_type(self, path):
        smedia = self.extract_smedia(path)
        if not smedia:
            return None
        return _SMEDIA_TO_MEDIA_TYPE.get(smedia)

    # ---- construction des URL vStream ------------------------------------

    def build_vstream_url(self, function, **params):
        query = {"site": PASTEBIN_SITE_IDENTIFIER, "function": function}
        query.update({k: v for k, v in params.items() if v is not None})
        return VSTREAM_PLUGIN_URL + "?" + urllib.parse.urlencode(query)

    @staticmethod
    def _sanitize_title(title):
        # Reproduit la convention de pastebin.py pour integrer un titre
        # dans une de ces query strings imbriquees (il fait le meme
        # remplacement avant d'ajouter '&sTitle=' a un siteUrl qu'il
        # construit lui-meme).
        title = title or ""
        return title.replace("+", " ").replace(" & ", " | ")

    def movie_url(self, tmdb_id, title=None, poster_url=None):
        title = self._sanitize_title(title)
        # siteUrl doit contenir un '&' pour que pastebin.py le decoupe en
        # prefixe (inutilise) et dict de parametres. sTitle doit etre
        # present (meme si idTMDB finit par matcher et que sa valeur est
        # donc inutilisee pour le filtrage) car getHosterList() accede
        # directement a aParams['sTitle']. Quels codes Pastebin chercher
        # reste entierement laisse a la configuration de vStream.
        site_url = "vstreamlists&sMedia=film&idTMDB=%s&sTitle=%s" % (tmdb_id, title)
        url = self.build_vstream_url(
            "showHosters", siteUrl=site_url, sMovieTitle=title, sThumb=poster_url
        )
        log.debug("built vStream route: media_type=movie tmdb_id=%s url=%s" % (tmdb_id, url))
        return url

    def tvshow_url(self, tmdb_id, title=None, smedia=None):
        smedia = smedia or DEFAULT_SMEDIA_FOR_TV
        title = self._sanitize_title(title)
        # Meme comportement idTMDB-court-circuite-le-titre que
        # getHosterList() (voir docstring du module). sMovieTitle sert a
        # l'affichage des libelles de saison et de repli si idTMDB ne
        # matche plus rien (ex: contenu retire de Pastebin depuis).
        site_url = "vstreamlists&sMedia=%s&idTMDB=%s" % (smedia, tmdb_id)
        url = self.build_vstream_url(
            "showSerieSaisons", siteUrl=site_url, sMovieTitle=title
        )
        log.debug(
            "built vStream route: media_type=tv smedia=%s tmdb_id=%s url=%s"
            % (smedia, tmdb_id, url)
        )
        return url
