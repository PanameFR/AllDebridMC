# -*- coding: utf-8 -*-
"""Cache local de metadonnees TMDB pour la fonctionnalite Listes, cle par
(media_type, tmdb_id). Porte depuis plugin.video.vstreamlists.
"""
import json
from datetime import datetime, timezone


class MediaManager(object):
    """Cache uniquement : l'identite d'un contenu est toujours
    media_type + tmdb_id, jamais le titre, et jamais un lien
    Pastebin/streaming ou un chemin local (ceux-ci vivent sur
    list_items, voir lists_manager.py).
    """

    def __init__(self, db):
        self._db = db

    def upsert(self, media):
        now = datetime.now(timezone.utc).isoformat()
        genres = media.get("genres")
        if isinstance(genres, (list, tuple)):
            genres = json.dumps(genres)

        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO media (
                    media_type, tmdb_id, title, original_title, year, overview,
                    poster_path, backdrop_path, genres, runtime, rating,
                    smedia, metadata_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(media_type, tmdb_id) DO UPDATE SET
                    title=excluded.title,
                    original_title=excluded.original_title,
                    year=excluded.year,
                    overview=excluded.overview,
                    poster_path=excluded.poster_path,
                    backdrop_path=excluded.backdrop_path,
                    genres=excluded.genres,
                    runtime=excluded.runtime,
                    rating=excluded.rating,
                    smedia=COALESCE(excluded.smedia, media.smedia),
                    metadata_updated_at=excluded.metadata_updated_at
                """,
                (
                    media["media_type"],
                    media["tmdb_id"],
                    media.get("title"),
                    media.get("original_title"),
                    media.get("year"),
                    media.get("overview"),
                    media.get("poster_path"),
                    media.get("backdrop_path"),
                    genres,
                    media.get("runtime"),
                    media.get("rating"),
                    media.get("smedia"),
                    now,
                ),
            )

    def set_smedia(self, media_type, tmdb_id, smedia):
        """Enregistre la categorie vStream (film/serie/anime/divers) sous
        laquelle ce titre a ete trouve, sans toucher aux champs issus de
        TMDB. Ne fait rien si la ligne media n'existe pas encore ou si
        smedia est inconnu.
        """
        if not smedia:
            return
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE media SET smedia = ? WHERE media_type = ? AND tmdb_id = ?",
                (smedia, media_type, tmdb_id),
            )

    def get(self, media_type, tmdb_id):
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM media WHERE media_type = ? AND tmdb_id = ?",
                (media_type, tmdb_id),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        if result.get("genres"):
            try:
                result["genres"] = json.loads(result["genres"])
            except (TypeError, ValueError):
                result["genres"] = []
        return result

    def needs_refresh(self, media_type, tmdb_id, ttl_seconds):
        cached = self.get(media_type, tmdb_id)
        if not cached or not cached.get("metadata_updated_at"):
            return True
        try:
            updated = datetime.fromisoformat(cached["metadata_updated_at"])
        except ValueError:
            return True
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - updated
        return age.total_seconds() > ttl_seconds

    def ensure_cached(self, tmdb_client, media_type, tmdb_id, ttl_seconds):
        """Renvoie les metadonnees en cache, ne les rafraichit depuis TMDB
        que si elles sont perimees ou absentes, et tolere que TMDB soit
        injoignable (repli sur le cache existant : une erreur TMDB ne doit
        jamais casser la navigation).
        """
        if self.needs_refresh(media_type, tmdb_id, ttl_seconds):
            try:
                if media_type == "movie":
                    fresh = tmdb_client.get_movie(tmdb_id)
                else:
                    fresh = tmdb_client.get_tv(tmdb_id)
                if fresh:
                    self.upsert(fresh)
            except Exception:
                pass
        return self.get(media_type, tmdb_id)
