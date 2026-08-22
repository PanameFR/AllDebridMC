# -*- coding: utf-8 -*-
"""Client TMDB independant utilise par la fonctionnalite Listes, porte
depuis plugin.video.vstreamlists. Sert uniquement a identifier un contenu
et recuperer ses metadonnees d'affichage pour les listes - separe du
proxy /api/kodi/movie-info du serveur AllDebridMC (qui ne couvre que les
films deja associes dans la bibliotheque locale, pas la recherche libre
ni les series).
"""
import json
import urllib.parse
import urllib.request
import urllib.error

from resources.lib import log

TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/"


class TmdbError(Exception):
    pass


class TmdbClient(object):
    def __init__(self, api_key, language="fr-FR", timeout=10):
        self._api_key = api_key
        self._language = language
        self._timeout = timeout

    def has_api_key(self):
        return bool(self._api_key)

    def _request(self, path, params=None):
        if not self._api_key:
            raise TmdbError("No TMDB API key configured")

        query = dict(params or {})
        query["api_key"] = self._api_key
        query["language"] = self._language
        url = "%s%s?%s" % (TMDB_API_BASE, path, urllib.parse.urlencode(query))

        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            log.error("TMDB HTTP %s on %s" % (exc.code, path))
            raise TmdbError("TMDB HTTP %s on %s" % (exc.code, path))
        except urllib.error.URLError as exc:
            log.error("TMDB unreachable on %s: %s" % (path, exc))
            raise TmdbError("TMDB unreachable: %s" % exc)

    # ---- search ------------------------------------------------------

    def search_movie(self, query, year=None):
        params = {"query": query}
        if year:
            params["year"] = year
        data = self._request("/search/movie", params)
        return [self._normalize_movie(r) for r in data.get("results", [])]

    def search_tv(self, query, year=None):
        params = {"query": query}
        if year:
            params["first_air_date_year"] = year
        data = self._request("/search/tv", params)
        return [self._normalize_tv(r) for r in data.get("results", [])]

    # ---- details -------------------------------------------------------

    def get_movie(self, tmdb_id):
        data = self._request("/movie/%s" % tmdb_id)
        return self._normalize_movie(data, detailed=True)

    def get_tv(self, tmdb_id):
        data = self._request("/tv/%s" % tmdb_id)
        return self._normalize_tv(data, detailed=True)

    def refresh_metadata(self, media_type, tmdb_id):
        if media_type == "movie":
            return self.get_movie(tmdb_id)
        return self.get_tv(tmdb_id)

    # ---- normalization -------------------------------------------------

    def _normalize_movie(self, r, detailed=False):
        year = (r.get("release_date") or "")[:4] or None
        return {
            "media_type": "movie",
            "tmdb_id": r.get("id"),
            "title": r.get("title"),
            "original_title": r.get("original_title"),
            "year": year,
            "overview": r.get("overview"),
            "poster_path": r.get("poster_path"),
            "backdrop_path": r.get("backdrop_path"),
            "genres": self._genre_names(r, detailed),
            "runtime": r.get("runtime") if detailed else None,
            "rating": r.get("vote_average"),
        }

    def _normalize_tv(self, r, detailed=False):
        year = (r.get("first_air_date") or "")[:4] or None
        return {
            "media_type": "tv",
            "tmdb_id": r.get("id"),
            "title": r.get("name"),
            "original_title": r.get("original_name"),
            "year": year,
            "overview": r.get("overview"),
            "poster_path": r.get("poster_path"),
            "backdrop_path": r.get("backdrop_path"),
            "genres": self._genre_names(r, detailed),
            "runtime": (r.get("episode_run_time") or [None])[0],
            "rating": r.get("vote_average"),
        }

    @staticmethod
    def _genre_names(r, detailed):
        if detailed:
            return [g.get("name") for g in r.get("genres", []) if g.get("name")]
        return []

    @staticmethod
    def image_url(path, size="w500"):
        if not path:
            return None
        return "%s%s%s" % (TMDB_IMAGE_BASE, size, path)
