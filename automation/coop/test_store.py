"""Disposable legacy-database coverage for the western excavation migration."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from server import Store


class StoreMigrationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="orebit-legacy-db-test-")
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / "legacy.sqlite3")
        self.state = {
            "player_money": 98765, "player_cargo": {"Ironium": 4},
            "player_items": {"Dynamite": 3}, "x": 13.5, "y": -64.5,
            "current_upgrades": {"Cargo": "Huge Bay"},
        }
        with sqlite3.connect(self.path) as database:
            database.executescript("""
                PRAGMA foreign_keys=ON;
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY, username TEXT UNIQUE,
                    display_name TEXT NOT NULL, password_hash TEXT,
                    discord_id TEXT UNIQUE, created_at INTEGER NOT NULL
                );
                CREATE TABLE tokens (
                    hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                    expires_at INTEGER NOT NULL, created_at INTEGER NOT NULL
                );
                CREATE TABLE worlds (
                    id TEXT PRIMARY KEY, seed INTEGER NOT NULL, created_at INTEGER NOT NULL
                );
                CREATE TABLE player_states (
                    world_id TEXT NOT NULL REFERENCES worlds(id),
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL, PRIMARY KEY(world_id,user_id)
                );
                CREATE TABLE excavations (
                    world_id TEXT NOT NULL REFERENCES worlds(id),
                    x INTEGER NOT NULL CHECK(x>=0 AND x<36),
                    y INTEGER NOT NULL CHECK(y>=0 AND y<600),
                    user_id INTEGER REFERENCES users(id), created_at INTEGER NOT NULL,
                    PRIMARY KEY(world_id,x,y)
                );
                INSERT INTO users VALUES(17,'legacy_miner','Legacy Miner','saved-password-hash',NULL,100);
                INSERT INTO tokens VALUES('saved-token-hash',17,9999999999,101);
                INSERT INTO worlds VALUES('public',42,102),('other_world',1234,103);
                INSERT INTO excavations VALUES('public',0,6,17,110),('public',35,587,NULL,111),('other_world',9,10,17,112);
            """)
            database.execute("INSERT INTO player_states VALUES(?,?,?,?,?)", ("public", 17, json.dumps(self.state), 9, 109))
            self.original = {
                table: database.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall()
                for table in ("users", "tokens", "worlds", "player_states", "excavations")
            }

    def assert_original_progress(self, database):
        for table in ("users", "tokens", "worlds", "player_states"):
            self.assertEqual(database.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall(), self.original[table])
        state, revision = database.execute("SELECT state,revision FROM player_states WHERE world_id='public' AND user_id=17").fetchone()
        self.assertEqual(json.loads(state), self.state)
        self.assertEqual(revision, 9)

    async def test_legacy_rows_and_accounts_survive_western_excavation_and_reopen(self):
        store = Store(self.path)
        try:
            self.assertEqual(store.connection.execute("PRAGMA user_version").fetchone()[0], 1)
            # Comparisons use ordinary tuples, as in the pre-migration snapshot.
            with sqlite3.connect(self.path) as database:
                self.assert_original_progress(database)
                self.assertEqual(database.execute("SELECT * FROM excavations ORDER BY 1,2").fetchall(), self.original["excavations"])
            for x, y in ((-10, 6), (-1, 599)):
                await store.run(lambda db, x=x, y=y: db.execute(
                    "INSERT INTO excavations VALUES(?,?,?,?,?)", ("public", x, y, 17, 120)
                ))
            for x, y in ((-11, 6), (36, 6), (-10, -1), (-10, 600)):
                with self.subTest(x=x, y=y), self.assertRaises(sqlite3.IntegrityError):
                    await store.run(lambda db, x=x, y=y: db.execute(
                        "INSERT INTO excavations VALUES(?,?,?,?,?)", ("public", x, y, 17, 121)
                    ))
        finally:
            await store.close()

        reopened = Store(self.path)
        try:
            with sqlite3.connect(self.path) as database:
                self.assert_original_progress(database)
                expected = self.original["excavations"] + [
                    ("public", -10, 6, 17, 120), ("public", -1, 599, 17, 120),
                ]
                self.assertEqual(set(database.execute("SELECT * FROM excavations").fetchall()), set(expected))
                self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            await reopened.close()

    async def test_copy_or_ddl_failure_rolls_back_the_entire_migration(self):
        connect = sqlite3.connect
        for failing_statement in ("INSERT INTO excavations_west", "ALTER TABLE excavations_west"):
            with self.subTest(statement=failing_statement):
                class FailingConnection(sqlite3.Connection):
                    def execute(self, sql, parameters=()):
                        if sql.strip().startswith(failing_statement):
                            raise sqlite3.OperationalError("injected migration failure")
                        return super().execute(sql, parameters)

                with patch("server.sqlite3.connect", side_effect=lambda *args, **kwargs: connect(*args, factory=FailingConnection, **kwargs)):
                    with self.assertRaisesRegex(sqlite3.OperationalError, "injected migration failure"):
                        Store(self.path)
                with connect(self.path) as database:
                    self.assert_original_progress(database)
                    self.assertEqual(database.execute("SELECT * FROM excavations ORDER BY 1,2").fetchall(), self.original["excavations"])
                    self.assertEqual(database.execute("PRAGMA user_version").fetchone()[0], 0)
                    self.assertIsNone(database.execute("SELECT name FROM sqlite_master WHERE name='excavations_west'").fetchone())
                    with self.assertRaises(sqlite3.IntegrityError):
                        database.execute("INSERT INTO excavations VALUES('public',-1,6,17,123)")


if __name__ == "__main__":
    unittest.main()
