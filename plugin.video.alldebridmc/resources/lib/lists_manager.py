# -*- coding: utf-8 -*-
"""Gestion des listes et de leurs items (fonctionnalite Listes, integree
depuis plugin.video.vstreamlists).
"""
import sqlite3
from datetime import datetime, timezone


class ListsManager(object):
    """Proprietaire de lists/list_items et de leur ordre. Ne stocke jamais
    de lien de lecture, d'URL Pastebin ou de reglage vStream - uniquement
    les metadonnees de liste et une reference (media_type, tmdb_id) vers
    la table media, plus la source de lecture (vstream/alldebridmc).
    """

    def __init__(self, db):
        self._db = db

    # ---- lists -----------------------------------------------------

    def create_list(self, name):
        name = (name or "").strip()
        if not name:
            raise ValueError("List name must not be empty")

        now = datetime.now(timezone.utc).isoformat()
        with self._db.connection() as conn:
            next_pos = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM lists"
            ).fetchone()["p"]
            cursor = conn.execute(
                "INSERT INTO lists (name, position, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (name, next_pos, now, now),
            )
            return cursor.lastrowid

    def rename_list(self, list_id, new_name):
        new_name = (new_name or "").strip()
        if not new_name:
            raise ValueError("List name must not be empty")
        now = datetime.now(timezone.utc).isoformat()
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE lists SET name = ?, updated_at = ? WHERE id = ?",
                (new_name, now, list_id),
            )

    def delete_list(self, list_id):
        # ON DELETE CASCADE supprime les list_items ; le cache media et
        # vStream/Pastebin/TMDB ne sont jamais touches.
        with self._db.connection() as conn:
            conn.execute("DELETE FROM lists WHERE id = ?", (list_id,))

    def get_lists(self):
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT l.id, l.name, l.position,
                       COUNT(i.id) AS item_count
                FROM lists l
                LEFT JOIN list_items i ON i.list_id = l.id
                GROUP BY l.id
                ORDER BY l.position ASC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def get_list(self, list_id):
        with self._db.connection() as conn:
            row = conn.execute("SELECT * FROM lists WHERE id = ?", (list_id,)).fetchone()
        return dict(row) if row else None

    def move_list(self, list_id, direction):
        """direction: 'up' | 'down' | 'first' | 'last'"""
        with self._db.transaction() as conn:
            lists = conn.execute(
                "SELECT id, position FROM lists ORDER BY position ASC"
            ).fetchall()
            ids = [r["id"] for r in lists]
            if list_id not in ids:
                return
            idx = ids.index(list_id)
            ids.pop(idx)
            if direction == "up":
                new_idx = max(0, idx - 1)
            elif direction == "down":
                new_idx = min(len(ids), idx + 1)
            elif direction == "first":
                new_idx = 0
            elif direction == "last":
                new_idx = len(ids)
            else:
                raise ValueError("Unknown direction: %s" % direction)
            ids.insert(new_idx, list_id)
            for position, lid in enumerate(ids):
                conn.execute("UPDATE lists SET position = ? WHERE id = ?", (position, lid))

    # ---- list items --------------------------------------------------

    def add_item(self, list_id, media_type, tmdb_id, source="vstream", local_path=None):
        """Idempotent : ajouter un item deja present dans la liste ne fait
        rien (pas de doublon au sein d'une meme liste), mais le meme media
        peut appartenir librement a plusieurs listes.

        source: 'vstream' (defaut, lecture via vStream/Pastebin) ou
        'alldebridmc' (lecture via la bibliotheque locale du serveur,
        local_path est alors le chemin relatif du dossier a parcourir).
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._db.connection() as conn:
            next_pos = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM list_items WHERE list_id = ?",
                (list_id,),
            ).fetchone()["p"]
            try:
                conn.execute(
                    "INSERT INTO list_items "
                    "(list_id, media_type, tmdb_id, position, added_at, source, local_path) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (list_id, media_type, tmdb_id, next_pos, now, source, local_path),
                )
                return True
            except sqlite3.IntegrityError:
                # Deja present dans cette liste : si on le re-ajoute depuis
                # une autre source (ex: retrouve dans la bibliotheque locale
                # apres avoir ete ajoute via vStream), on bascule dessus -
                # l'intention explicite de l'utilisateur est de l'utiliser
                # desormais depuis cette source-la.
                conn.execute(
                    "UPDATE list_items SET source = ?, local_path = ? "
                    "WHERE list_id = ? AND media_type = ? AND tmdb_id = ?",
                    (source, local_path, list_id, media_type, tmdb_id),
                )
                return False

    def remove_item(self, list_id, media_type, tmdb_id):
        with self._db.connection() as conn:
            conn.execute(
                "DELETE FROM list_items WHERE list_id = ? AND media_type = ? AND tmdb_id = ?",
                (list_id, media_type, tmdb_id),
            )

    def move_item(self, from_list_id, to_list_id, media_type, tmdb_id):
        """Deplace un item d'une liste a une autre en une seule transaction :
        ajout a la destination, retrait de l'origine, ou annulation complete.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._db.transaction() as conn:
            source_row = conn.execute(
                "SELECT source, local_path FROM list_items "
                "WHERE list_id = ? AND media_type = ? AND tmdb_id = ?",
                (from_list_id, media_type, tmdb_id),
            ).fetchone()
            source = source_row["source"] if source_row else "vstream"
            local_path = source_row["local_path"] if source_row else None

            next_pos = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM list_items WHERE list_id = ?",
                (to_list_id,),
            ).fetchone()["p"]
            conn.execute(
                """
                INSERT INTO list_items
                    (list_id, media_type, tmdb_id, position, added_at, source, local_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(list_id, media_type, tmdb_id) DO NOTHING
                """,
                (to_list_id, media_type, tmdb_id, next_pos, now, source, local_path),
            )
            conn.execute(
                "DELETE FROM list_items WHERE list_id = ? AND media_type = ? AND tmdb_id = ?",
                (from_list_id, media_type, tmdb_id),
            )

    def get_items(self, list_id):
        """Items d'une liste joints aux metadonnees media en cache, ordonnes."""
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT i.id AS item_id, i.list_id, i.media_type, i.tmdb_id, i.position,
                       i.source, i.local_path,
                       m.title, m.original_title, m.year, m.overview, m.poster_path,
                       m.backdrop_path, m.genres, m.runtime, m.rating, m.smedia
                FROM list_items i
                LEFT JOIN media m ON m.media_type = i.media_type AND m.tmdb_id = i.tmdb_id
                WHERE i.list_id = ?
                ORDER BY i.position ASC
                """,
                (list_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def move_item_position(self, list_id, media_type, tmdb_id, direction):
        """direction: 'up' | 'down' | 'first' | 'last' au sein de la liste."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT media_type, tmdb_id FROM list_items "
                "WHERE list_id = ? ORDER BY position ASC",
                (list_id,),
            ).fetchall()
            keys = [(r["media_type"], r["tmdb_id"]) for r in rows]
            key = (media_type, tmdb_id)
            if key not in keys:
                return
            idx = keys.index(key)
            keys.pop(idx)
            if direction == "up":
                new_idx = max(0, idx - 1)
            elif direction == "down":
                new_idx = min(len(keys), idx + 1)
            elif direction == "first":
                new_idx = 0
            elif direction == "last":
                new_idx = len(keys)
            else:
                raise ValueError("Unknown direction: %s" % direction)
            keys.insert(new_idx, key)
            for position, (mt, tid) in enumerate(keys):
                conn.execute(
                    "UPDATE list_items SET position = ? "
                    "WHERE list_id = ? AND media_type = ? AND tmdb_id = ?",
                    (position, list_id, mt, tid),
                )

    def find_lists_containing(self, media_type, tmdb_id):
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT l.id, l.name
                FROM lists l
                JOIN list_items i ON i.list_id = l.id
                WHERE i.media_type = ? AND i.tmdb_id = ?
                ORDER BY l.position ASC
                """,
                (media_type, tmdb_id),
            ).fetchall()
        return [dict(r) for r in rows]
