from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import threading
import uuid
from typing import Any

from .config import BACKEND_DIR


DEFAULT_HABITS = (
    ("gym", "Gym", "Strength, gym, or workout session"),
    ("running", "Running", "Run, walk, or cardio session"),
    ("work", "Work", "Focused work or useful work block"),
)

DEFAULT_MEMORIES = (
    (
        "memory-project-am",
        "project",
        "A&M",
        "College/TAMU/Blinn/housing/classes/school admin.",
    ),
    (
        "memory-project-xo",
        "project",
        "XO",
        "VR/worldbuilding/prototype project with Ashwin and Charlie.",
    ),
    (
        "memory-project-nebulo",
        "project",
        "Nebulo",
        "Startup/work involving private cloud storage and AI context control.",
    ),
    (
        "memory-project-freelance",
        "project",
        "Freelance",
        "Client outreach, websites, law firms, dentists, realtors, portfolio, invoices.",
    ),
    (
        "memory-project-personal",
        "project",
        "Personal",
        "Gym, health, shopping, errands, car, family, life admin.",
    ),
    ("memory-person-brandon", "person", "Brandon", "Associated with Nebulo."),
    ("memory-person-ashwin", "person", "Ashwin", "Associated with XO."),
    ("memory-person-charlie", "person", "Charlie", "Associated with XO."),
    ("memory-person-nikhil", "person", "Nikhil", "A&M roommate."),
    ("memory-person-andy", "person", "Andy", "A&M roommate."),
    ("memory-person-kamden", "person", "Kamden", "A&M roommate."),
    ("memory-person-sam", "person", "Sam", "Carrollton house / UTD friend group."),
    ("memory-person-jai", "person", "Jai", "Carrollton house / UTD friend group."),
    ("memory-person-krrish", "person", "Krrish", "Carrollton house / UTD friend group."),
    ("memory-group-am-roommates", "group", "A&M roommates", "Nikhil, Andy, Kamden."),
    (
        "memory-group-carrollton-utd",
        "group",
        "Carrollton house / UTD group",
        "Sam, Jai, Krrish.",
    ),
    (
        "memory-rule-shopping-errands",
        "classification_rule",
        "Shopping and errands",
        "Shopping and errands go to Personal.",
    ),
    (
        "memory-rule-college",
        "classification_rule",
        "College/TAMU/Blinn",
        "College/TAMU/Blinn tasks go to A&M.",
    ),
    (
        "memory-rule-xo",
        "classification_rule",
        "VR/headset/Ashwin/Charlie",
        "VR/headset/Ashwin/Charlie tasks go to XO.",
    ),
    (
        "memory-rule-nebulo",
        "classification_rule",
        "Brandon/Nebulo/context-control",
        "Brandon/Nebulo/context-control tasks go to Nebulo.",
    ),
    (
        "memory-rule-freelance",
        "classification_rule",
        "Client/law firm/dentist/realtor/website",
        "Client/law firm/dentist/realtor/website tasks go to Freelance.",
    ),
    (
        "memory-rule-misc",
        "classification_rule",
        "Misc fallback",
        "Misc is fallback only.",
    ),
    (
        "memory-preference-one-action",
        "preference",
        "One clear next action",
        "Give one clear next action.",
    ),
    (
        "memory-preference-tone",
        "preference",
        "Direct supportive tone",
        "Be direct, supportive, and not guilt-based.",
    ),
    (
        "memory-preference-low-energy",
        "preference",
        "Low-energy mode",
        "Low-energy mode should suggest tiny useful wins.",
    ),
    (
        "memory-preference-gym",
        "preference",
        "Gym flexibility",
        "Gym is flexible but important.",
    ),
)

_INITIALIZED_PATHS: set[str] = set()
_INIT_LOCK = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _database_path() -> str:
    return (
        os.getenv("APP_DB_PATH")
        or os.getenv("APP_DATABASE_PATH")
        or str(BACKEND_DIR / "personal_chief_of_staff.sqlite3")
    )


