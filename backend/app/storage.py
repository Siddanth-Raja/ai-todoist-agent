from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import uuid
from typing import Any

from .activity_domain import (
    MeaningfulActivityEvent,
    activity_contract_projection,
    activity_event_payload,
)
from .config import BACKEND_DIR


DEFAULT_HABITS = (
    ("gym", "Gym", "Strength, gym, or workout session"),
    ("running", "Running", "Run, walk, or cardio session"),
    ("work", "Work", "Focused work or useful work block"),
)

DEFAULT_CANONICAL_PROJECTS = (
    {
        "id": "project-pcos-ai-todoist-agent",
        "key": "pcos-ai-todoist-agent",
        "display_name": "PCOS / ai todoist agent",
        "description": "Personal Chief of Staff system, Todoist agent, local app, and assistant behavior.",
        "sort_order": 10,
        "aliases": ("pcos", "ai-todoist-agent", "personal-chief-of-staff", "chief-of-staff"),
        "hints": (
            ("keyword", "pcos"),
            ("keyword", "personal chief of staff"),
            ("keyword", "chief of staff"),
            ("keyword", "ai todoist agent"),
            ("keyword", "todoist agent"),
            ("keyword", "agent api"),
            ("keyword", "assistant behavior"),
            ("keyword", "settings health"),
        ),
        "provider_mappings": (
            (
                "linear",
                "project",
                "8622937e-f05d-48b7-ba54-43604a8aa733",
                {"source": "sid-134"},
            ),
        ),
    },
    {
        "id": "project-nebulo",
        "key": "nebulo",
        "display_name": "Nebulo",
        "description": "AI context control, private storage, product work, and Brandon-related follow-through.",
        "sort_order": 20,
        "aliases": (),
        "hints": (
            ("life_area", "Nebulo"),
            ("keyword", "nebulo"),
            ("keyword", "brandon"),
            ("keyword", "context control"),
            ("keyword", "context-control"),
            ("keyword", "private storage"),
            ("person", "Brandon"),
        ),
        "provider_mappings": (
            ("todoist", "section", "Nebulo", None),
            (
                "linear",
                "project",
                "d9fdfe44-3e66-4dc0-b564-b2bcb646e635",
                {"source": "sid-134"},
            ),
        ),
    },
    {
        "id": "project-xo",
        "key": "xo",
        "display_name": "XO",
        "description": "VR, prototype, headset, worldbuilding, Ashwin, and Charlie.",
        "sort_order": 30,
        "aliases": (),
        "hints": (
            ("life_area", "XO"),
            ("keyword", "xo"),
            ("keyword", "xo collective"),
            ("keyword", "vr"),
            ("keyword", "headset"),
            ("keyword", "prototype"),
            ("keyword", "ashwin"),
            ("keyword", "charlie"),
            ("person", "Ashwin"),
            ("person", "Charlie"),
        ),
        "provider_mappings": (
            ("todoist", "section", "XO Collective", None),
            (
                "linear",
                "project",
                "6752d640-2f40-423f-b86f-ef11e0c4deda",
                {"source": "sid-134"},
            ),
        ),
    },
    {
        "id": "project-freelance",
        "key": "freelance",
        "display_name": "Freelance",
        "description": "Client outreach, websites, proposals, invoices, and delivery work.",
        "sort_order": 40,
        "aliases": (),
        "hints": (
            ("life_area", "Freelance"),
            ("keyword", "freelance"),
            ("keyword", "client"),
            ("keyword", "website"),
            ("keyword", "law firm"),
            ("keyword", "dentist"),
            ("keyword", "realtor"),
            ("keyword", "invoice"),
            ("keyword", "proposal"),
        ),
        "provider_mappings": (
            ("todoist", "section", "Freelance Web Design", None),
            (
                "linear",
                "project",
                "2bde590c-a8ab-4f4e-81eb-f7a8da8c1833",
                {"source": "sid-134"},
            ),
        ),
    },
    {
        "id": "project-am",
        "key": "am",
        "display_name": "A&M",
        "description": "College, TAMU, Blinn, housing, registration, classes, and roommate context.",
        "sort_order": 50,
        "aliases": ("aandm", "a-and-m", "tamu", "college"),
        "hints": (
            ("life_area", "A&M"),
            ("keyword", "a&m"),
            ("keyword", "a and m"),
            ("keyword", "tamu"),
            ("keyword", "blinn"),
            ("keyword", "college"),
            ("keyword", "housing"),
            ("keyword", "classes"),
            ("keyword", "nikhil"),
            ("keyword", "andy"),
            ("keyword", "kamden"),
            ("person", "Nikhil"),
            ("person", "Andy"),
            ("person", "Kamden"),
        ),
        "provider_mappings": (("todoist", "section", "College", None),),
    },
    {
        "id": "project-personal",
        "key": "personal",
        "display_name": "Personal",
        "description": "Gym, health, shopping, errands, car, family, and life admin.",
        "sort_order": 60,
        "aliases": (),
        "hints": (
            ("life_area", "Personal"),
            ("keyword", "personal"),
            ("keyword", "gym"),
            ("keyword", "health"),
            ("keyword", "shopping"),
            ("keyword", "target"),
            ("keyword", "errand"),
            ("keyword", "car"),
            ("keyword", "family"),
            ("keyword", "life admin"),
            ("keyword", "sam"),
            ("keyword", "jai"),
            ("keyword", "krrish"),
            ("person", "Sam"),
            ("person", "Jai"),
            ("person", "Krrish"),
        ),
        "provider_mappings": (("todoist", "section", "Personal", None),),
    },
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
        "Client outreach, websites, law firms, dentists, realtors, portfolio, invoices. Todoist section: Freelance Web Design.",
    ),
    (
        "memory-project-personal",
        "project",
        "Personal",
        "Gym, health, shopping, errands, car, family, life admin. Todoist section: Personal.",
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
        "Shopping/gym/health/car/life admin",
        "Shopping, gym, health, car, and life admin tasks go to Personal.",
    ),
    (
        "memory-rule-college",
        "classification_rule",
        "College/TAMU/Blinn",
        "College, TAMU, Blinn, housing, and classes tasks go to A&M.",
    ),
    (
        "memory-rule-xo",
        "classification_rule",
        "VR/headset/Ashwin/Charlie",
        "Ashwin, Charlie, VR, headset, and prototype tasks go to XO.",
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
        "memory-rule-ddn",
        "classification_rule",
        "DDN",
        "DDN can route to Freelance or Personal depending on the current intended project. If unclear, expose it as Needs Classification instead of hiding it.",
    ),
    (
        "memory-rule-misc",
        "classification_rule",
        "Misc fallback",
        "Unknown tasks go to Misc as fallback only.",
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


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


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

    connection = sqlite3.connect(path, factory=_ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def database_connection() -> sqlite3.Connection:
    """Open the shared application database after idempotent schema setup."""
    ensure_database()
    return _connect()


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
                    source TEXT NOT NULL DEFAULT 'app',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_focus_intents (
                    id TEXT PRIMARY KEY,
                    canonical_project_id TEXT NOT NULL,
                    confirmed_state TEXT NOT NULL CHECK(confirmed_state IN (
                        'active_momentum', 'waiting_external', 'intentionally_paused',
                        'dedicated_session_needed', 'quiet_possible_drift',
                        'recently_completed', 'insufficient_evidence'
                    )),
                    reason TEXT,
                    confirmed_at TEXT NOT NULL,
                    expires_at TEXT,
                    review_after TEXT,
                    review_trigger TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (canonical_project_id) REFERENCES canonical_projects(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_project_focus_intents_project_time
                    ON project_focus_intents(canonical_project_id, confirmed_at DESC);

                CREATE TABLE IF NOT EXISTS provider_change_scopes (
                    provider TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    canonical_project_id TEXT,
                    coverage_state TEXT NOT NULL,
                    diagnostic TEXT,
                    historical_coverage_start TEXT,
                    retained_from TEXT,
                    last_success_at TEXT,
                    observed_at TEXT NOT NULL,
                    observation_count INTEGER NOT NULL DEFAULT 0,
                    schema_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (provider, scope_id)
                );

                CREATE TABLE IF NOT EXISTS provider_record_checkpoints (
                    provider TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    provider_record_type TEXT NOT NULL,
                    provider_record_id TEXT NOT NULL,
                    canonical_project_id TEXT,
                    source_revision TEXT,
                    source_updated_at TEXT,
                    observed_at TEXT NOT NULL,
                    state_hash TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (
                        provider, scope_id, provider_record_type, provider_record_id
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_provider_record_checkpoints_project
                    ON provider_record_checkpoints(canonical_project_id, provider, scope_id);

                CREATE TABLE IF NOT EXISTS provider_change_events (
                    event_position INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE,
                    deduplication_key TEXT NOT NULL UNIQUE,
                    transition_category TEXT NOT NULL,
                    canonical_project_id TEXT,
                    provider TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    provider_record_type TEXT NOT NULL,
                    provider_record_id TEXT NOT NULL,
                    source_event_at TEXT,
                    source_updated_at TEXT,
                    observed_at TEXT NOT NULL,
                    effective_at TEXT NOT NULL,
                    time_basis TEXT NOT NULL,
                    before_json TEXT,
                    after_json TEXT,
                    evidence_json TEXT NOT NULL,
                    activity_id TEXT NOT NULL UNIQUE,
                    schema_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_provider_change_events_project_time
                    ON provider_change_events(canonical_project_id, effective_at DESC, event_position DESC);

                CREATE INDEX IF NOT EXISTS idx_provider_change_events_scope_time
                    ON provider_change_events(provider, scope_id, effective_at DESC, event_position DESC);

                CREATE TABLE IF NOT EXISTS provider_change_consumers (
                    consumer_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    acknowledged_effective_at TEXT NOT NULL,
                    acknowledged_event_position INTEGER NOT NULL,
                    acknowledged_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    PRIMARY KEY (consumer_id, provider, scope_id)
                );

                CREATE TABLE IF NOT EXISTS reality_confirmations (
                    id TEXT PRIMARY KEY,
                    reconciliation_id TEXT NOT NULL,
                    canonical_project_id TEXT NOT NULL,
                    selected_resolution_code TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK(outcome IN (
                        'handled', 'not_handled', 'waiting', 'review_only'
                    )),
                    confirming_actor TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL,
                    evidence_references_json TEXT NOT NULL,
                    evidence_version TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    schema_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_reality_confirmations_reconciliation
                    ON reality_confirmations(
                        canonical_project_id, reconciliation_id, confirmed_at DESC
                    );

                CREATE TABLE IF NOT EXISTS reality_confirmation_reversals (
                    confirmation_id TEXT PRIMARY KEY,
                    reversed_at TEXT NOT NULL,
                    reversed_by_actor TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    schema_version INTEGER NOT NULL,
                    FOREIGN KEY (confirmation_id) REFERENCES reality_confirmations(id)
                );

                CREATE TABLE IF NOT EXISTS morning_corrections (
                    id TEXT PRIMARY KEY,
                    correction_type TEXT NOT NULL CHECK(correction_type IN (
                        'already_done', 'not_today', 'wrong_context',
                        'waiting_on_someone', 'snooze'
                    )),
                    statement_id TEXT NOT NULL,
                    reconciliation_id TEXT,
                    reality_item_id TEXT,
                    synthesis_id TEXT NOT NULL,
                    canonical_project_id TEXT,
                    canonical_project_key TEXT,
                    work_provider TEXT,
                    work_provider_record_id TEXT,
                    source_provider TEXT,
                    source_provider_record_type TEXT,
                    source_provider_record_id TEXT,
                    evidence_references_json TEXT NOT NULL,
                    evidence_version TEXT NOT NULL,
                    prior_classification TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    correcting_actor TEXT NOT NULL,
                    attribution TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    effective_at TEXT NOT NULL,
                    expires_at TEXT,
                    review_at TEXT,
                    status TEXT NOT NULL CHECK(status IN ('active', 'superseded', 'reversed')),
                    supersedes_correction_id TEXT,
                    reversed_at TEXT,
                    reversed_by_actor TEXT,
                    reversal_idempotency_key TEXT UNIQUE,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    schema_version INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_morning_corrections_statement_time
                    ON morning_corrections(statement_id, created_at DESC, id ASC);

                CREATE INDEX IF NOT EXISTS idx_morning_corrections_reconciliation_time
                    ON morning_corrections(reconciliation_id, created_at DESC, id ASC);

                CREATE TABLE IF NOT EXISTS morning_provider_previews (
                    id TEXT PRIMARY KEY,
                    statement_id TEXT NOT NULL,
                    synthesis_id TEXT NOT NULL,
                    evidence_version TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    provider_record_type TEXT NOT NULL,
                    provider_record_id TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    previous_value_json TEXT,
                    proposed_value_json TEXT NOT NULL,
                    provider_revision TEXT,
                    requested_by_actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'ready', 'unsupported', 'confirmed', 'stale',
                        'succeeded', 'failed', 'uncertain'
                    )),
                    diagnostic TEXT,
                    confirmation_idempotency_key TEXT UNIQUE,
                    confirmed_by_actor TEXT,
                    confirmed_at TEXT,
                    result_reference TEXT,
                    request_idempotency_key TEXT NOT NULL UNIQUE,
                    schema_version INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_morning_provider_previews_statement_time
                    ON morning_provider_previews(statement_id, created_at DESC, id ASC);

                CREATE TABLE IF NOT EXISTS canonical_projects (
                    id TEXT PRIMARY KEY,
                    key TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 100,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS canonical_project_aliases (
                    project_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, normalized_alias),
                    FOREIGN KEY (project_id) REFERENCES canonical_projects(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS canonical_project_classification_hints (
                    project_id TEXT NOT NULL,
                    hint_type TEXT NOT NULL CHECK(hint_type IN ('life_area', 'keyword', 'person')),
                    value TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, hint_type, value),
                    FOREIGN KEY (project_id) REFERENCES canonical_projects(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS canonical_project_provider_mappings (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    provider_ref TEXT NOT NULL,
                    metadata TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (provider, resource_type, provider_ref),
                    FOREIGN KEY (project_id) REFERENCES canonical_projects(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS pending_actions (
                    id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL CHECK(action_type IN (
                        'create_todoist_task',
                        'create_todoist_subtask',
                        'create_many_todoist_tasks',
                        'create_many_todoist_subtasks',
                        'create_calendar_event',
                        'update_calendar_event',
                        'gmail_apply_label',
                        'gmail_remove_label',
                        'gmail_archive',
                        'gmail_restore_inbox',
                        'gmail_mark_read',
                        'gmail_mark_unread',
                        'gmail_create_label'
                    )),
                    schema_version INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    canonical_project_id TEXT,
                    provider TEXT NOT NULL CHECK(provider IN ('todoist', 'google_calendar', 'gmail')),
                    target_references TEXT NOT NULL,
                    confirmation_prompt TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    payload_fingerprint TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    session_id TEXT,
                    source TEXT NOT NULL,
                    source_ref TEXT,
                    lifecycle TEXT NOT NULL CHECK(lifecycle IN (
                        'pending', 'executing', 'succeeded', 'failed', 'cancelled',
                        'expired', 'outcome_unknown'
                    )),
                    version INTEGER NOT NULL DEFAULT 1,
                    proposed_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    confirmed_at TEXT,
                    execution_started_at TEXT,
                    completed_at TEXT,
                    expires_at TEXT,
                    result TEXT,
                    failure TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_pending_actions_session_state
                    ON pending_actions(session_id, lifecycle, proposed_at DESC);

                CREATE TABLE IF NOT EXISTS gmail_mutation_gate (
                    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                    authorized_scope TEXT,
                    approval_reference TEXT,
                    oauth_authorized_at TEXT,
                    canary_action_id TEXT,
                    canary_manifest_fingerprint TEXT,
                    canary_label_id TEXT,
                    canary_applied_at TEXT,
                    canary_undo_action_id TEXT,
                    canary_undo_verified_at TEXT,
                    provider_mutation_calls INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                """
            )
            _ensure_activity_columns(connection)
            _ensure_pending_action_contract(connection)
            _ensure_gmail_mutation_gate_columns(connection)
            _ensure_morning_provider_preview_columns(connection)
            _seed_default_habits(connection)
            _seed_default_memories(connection)
            _seed_default_canonical_projects(connection)

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


def _seed_default_canonical_projects(connection: sqlite3.Connection) -> None:
    now = _utc_now()
    for project in DEFAULT_CANONICAL_PROJECTS:
        connection.execute(
            """
            INSERT OR IGNORE INTO canonical_projects
                (id, key, display_name, description, enabled, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                project["id"],
                project["key"],
                project["display_name"],
                project["description"],
                project["sort_order"],
                now,
                now,
            ),
        )
        row = connection.execute(
            "SELECT id FROM canonical_projects WHERE key = ?",
            (project["key"],),
        ).fetchone()
        project_id = str(row["id"])

        for alias in project["aliases"]:
            connection.execute(
                """
                INSERT OR IGNORE INTO canonical_project_aliases
                    (project_id, alias, normalized_alias, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (project_id, alias, _normalize_project_reference(alias), now),
            )

        for hint_type, value in project["hints"]:
            connection.execute(
                """
                INSERT OR IGNORE INTO canonical_project_classification_hints
                    (project_id, hint_type, value, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (project_id, hint_type, value, now),
            )

        for provider, resource_type, provider_ref, metadata in project["provider_mappings"]:
            connection.execute(
                """
                INSERT OR IGNORE INTO canonical_project_provider_mappings
                    (id, project_id, provider, resource_type, provider_ref, metadata, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    f"mapping-{project['key']}-{provider}-{_slugify(resource_type)}-{_slugify(provider_ref)}",
                    project_id,
                    provider,
                    resource_type,
                    provider_ref,
                    json.dumps(metadata, ensure_ascii=False) if metadata is not None else None,
                    now,
                    now,
                ),
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
    metadata = json.loads(payload) if payload else None
    action_type = item.get("action_type")
    detail = item.get("detail")
    source = item.get("source") or "app"
    item["payload"] = metadata
    item["metadata"] = metadata
    item["type"] = action_type
    item["description"] = detail
    item["source"] = source
    return activity_contract_projection(item)


def _focus_intent_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _ensure_activity_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(activity_logs)").fetchall()
    }
    if "source" not in columns:
        connection.execute("ALTER TABLE activity_logs ADD COLUMN source TEXT NOT NULL DEFAULT 'app'")


def _ensure_pending_action_contract(connection: sqlite3.Connection) -> None:
    """Expand SID-150's closed action table without weakening stored contracts."""
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'pending_actions'"
    ).fetchone()
    schema = str(row["sql"] or "") if row else ""
    if "gmail_apply_label" in schema and "'gmail'" in schema:
        return

    connection.execute("DROP INDEX IF EXISTS idx_pending_actions_session_state")
    connection.execute("ALTER TABLE pending_actions RENAME TO pending_actions_sid150")
    connection.executescript(
        """
        CREATE TABLE pending_actions (
            id TEXT PRIMARY KEY,
            action_type TEXT NOT NULL CHECK(action_type IN (
                'create_todoist_task', 'create_todoist_subtask',
                'create_many_todoist_tasks', 'create_many_todoist_subtasks',
                'create_calendar_event', 'update_calendar_event',
                'gmail_apply_label', 'gmail_remove_label', 'gmail_archive',
                'gmail_restore_inbox', 'gmail_mark_read', 'gmail_mark_unread',
                'gmail_create_label'
            )),
            schema_version INTEGER NOT NULL,
            payload TEXT NOT NULL,
            canonical_project_id TEXT,
            provider TEXT NOT NULL CHECK(provider IN ('todoist', 'google_calendar', 'gmail')),
            target_references TEXT NOT NULL,
            confirmation_prompt TEXT NOT NULL,
            evidence TEXT NOT NULL,
            payload_fingerprint TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            session_id TEXT,
            source TEXT NOT NULL,
            source_ref TEXT,
            lifecycle TEXT NOT NULL CHECK(lifecycle IN (
                'pending', 'executing', 'succeeded', 'failed', 'cancelled',
                'expired', 'outcome_unknown'
            )),
            version INTEGER NOT NULL DEFAULT 1,
            proposed_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            confirmed_at TEXT,
            execution_started_at TEXT,
            completed_at TEXT,
            expires_at TEXT,
            result TEXT,
            failure TEXT
        );

        INSERT INTO pending_actions SELECT * FROM pending_actions_sid150;
        DROP TABLE pending_actions_sid150;
        CREATE INDEX idx_pending_actions_session_state
            ON pending_actions(session_id, lifecycle, proposed_at DESC);
        """
    )


def _ensure_gmail_mutation_gate_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(gmail_mutation_gate)").fetchall()
    }
    if "provider_mutation_calls" not in columns:
        connection.execute(
            """
            ALTER TABLE gmail_mutation_gate
            ADD COLUMN provider_mutation_calls INTEGER NOT NULL DEFAULT 0
            """
        )


def _ensure_morning_provider_preview_columns(connection: sqlite3.Connection) -> None:
    """Keep the additive SID-245 preview ledger readable across schema revisions."""
    columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(morning_provider_previews)"
        ).fetchall()
    }
    if "confirmed_by_actor" not in columns:
        connection.execute(
            "ALTER TABLE morning_provider_previews ADD COLUMN confirmed_by_actor TEXT"
        )


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


def list_activity(limit: int | None = 30) -> list[dict[str, Any]]:
    ensure_database()
    with _connect() as connection:
        if limit is None:
            rows = connection.execute(
                """
                SELECT id, action_type, title, detail, payload, source, created_at
                FROM activity_logs
                ORDER BY created_at DESC
                """
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT id, action_type, title, detail, payload, source, created_at
                FROM activity_logs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [_activity_from_row(row) for row in rows]


def log_activity(
    *,
    action_type: str | None = None,
    type: str | None = None,
    title: str,
    detail: str | None = None,
    description: str | None = None,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    source: str = "app",
    created_at: str | None = None,
) -> dict[str, Any]:
    ensure_database()
    activity_id = str(uuid.uuid4())
    activity_type = action_type or type
    if not activity_type:
        raise ValueError("activity type is required")
    activity_detail = detail if detail is not None else description
    activity_payload = payload if payload is not None else metadata
    happened_at = created_at or _utc_now()
    payload_text = json.dumps(activity_payload, ensure_ascii=False) if activity_payload is not None else None
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO activity_logs
                (id, action_type, title, detail, payload, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (activity_id, activity_type, title, activity_detail, payload_text, source, happened_at),
        )
        row = connection.execute(
            """
            SELECT id, action_type, title, detail, payload, source, created_at
            FROM activity_logs
            WHERE id = ?
            """,
            (activity_id,),
        ).fetchone()
    return _activity_from_row(row)


def log_meaningful_activity(event: MeaningfulActivityEvent) -> dict[str, Any]:
    return log_activity(
        action_type=event.category.value,
        title=event.summary,
        detail=None,
        source=event.source_provider,
        payload=activity_event_payload(event),
        created_at=event.observed_at.isoformat(),
    )


def save_project_focus_intent(
    *,
    canonical_project_id: str,
    confirmed_state: str,
    reason: str | None,
    confirmed_at: datetime,
    expires_at: datetime | None = None,
    review_after: datetime | None = None,
    review_trigger: str | None = None,
) -> dict[str, Any]:
    from .project_activity_focus import ExplicitProjectIntent

    ensure_database()
    intent_id = str(uuid.uuid4())
    validated = ExplicitProjectIntent(
        id=intent_id,
        canonical_project_id=canonical_project_id,
        confirmed_state=confirmed_state,
        reason=reason,
        confirmed_at=confirmed_at,
        expires_at=expires_at,
        review_after=review_after,
        review_trigger=review_trigger,
    )
    now = _utc_now()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO project_focus_intents
                (id, canonical_project_id, confirmed_state, reason, confirmed_at,
                 expires_at, review_after, review_trigger, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                validated.id,
                validated.canonical_project_id,
                validated.confirmed_state.value,
                validated.reason,
                validated.confirmed_at.isoformat(),
                validated.expires_at.isoformat() if validated.expires_at else None,
                validated.review_after.isoformat() if validated.review_after else None,
                validated.review_trigger,
                now,
                now,
            ),
        )
        row = connection.execute(
            "SELECT * FROM project_focus_intents WHERE id = ?",
            (intent_id,),
        ).fetchone()
    return _focus_intent_from_row(row)


def get_latest_project_focus_intent(
    canonical_project_id: str,
) -> dict[str, Any] | None:
    ensure_database()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM project_focus_intents
            WHERE canonical_project_id = ?
            ORDER BY confirmed_at DESC, created_at DESC
            LIMIT 1
            """,
            (canonical_project_id,),
        ).fetchone()
    return _focus_intent_from_row(row) if row else None


def list_canonical_projects(*, include_disabled: bool = False) -> list[dict[str, Any]]:
    ensure_database()
    where_clause = "" if include_disabled else "WHERE enabled = 1"
    with _connect() as connection:
        rows = connection.execute(
            f"""
            SELECT id, key, display_name, description, enabled, sort_order, created_at, updated_at
            FROM canonical_projects
            {where_clause}
            ORDER BY sort_order, display_name COLLATE NOCASE, key
            """
        ).fetchall()
        return [_canonical_project_from_row(connection, row) for row in rows]


def get_canonical_project(project_reference: str) -> dict[str, Any] | None:
    ensure_database()
    normalized_reference = _normalize_project_reference(project_reference)
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT DISTINCT p.id, p.key, p.display_name, p.description, p.enabled,
                p.sort_order, p.created_at, p.updated_at
            FROM canonical_projects p
            LEFT JOIN canonical_project_aliases a ON a.project_id = p.id
            WHERE p.id = ? OR p.key = ? OR a.normalized_alias = ?
            LIMIT 1
            """,
            (project_reference, normalized_reference, normalized_reference),
        ).fetchone()
        return _canonical_project_from_row(connection, row) if row else None


def create_canonical_project(
    *,
    key: str,
    display_name: str,
    description: str = "",
    enabled: bool = True,
    sort_order: int = 100,
    aliases: list[str] | tuple[str, ...] = (),
    classification_hints: list[dict[str, str]] | tuple[dict[str, str], ...] = (),
    provider_mappings: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    project_id: str | None = None,
) -> dict[str, Any]:
    ensure_database()
    canonical_key = _normalize_project_reference(key)
    if not canonical_key:
        raise ValueError("project key is required")
    if canonical_key == "needs-classification":
        raise ValueError("needs-classification is a system state")

    now = _utc_now()
    canonical_project_id = project_id or str(uuid.uuid4())
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO canonical_projects
                (id, key, display_name, description, enabled, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical_project_id,
                canonical_key,
                display_name,
                description,
                1 if enabled else 0,
                sort_order,
                now,
                now,
            ),
        )
        for alias in aliases:
            _insert_project_alias(connection, canonical_project_id, alias, now)
        for hint in classification_hints:
            _insert_project_hint(
                connection,
                canonical_project_id,
                str(hint.get("type") or ""),
                str(hint.get("value") or ""),
                now,
            )
        for mapping in provider_mappings:
            _insert_project_provider_mapping(
                connection,
                canonical_project_id,
                provider=str(mapping.get("provider") or ""),
                resource_type=str(mapping.get("resource_type") or ""),
                provider_ref=str(mapping.get("provider_ref") or ""),
                metadata=mapping.get("metadata"),
                enabled=bool(mapping.get("enabled", True)),
                now=now,
            )
        row = connection.execute(
            """
            SELECT id, key, display_name, description, enabled, sort_order, created_at, updated_at
            FROM canonical_projects
            WHERE id = ?
            """,
            (canonical_project_id,),
        ).fetchone()
        return _canonical_project_from_row(connection, row)


def update_canonical_project(project_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    ensure_database()
    allowed = {"display_name", "description", "enabled", "sort_order"}
    changes = {key: value for key, value in updates.items() if key in allowed and value is not None}
    if not changes:
        return get_canonical_project(project_id)
    if "enabled" in changes:
        changes["enabled"] = 1 if changes["enabled"] else 0
    changes["updated_at"] = _utc_now()
    assignments = ", ".join(f"{key} = ?" for key in changes)
    values = [*changes.values(), project_id]
    with _connect() as connection:
        cursor = connection.execute(
            f"UPDATE canonical_projects SET {assignments} WHERE id = ?",
            values,
        )
        if cursor.rowcount == 0:
            return None
        row = connection.execute(
            """
            SELECT id, key, display_name, description, enabled, sort_order, created_at, updated_at
            FROM canonical_projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()
        return _canonical_project_from_row(connection, row)


def add_canonical_project_alias(project_id: str, alias: str) -> dict[str, Any] | None:
    ensure_database()
    with _connect() as connection:
        if not _project_exists(connection, project_id):
            return None
        _insert_project_alias(connection, project_id, alias, _utc_now())
    return get_canonical_project(project_id)


def add_canonical_project_classification_hint(
    project_id: str,
    *,
    hint_type: str,
    value: str,
) -> dict[str, Any] | None:
    ensure_database()
    with _connect() as connection:
        if not _project_exists(connection, project_id):
            return None
        _insert_project_hint(connection, project_id, hint_type, value, _utc_now())
    return get_canonical_project(project_id)


def add_canonical_project_provider_mapping(
    project_id: str,
    *,
    provider: str,
    resource_type: str,
    provider_ref: str,
    metadata: dict[str, Any] | None = None,
    enabled: bool = True,
) -> dict[str, Any] | None:
    ensure_database()
    with _connect() as connection:
        if not _project_exists(connection, project_id):
            return None
        _insert_project_provider_mapping(
            connection,
            project_id,
            provider=provider,
            resource_type=resource_type,
            provider_ref=provider_ref,
            metadata=metadata,
            enabled=enabled,
            now=_utc_now(),
        )
    return get_canonical_project(project_id)


def get_canonical_project_provider_mapping(mapping_id: str) -> dict[str, Any] | None:
    ensure_database()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT id, project_id, provider, resource_type, provider_ref,
                metadata, enabled, created_at, updated_at
            FROM canonical_project_provider_mappings
            WHERE id = ?
            """,
            (mapping_id,),
        ).fetchone()
        return _canonical_project_provider_mapping_from_row(row) if row else None


def update_canonical_project_provider_mapping(
    mapping_id: str,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    """Update a durable provider mapping without changing source-defined seeds."""
    ensure_database()
    allowed = {
        "project_id",
        "provider",
        "resource_type",
        "provider_ref",
        "metadata",
        "enabled",
    }
    changes = {key: value for key, value in updates.items() if key in allowed}
    if not changes:
        return get_canonical_project_provider_mapping(mapping_id)

    for required in ("project_id", "provider", "resource_type", "provider_ref"):
        if required in changes and not str(changes[required] or "").strip():
            raise ValueError(f"{required} is required")
    if "metadata" in changes:
        metadata = changes["metadata"]
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be an object or null")
        changes["metadata"] = (
            json.dumps(metadata, ensure_ascii=False) if metadata is not None else None
        )
    if "enabled" in changes:
        changes["enabled"] = 1 if changes["enabled"] else 0
    changes["updated_at"] = _utc_now()
    assignments = ", ".join(f"{key} = ?" for key in changes)

    with _connect() as connection:
        if "project_id" in changes and not _project_exists(
            connection,
            str(changes["project_id"]),
        ):
            raise ValueError("unknown canonical project")
        cursor = connection.execute(
            f"""
            UPDATE canonical_project_provider_mappings
            SET {assignments}
            WHERE id = ?
            """,
            [*changes.values(), mapping_id],
        )
        if cursor.rowcount == 0:
            return None
        row = connection.execute(
            """
            SELECT id, project_id, provider, resource_type, provider_ref,
                metadata, enabled, created_at, updated_at
            FROM canonical_project_provider_mappings
            WHERE id = ?
            """,
            (mapping_id,),
        ).fetchone()
        return _canonical_project_provider_mapping_from_row(row)


def resolve_canonical_project_provider_mapping(
    *,
    provider: str,
    resource_type: str,
    provider_ref: str,
) -> dict[str, Any] | None:
    ensure_database()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT p.id, p.key, p.display_name, p.description, p.enabled,
                p.sort_order, p.created_at, p.updated_at
            FROM canonical_project_provider_mappings m
            JOIN canonical_projects p ON p.id = m.project_id
            WHERE lower(m.provider) = lower(?)
                AND lower(m.resource_type) = lower(?)
                AND m.provider_ref = ?
                AND m.enabled = 1
                AND p.enabled = 1
            LIMIT 1
            """,
            (provider, resource_type, provider_ref),
        ).fetchone()
        return _canonical_project_from_row(connection, row) if row else None


def _canonical_project_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> dict[str, Any]:
    project_id = str(row["id"])
    aliases = connection.execute(
        """
        SELECT alias, normalized_alias
        FROM canonical_project_aliases
        WHERE project_id = ?
        ORDER BY alias COLLATE NOCASE
        """,
        (project_id,),
    ).fetchall()
    hints = connection.execute(
        """
        SELECT hint_type, value
        FROM canonical_project_classification_hints
        WHERE project_id = ?
        ORDER BY hint_type, value COLLATE NOCASE
        """,
        (project_id,),
    ).fetchall()
    mappings = connection.execute(
        """
        SELECT id, provider, resource_type, provider_ref, metadata, enabled, created_at, updated_at
        FROM canonical_project_provider_mappings
        WHERE project_id = ?
        ORDER BY provider, resource_type, provider_ref
        """,
        (project_id,),
    ).fetchall()
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    item["aliases"] = [dict(alias) for alias in aliases]
    item["classification_hints"] = [
        {"type": hint["hint_type"], "value": hint["value"]}
        for hint in hints
    ]
    item["provider_mappings"] = []
    for mapping in mappings:
        provider_mapping = _canonical_project_provider_mapping_from_row(mapping)
        provider_mapping.pop("project_id", None)
        item["provider_mappings"].append(provider_mapping)
    return item


def _canonical_project_provider_mapping_from_row(
    row: sqlite3.Row,
) -> dict[str, Any]:
    provider_mapping = dict(row)
    provider_mapping["enabled"] = bool(provider_mapping["enabled"])
    provider_mapping["metadata"] = (
        json.loads(provider_mapping["metadata"])
        if provider_mapping.get("metadata")
        else None
    )
    return provider_mapping


def _project_exists(connection: sqlite3.Connection, project_id: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM canonical_projects WHERE id = ?",
        (project_id,),
    ).fetchone() is not None


def _insert_project_alias(
    connection: sqlite3.Connection,
    project_id: str,
    alias: str,
    now: str,
) -> None:
    normalized_alias = _normalize_project_reference(alias)
    if not normalized_alias:
        raise ValueError("project alias is required")
    connection.execute(
        """
        INSERT OR IGNORE INTO canonical_project_aliases
            (project_id, alias, normalized_alias, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (project_id, alias, normalized_alias, now),
    )


def _insert_project_hint(
    connection: sqlite3.Connection,
    project_id: str,
    hint_type: str,
    value: str,
    now: str,
) -> None:
    if hint_type not in {"life_area", "keyword", "person"}:
        raise ValueError("unsupported project classification hint type")
    if not value.strip():
        raise ValueError("project classification hint value is required")
    connection.execute(
        """
        INSERT OR IGNORE INTO canonical_project_classification_hints
            (project_id, hint_type, value, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (project_id, hint_type, value, now),
    )


def _insert_project_provider_mapping(
    connection: sqlite3.Connection,
    project_id: str,
    *,
    provider: str,
    resource_type: str,
    provider_ref: str,
    metadata: dict[str, Any] | None,
    enabled: bool,
    now: str,
) -> None:
    if not provider.strip() or not resource_type.strip() or not provider_ref.strip():
        raise ValueError("provider, resource_type, and provider_ref are required")
    mapping_id = str(uuid.uuid4())
    connection.execute(
        """
        INSERT INTO canonical_project_provider_mappings
            (id, project_id, provider, resource_type, provider_ref, metadata, enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            mapping_id,
            project_id,
            provider,
            resource_type,
            provider_ref,
            json.dumps(metadata, ensure_ascii=False) if metadata is not None else None,
            1 if enabled else 0,
            now,
            now,
        ),
    )


def _normalize_project_reference(value: str) -> str:
    text = value.lower().replace("&", " and ")
    text = text.replace("_", " ").replace("-", " ")
    return "-".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _slugify(value: str) -> str:
    text = value.strip().lower()
    chars = [character if character.isalnum() else "-" for character in text]
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug
