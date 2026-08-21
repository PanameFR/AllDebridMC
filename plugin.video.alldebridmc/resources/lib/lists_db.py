# -*- coding: utf-8 -*-
"""Connexion SQLite et migrations pour lists.db (fonctionnalite Listes,
integree depuis l'addon vStream Listes - voir lists_routes.py).
"""
import sqlite3
from contextlib import contextmanager

import xbmcvfs

_DB_FILENAME = "lists.db"

# Chaque entree est appliquee une seule fois, dans l'ordre, et enregistree
# dans schema_version : une mise a jour de l'addon ne touche jamais aux
# donnees deja presentes.
MIGRATIONS = [
    # 1: schema initial (porte tel quel depuis plugin.video.vstreamlists)
    """
    CREATE TABLE IF NOT EXISTS lists (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        position    INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS media (
        media_type          TEXT NOT NULL,
        tmdb_id             INTEGER NOT NULL,
        title               TEXT,
        original_title      TEXT,
        year                TEXT,
        overview            TEXT,
        poster_path         TEXT,
        backdrop_path       TEXT,
        genres              TEXT,
        runtime             INTEGER,
        rating              REAL,
        metadata_updated_at TEXT,
        PRIMARY KEY (media_type, tmdb_id)
    );

    CREATE TABLE IF NOT EXISTS list_items (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        list_id     INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
        media_type  TEXT NOT NULL,
        tmdb_id     INTEGER NOT NULL,
        position    INTEGER NOT NULL DEFAULT 0,
        added_at    TEXT NOT NULL,
        UNIQUE(list_id, media_type, tmdb_id)
    );

    CREATE INDEX IF NOT EXISTS idx_list_items_list ON list_items(list_id);
    CREATE INDEX IF NOT EXISTS idx_list_items_media ON list_items(media_type, tmdb_id);
    """,
    # 2: categorie vStream d'origine (film/serie/anime/divers).
    "ALTER TABLE media ADD COLUMN smedia TEXT;",
    # 3: un item de liste vient soit de vStream/Pastebin (comportement
    # d'origine, valeur par defaut pour les lignes existantes), soit de la
    # bibliotheque locale AllDebridMC - auquel cas local_path porte le
    # chemin relatif du dossier a parcourir sur le serveur.
    """
    ALTER TABLE list_items ADD COLUMN source TEXT NOT NULL DEFAULT 'vstream';
    ALTER TABLE list_items ADD COLUMN local_path TEXT;
    """,
]


class DatabaseManager(object):
    """Connexion SQLite dediee a lists.db. Ne touche jamais aux fichiers,
    reglages, historique ou favoris de vStream/AllDebridMC eux-memes.
    """

    def __init__(self, profile_path):
        real_path = xbmcvfs.translatePath(profile_path)
        if not xbmcvfs.exists(real_path):
            xbmcvfs.mkdirs(real_path)
        self._db_path = real_path.rstrip("/\\") + "/" + _DB_FILENAME
        self._migrate()

    def _connect(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _migrate(self):
        conn = self._connect()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
            )
            row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            current = row["v"] if row and row["v"] is not None else 0

            for index, script in enumerate(MIGRATIONS, start=1):
                if index <= current:
                    continue
                conn.executescript(script)
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (index,))
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def connection(self):
        """Connexion auto-commit pour lectures/ecritures simples."""
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        """BEGIN/COMMIT/ROLLBACK explicite pour les operations multi-etapes
        (ex: deplacer un item entre listes) afin qu'un echec ne laisse
        jamais la base a moitie modifiee.
        """
        conn = self._connect()
        try:
            conn.execute("BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
