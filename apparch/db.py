"""Capa de acceso a datos: SQLite con el registro de paquetes y configuraciones."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


def _default_data_dir() -> Path:
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    """Wrapper delgado sobre sqlite3 con las operaciones que necesita la UI."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (_default_data_dir() / "apparch.db")
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()
        if self._needs_source_migration():
            self._migrate_packages_table()
        self._ensure_date_columns()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS packages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                version TEXT,
                source TEXT NOT NULL CHECK (source IN ('official', 'aur', 'flatpak', 'flatpak_runtime', 'dependency')),
                status TEXT NOT NULL CHECK (status IN ('installed', 'removed')),
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                notes TEXT DEFAULT '',
                installed_date TEXT,
                updated_date TEXT,
                UNIQUE (name, source)
            );

            CREATE TABLE IF NOT EXISTS configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                added_date TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS system_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL CHECK (category IN ('service', 'group', 'wifi')),
                scope TEXT,
                name TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('present', 'removed')),
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                notes TEXT DEFAULT '',
                UNIQUE (category, scope, name)
            );
            """
        )
        self._conn.commit()

    def _needs_source_migration(self) -> bool:
        """Detecta bases de datos creadas antes de soportar los orígenes actuales."""
        cur = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'packages'"
        )
        row = cur.fetchone()
        return row is not None and "dependency" not in row["sql"]

    def _migrate_packages_table(self) -> None:
        """Reconstruye 'packages' con el nuevo esquema, preservando los datos existentes."""
        self._conn.executescript(
            """
            ALTER TABLE packages RENAME TO packages_old;

            CREATE TABLE packages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                version TEXT,
                source TEXT NOT NULL CHECK (source IN ('official', 'aur', 'flatpak', 'flatpak_runtime', 'dependency')),
                status TEXT NOT NULL CHECK (status IN ('installed', 'removed')),
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                notes TEXT DEFAULT '',
                installed_date TEXT,
                updated_date TEXT,
                UNIQUE (name, source)
            );

            INSERT INTO packages (id, name, version, source, status, first_seen, last_seen, notes)
                SELECT id, name, version, source, status, first_seen, last_seen, notes
                FROM packages_old;

            DROP TABLE packages_old;
            """
        )
        self._conn.commit()

    def _ensure_date_columns(self) -> None:
        """Migración aditiva: agrega installed_date/updated_date si faltan."""
        cur = self._conn.execute("PRAGMA table_info(packages)")
        columns = {row["name"] for row in cur.fetchall()}
        if "installed_date" not in columns:
            self._conn.execute("ALTER TABLE packages ADD COLUMN installed_date TEXT")
        if "updated_date" not in columns:
            self._conn.execute("ALTER TABLE packages ADD COLUMN updated_date TEXT")
        self._conn.commit()

    # ---- Paquetes -----------------------------------------------------

    def sync_packages(self, packages_by_source: dict[str, dict[str, str]]) -> dict[str, int]:
        """Sincroniza el resultado de un escaneo con la base de datos.

        packages_by_source: {'official': {nombre: version}, 'aur': {...}, 'flatpak': {...}}
        Solo actualiza los orígenes incluidos en el diccionario: si no se pasa
        'flatpak', por ejemplo, el registro de Flatpak queda intacto (no se
        marca nada como eliminado).
        Devuelve un resumen de cuántos paquetes se agregaron, actualizaron o
        marcaron como eliminados.
        """
        now = _now()
        sources_scanned = set(packages_by_source.keys())

        cur = self._conn.cursor()
        cur.execute("SELECT name, source, status FROM packages")
        existing = {(row["name"], row["source"]): row["status"] for row in cur.fetchall()}

        added = updated = removed = 0
        current_keys: set[tuple[str, str]] = set()

        for source, packages in packages_by_source.items():
            for name, version in packages.items():
                key = (name, source)
                current_keys.add(key)
                if key not in existing:
                    cur.execute(
                        "INSERT INTO packages (name, version, source, status, first_seen, last_seen, notes)"
                        " VALUES (?, ?, ?, 'installed', ?, ?, '')",
                        (name, version, source, now, now),
                    )
                    added += 1
                else:
                    cur.execute(
                        "UPDATE packages SET version = ?, status = 'installed', last_seen = ?"
                        " WHERE name = ? AND source = ?",
                        (version, now, name, source),
                    )
                    updated += 1

        for (name, source), status in existing.items():
            if source in sources_scanned and (name, source) not in current_keys and status != "removed":
                cur.execute(
                    "UPDATE packages SET status = 'removed', last_seen = ? WHERE name = ? AND source = ?",
                    (now, name, source),
                )
                removed += 1

        self._conn.commit()
        return {"added": added, "updated": updated, "removed": removed}

    def update_install_history(
        self, pacman_history: dict[str, dict[str, str]], flatpak_history: dict[str, dict[str, str]]
    ) -> None:
        """Completa installed_date/updated_date a partir de logs del sistema.

        pacman_history se aplica a paquetes con source 'official'/'aur';
        flatpak_history se aplica a los de source 'flatpak'. Paquetes sin
        entrada en el historial correspondiente quedan sin fecha (None).
        """
        cur = self._conn.cursor()
        cur.execute("SELECT id, name, source FROM packages WHERE status = 'installed'")
        for row in cur.fetchall():
            history = pacman_history if row["source"] in ("official", "aur", "dependency") else flatpak_history
            info = history.get(row["name"])
            if not info:
                continue
            cur.execute(
                "UPDATE packages SET installed_date = ?, updated_date = ? WHERE id = ?",
                (info.get("installed"), info.get("updated"), row["id"]),
            )
        self._conn.commit()

    def list_packages(self) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM packages ORDER BY status ASC, source ASC, name ASC"
        )
        return cur.fetchall()

    def update_package_notes(self, package_id: int, notes: str) -> None:
        self._conn.execute("UPDATE packages SET notes = ? WHERE id = ?", (notes, package_id))
        self._conn.commit()

    def package_counts(self) -> dict[str, int]:
        cur = self._conn.execute(
            "SELECT source, status, COUNT(*) AS n FROM packages GROUP BY source, status"
        )
        counts = {
            "official": 0, "aur": 0, "flatpak": 0, "flatpak_runtime": 0, "dependency": 0,
            "removed": 0, "installed": 0,
        }
        for row in cur.fetchall():
            if row["status"] == "installed":
                counts[row["source"]] += row["n"]
                counts["installed"] += row["n"]
            else:
                counts["removed"] += row["n"]
        return counts

    # ---- Sistema (servicios, grupos, redes) ------------------------------

    def sync_system_items(
        self, category: str, items: dict[str, str], scope: str | None = None
    ) -> dict[str, int]:
        """Sincroniza un category+scope específico (p. ej. 'service'+'system').

        items: {nombre: detalle} (el detalle no se persiste, solo define el
        conjunto actual). Todo lo que ya estaba registrado para ese
        category+scope y no aparece más pasa a 'removed'; no toca otros
        category/scope (así escanear servicios no afecta a grupos, etc.).
        """
        now = _now()
        cur = self._conn.cursor()
        cur.execute(
            "SELECT name, status FROM system_items WHERE category = ? AND scope IS ?",
            (category, scope),
        )
        existing = {row["name"]: row["status"] for row in cur.fetchall()}

        added = updated = removed = 0
        for name in items:
            if name not in existing:
                cur.execute(
                    "INSERT INTO system_items (category, scope, name, status, first_seen, last_seen, notes)"
                    " VALUES (?, ?, ?, 'present', ?, ?, '')",
                    (category, scope, name, now, now),
                )
                added += 1
            else:
                cur.execute(
                    "UPDATE system_items SET status = 'present', last_seen = ?"
                    " WHERE category = ? AND scope IS ? AND name = ?",
                    (now, category, scope, name),
                )
                updated += 1

        for name, status in existing.items():
            if name not in items and status != "removed":
                cur.execute(
                    "UPDATE system_items SET status = 'removed', last_seen = ?"
                    " WHERE category = ? AND scope IS ? AND name = ?",
                    (now, category, scope, name),
                )
                removed += 1

        self._conn.commit()
        return {"added": added, "updated": updated, "removed": removed}

    def list_system_items(self) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM system_items ORDER BY category ASC, status ASC, scope ASC, name ASC"
        )
        return cur.fetchall()

    def update_system_item_notes(self, item_id: int, notes: str) -> None:
        self._conn.execute("UPDATE system_items SET notes = ? WHERE id = ?", (notes, item_id))
        self._conn.commit()

    def system_item_counts(self) -> dict[str, int]:
        cur = self._conn.execute(
            "SELECT category, status, COUNT(*) AS n FROM system_items GROUP BY category, status"
        )
        counts = {"service": 0, "group": 0, "wifi": 0, "removed": 0, "present": 0}
        for row in cur.fetchall():
            if row["status"] == "present":
                counts[row["category"]] += row["n"]
                counts["present"] += row["n"]
            else:
                counts["removed"] += row["n"]
        return counts

    # ---- Configuraciones ------------------------------------------------

    def add_config(self, path: str, description: str = "") -> bool:
        try:
            self._conn.execute(
                "INSERT INTO configs (path, description, added_date) VALUES (?, ?, ?)",
                (path, description, _now()),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def list_configs(self) -> list[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM configs ORDER BY path ASC")
        return cur.fetchall()

    def update_config_description(self, config_id: int, description: str) -> None:
        self._conn.execute(
            "UPDATE configs SET description = ? WHERE id = ?", (description, config_id)
        )
        self._conn.commit()

    def remove_config(self, config_id: int) -> None:
        self._conn.execute("DELETE FROM configs WHERE id = ?", (config_id,))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