def _connect() -> sqlite3.Connection:
    path = _database_path()
    if path not in {":memory:", ""}:
        Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def ensure_database() -> None:
    path = _database_path()
    if path in _INITIALIZED_PATHS:
        return

    with _INIT_LOCK:
        if path in _INITIALIZED_PATHS:
            return

        with _connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_entries (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS habit_definitions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS habit_checkins (
                    id TEXT PRIMARY KEY,
                    habit_id TEXT,
                    habit TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('yes', 'no', 'partial')),
                    note TEXT,
                    timestamp TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (habit_id) REFERENCES habit_definitions(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS activity_logs (
                    id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT,
                    payload TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            _seed_default_habits(connection)
            _seed_default_memories(connection)

        _INITIALIZED_PATHS.add(path)


def _seed_default_habits(connection: sqlite3.Connection) -> None:
    now = _utc_now()
    for habit_id, name, description in DEFAULT_HABITS:
        connection.execute(
            """
            INSERT OR IGNORE INTO habit_definitions
                (id, name, description, enabled, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (habit_id, name, description, now, now),
        )


def _seed_default_memories(connection: sqlite3.Connection) -> None:
    now = _utc_now()
    for memory_id, memory_type, title, content in DEFAULT_MEMORIES:
        existing = connection.execute(
            """
            SELECT 1
            FROM memory_entries
            WHERE lower(type) = lower(?) AND lower(title) = lower(?)
            LIMIT 1
            """,
            (memory_type, title),
        ).fetchone()
        if existing:
            continue

        connection.execute(
            """
            INSERT OR IGNORE INTO memory_entries
                (id, type, title, content, confidence, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1.0, 1, ?, ?)
            """,
            (memory_id, memory_type, title, content, now, now),
        )


def _memory_from_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    item["confidence"] = float(item["confidence"])
    return item


def _habit_from_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    return item


def _activity_from_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    payload = item.get("payload")
    item["payload"] = json.loads(payload) if payload else None
    return item


def list_memory_entries() -> list[dict[str, Any]]:
    ensure_database()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, type, title, content, confidence, enabled, created_at, updated_at
            FROM memory_entries
            ORDER BY type COLLATE NOCASE, updated_at DESC
            """
        ).fetchall()
    return [_memory_from_row(row) for row in rows]


def create_memory_entry(
    *,
    type: str,
    title: str,
    content: str,
    confidence: float,
    enabled: bool = True,
) -> dict[str, Any]:
    ensure_database()
    now = _utc_now()
    memory_id = str(uuid.uuid4())
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO memory_entries
                (id, type, title, content, confidence, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                type,
                title,
                content,
                confidence,
                1 if enabled else 0,
                now,
                now,
            ),
        )
        row = connection.execute(
            """
            SELECT id, type, title, content, confidence, enabled, created_at, updated_at
            FROM memory_entries
            WHERE id = ?
            """,
            (memory_id,),
        ).fetchone()
    return _memory_from_row(row)


def update_memory_entry(memory_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    ensure_database()
    allowed = {"type", "title", "content", "confidence", "enabled"}
    changes = {key: value for key, value in updates.items() if key in allowed and value is not None}
    if not changes:
        return get_memory_entry(memory_id)

    changes["updated_at"] = _utc_now()
    if "enabled" in changes:
        changes["enabled"] = 1 if changes["enabled"] else 0

    assignments = ", ".join(f"{key} = ?" for key in changes)
    values = [*changes.values(), memory_id]
    with _connect() as connection:
        cursor = connection.execute(
            f"UPDATE memory_entries SET {assignments} WHERE id = ?",
            values,
        )
        if cursor.rowcount == 0:
            return None
        row = connection.execute(
            """
            SELECT id, type, title, content, confidence, enabled, created_at, updated_at
            FROM memory_entries
            WHERE id = ?
            """,
            (memory_id,),
        ).fetchone()
    return _memory_from_row(row)


def get_memory_entry(memory_id: str) -> dict[str, Any] | None:
    ensure_database()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT id, type, title, content, confidence, enabled, created_at, updated_at
            FROM memory_entries
            WHERE id = ?
            """,
            (memory_id,),
        ).fetchone()
    return _memory_from_row(row) if row else None


def delete_memory_entry(memory_id: str) -> bool:
    ensure_database()
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM memory_entries WHERE id = ?", (memory_id,))
    return cursor.rowcount > 0


def list_habits() -> list[dict[str, Any]]:
    ensure_database()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, name, description, enabled, created_at, updated_at
            FROM habit_definitions
            ORDER BY
                CASE id WHEN 'gym' THEN 0 WHEN 'running' THEN 1 WHEN 'work' THEN 2 ELSE 3 END,
                name COLLATE NOCASE
            """
        ).fetchall()
    return [_habit_from_row(row) for row in rows]


def create_habit(
    *,
    name: str,
    description: str = "",
    enabled: bool = True,
) -> dict[str, Any]:
    ensure_database()
    existing = get_habit(name)
    if existing:
        return existing

    now = _utc_now()
    habit_id = _slugify(name) or str(uuid.uuid4())
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO habit_definitions
                (id, name, description, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (habit_id, name, description, 1 if enabled else 0, now, now),
        )
        row = connection.execute(
            """
            SELECT id, name, description, enabled, created_at, updated_at
            FROM habit_definitions
            WHERE id = ?
            """,
            (habit_id,),
        ).fetchone()
    return _habit_from_row(row)


def update_habit(habit_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    ensure_database()
    allowed = {"name", "description", "enabled"}
    changes = {key: value for key, value in updates.items() if key in allowed and value is not None}
    if not changes:
        return get_habit(habit_id)

    changes["updated_at"] = _utc_now()
    if "enabled" in changes:
        changes["enabled"] = 1 if changes["enabled"] else 0

    assignments = ", ".join(f"{key} = ?" for key in changes)
    values = [*changes.values(), habit_id]
    with _connect() as connection:
        cursor = connection.execute(
            f"UPDATE habit_definitions SET {assignments} WHERE id = ?",
            values,
        )
        if cursor.rowcount == 0:
            return None
        row = connection.execute(
            """
            SELECT id, name, description, enabled, created_at, updated_at
            FROM habit_definitions
            WHERE id = ?
            """,
            (habit_id,),
        ).fetchone()
    return _habit_from_row(row)


def get_habit(habit_id_or_name: str) -> dict[str, Any] | None:
    ensure_database()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT id, name, description, enabled, created_at, updated_at
            FROM habit_definitions
            WHERE id = ? OR lower(name) = lower(?)
            """,
            (habit_id_or_name, habit_id_or_name),
        ).fetchone()
    return _habit_from_row(row) if row else None


def delete_habit(habit_id: str) -> bool:
    ensure_database()
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM habit_definitions WHERE id = ?", (habit_id,))
    return cursor.rowcount > 0


def list_habit_checkins(limit: int = 50) -> list[dict[str, Any]]:
    ensure_database()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, habit_id, habit, status, note, timestamp, created_at
            FROM habit_checkins
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def create_habit_checkin(
    *,
    habit: str,
    status: str,
    note: str | None,
    timestamp: str | None,
) -> dict[str, Any]:
    ensure_database()
    habit_record = get_habit(habit)
    if habit_record is None:
        raise ValueError("habit_not_found")

    checkin_id = str(uuid.uuid4())
    happened_at = timestamp or _utc_now()
    created_at = _utc_now()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO habit_checkins
                (id, habit_id, habit, status, note, timestamp, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                checkin_id,
                habit_record["id"],
                habit_record["name"],
                status,
                note,
                happened_at,
                created_at,
            ),
        )
        row = connection.execute(
            """
            SELECT id, habit_id, habit, status, note, timestamp, created_at
            FROM habit_checkins
            WHERE id = ?
            """,
            (checkin_id,),
        ).fetchone()
    return dict(row)


def list_activity(limit: int = 30) -> list[dict[str, Any]]:
    ensure_database()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, action_type, title, detail, payload, created_at
            FROM activity_logs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_activity_from_row(row) for row in rows]


def log_activity(
    *,
    action_type: str,
    title: str,
    detail: str | None = None,
    payload: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    ensure_database()
    activity_id = str(uuid.uuid4())
    happened_at = created_at or _utc_now()
    payload_text = json.dumps(payload, ensure_ascii=False) if payload is not None else None
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO activity_logs
                (id, action_type, title, detail, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (activity_id, action_type, title, detail, payload_text, happened_at),
        )
        row = connection.execute(
            """
            SELECT id, action_type, title, detail, payload, created_at
            FROM activity_logs
            WHERE id = ?
            """,
            (activity_id,),
        ).fetchone()
    return _activity_from_row(row)


def _slugify(value: str) -> str:
    text = value.strip().lower()
    chars = [character if character.isalnum() else "-" for character in text]
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug
