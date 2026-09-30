"""Provider-disabled synthetic runtime: one process, one durable SQLite owner.

No existing/canary database may be adopted. Bootstrap is an explicit operation;
normal startup verifies existing markers, schemas and durable fingerprint keys.
"""
from __future__ import annotations

from contextlib import contextmanager, closing
from dataclasses import dataclass
from pathlib import Path
import fcntl
import json
import os
import sqlite3
import threading
import uuid


class RuntimeRefusal(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeConfig:
    root: Path
    environment_id: str
    actor_id: str
    workspace_id: str
    origin: str = "http://127.0.0.1:8017"
    require_mount: bool = False

    @property
    def database(self):
        return self.root / "runtime.sqlite3"

    def validate(self):
        if not self.root.is_absolute() or self.root.is_symlink():
            raise RuntimeRefusal("invalid_storage_root")
        uuid.UUID(self.environment_id)
        if not self.actor_id.startswith("synthetic-") or not self.workspace_id.startswith("synthetic-"):
            raise RuntimeRefusal("synthetic_identity_required")
        if self.origin not in {"http://127.0.0.1:8017", "http://127.0.0.1:3017"}:
            # Hosted use is private HTTPS only; network configuration remains a gate.
            from urllib.parse import urlsplit
            parsed = urlsplit(self.origin)
            if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".ts.net") or parsed.path or parsed.query or parsed.fragment:
                raise RuntimeRefusal("private_origin_required")


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class RuntimeStore:
    def __init__(self, config: RuntimeConfig):
        config.validate()
        self.config = config
        self._lock_file = None
        self._previous_env = None
        self._gate = threading.RLock()
        self._queue = threading.BoundedSemaphore(16)
        self.accepting = False

    def marker(self):
        return {"environment_id": self.config.environment_id, "actor_id": self.config.actor_id,
                "workspace_id": self.config.workspace_id, "kind": "synthetic", "schema": 1}

    def validate_volume(self):
        root = self.config.root
        if not root.is_dir() or root.is_symlink() or (self.config.require_mount and not os.path.ismount(root.parent)):
            raise RuntimeRefusal("durable_volume_unavailable")
        if json.loads((root / "environment.json").read_text()) != self.marker():
            raise RuntimeRefusal("environment_mismatch")
        if self.config.database.is_symlink() or not self.config.database.is_file():
            raise RuntimeRefusal("database_missing")
        if self.config.database.stat().st_mode & 0o077:
            raise RuntimeRefusal("database_permissions")

    def acquire(self):
        self.validate_volume()
        if self._lock_file:
            raise RuntimeRefusal("already_owned")
        lock_path = self.config.root / "owner.lock"
        if lock_path.is_symlink():
            raise RuntimeRefusal("unsafe_lock")
        handle = open(lock_path, "a+b")
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise RuntimeRefusal("second_owner_refused") from None
        self._lock_file = handle

    def connection(self, *, readonly=False):
        self.validate_volume()
        if self._lock_file is None:
            raise RuntimeRefusal("owner_required")
        connection = sqlite3.connect(f"{self.config.database.as_uri()}?mode={'ro' if readonly else 'rw'}",
                                     uri=True, timeout=5, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute("PRAGMA secure_delete=ON")
        connection.execute("PRAGMA synchronous=FULL")
        if readonly:
            connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
            connection.close()
            raise RuntimeRefusal("unsafe_journal_mode")
        return connection

    @contextmanager
    def write_gate(self, *, maintenance=False):
        if not maintenance and not self.accepting:
            raise RuntimeRefusal("runtime_not_ready")
        if not self._queue.acquire(blocking=False):
            raise RuntimeRefusal("write_queue_full")
        try:
            with self._gate:
                if not maintenance and not self.accepting:
                    raise RuntimeRefusal("runtime_stopping")
                self.validate_volume()
                yield
        finally:
            self._queue.release()

    def install(self):
        if self._previous_env is None:
            self._previous_env = {key: os.environ.get(key) for key in ("APP_DB_PATH", "PCOS_SYNTHETIC_RUNTIME")}
        os.environ["PCOS_SYNTHETIC_RUNTIME"] = "1"
        from .storage import configure_runtime_connections
        os.environ["APP_DB_PATH"] = str(self.config.database)
        configure_runtime_connections(self.connection)

    def verify(self):
        with self.connection(readonly=True) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or connection.execute("PRAGMA foreign_key_check").fetchone():
                raise RuntimeRefusal("integrity_failure")
            row = connection.execute("SELECT * FROM runtime_metadata").fetchone()
            if row is None or row["schema_version"] != 1 or row["environment_id"] != self.config.environment_id:
                raise RuntimeRefusal("schema_or_environment_mismatch")
            if connection.execute("PRAGMA user_version").fetchone()[0] != 15701:
                raise RuntimeRefusal("unsupported_schema_rollback")
            if not connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='runtime_assessment_inputs'").fetchone():
                raise RuntimeRefusal("assessment_schema_missing")
            expected = {"runtime_context_privacy", "runtime_college_privacy", "runtime_college_privacy_retry"}
            found = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
            if not expected <= found:
                raise RuntimeRefusal("privacy_boundary_missing")
        from .conversation_context import SharedConversationContextService
        from .college_domain import CollegeDomainService
        SharedConversationContextService()
        CollegeDomainService()

    def start(self):
        self.acquire()
        try:
            self.install()
            self.verify()
            self.maintenance()
            self.accepting = True
        except Exception:
            self.close()
            raise

    def maintenance(self):
        from datetime import datetime, timezone
        from .conversation_context import SharedConversationContextService, ContextScope, CommandIdentity
        from .college_domain import CollegeDomainService, CollegeScope
        with self.write_gate(maintenance=True):
            with self.connection(readonly=True) as c:
                interrupted = c.execute("SELECT actor_id,workspace_id,assessment_id FROM college_assessments WHERE lifecycle IN ('queued','running')").fetchall()
                expired = c.execute("SELECT DISTINCT actor_id,workspace_id FROM raw_conversation_evidence WHERE content IS NOT NULL AND expires_at<=?", (datetime.now(timezone.utc).isoformat(),)).fetchall()
            domain = CollegeDomainService()
            for row in interrupted:
                domain.fail_assessment(CollegeScope(row["actor_id"], row["workspace_id"]), assessment_id=row["assessment_id"], code="interrupted", message="Explicit retry required after restart.", retryable=True)
            context = SharedConversationContextService()
            for row in expired:
                identity = str(uuid.uuid4())
                context.expire_raw_evidence(ContextScope(row["actor_id"], row["workspace_id"]), CommandIdentity(identity, identity), through=datetime.now(timezone.utc))
            with self.connection() as c:
                c.execute("DELETE FROM runtime_sessions WHERE absolute_until<=? OR idle_until<=?", (time_now(), time_now()))

    def diagnostics(self):
        with self.connection(readonly=True) as c:
            row = c.execute("SELECT privacy_generation,synced_generation,recovery_capture_disabled FROM runtime_metadata").fetchone()
            backup = c.execute("SELECT verified_at FROM runtime_backup_status WHERE singleton=1").fetchone()
            pending = c.execute("SELECT min(recorded_at) FROM runtime_suppression_outbox WHERE generation>?", (row[1],)).fetchone()[0]
        return {"ready": self.accepting, "backup_sanitation": "pending" if row[0] != row[1] else "synced",
                "capture_disabled_for_recovery": bool(row[2]),
                "backup_scope": "local_synthetic_vault_only",
                "last_backup_verified_at": backup[0] if backup else None,
                "pending_suppression_since": pending}

    def close(self):
        self.accepting = False
        with self._gate:
            if self._lock_file:
                from .storage import configure_runtime_connections
                configure_runtime_connections(None)
                fcntl.flock(self._lock_file, fcntl.LOCK_UN)
                self._lock_file.close()
                self._lock_file = None
            if self._previous_env is not None:
                for key, value in self._previous_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
                self._previous_env = None


def time_now():
    import time
    return time.time()


def bootstrap(config: RuntimeConfig, password_hash: str, *, recovery=False):
    """Explicit NEW synthetic storage only. Partial bootstrap is never adopted."""
    config.validate()
    root = config.root
    if config.require_mount and not os.path.ismount(root.parent):
        raise RuntimeRefusal("durable_volume_unavailable")
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    os.chmod(root, 0o700)
    (root / "environment.json").write_text(json.dumps(RuntimeStore(config).marker()))
    os.chmod(root / "environment.json", 0o600)
    fd = os.open(config.database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    store = RuntimeStore(config)
    store.acquire()
    store.install()
    try:
        from .conversation_context import SharedConversationContextService
        from .college_domain import CollegeDomainService
        SharedConversationContextService.initialize_schema()
        CollegeDomainService.initialize_schema()
        with store.connection() as c:
            c.executescript('''
            CREATE TABLE runtime_metadata(environment_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
                privacy_generation INTEGER NOT NULL DEFAULT 0, synced_generation INTEGER NOT NULL DEFAULT 0,
                recovery_capture_disabled INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE runtime_assessment_inputs(command_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
                request_hash TEXT NOT NULL, snapshot_id TEXT NOT NULL, snapshot_version TEXT NOT NULL,
                context_generation INTEGER NOT NULL);
            CREATE TABLE runtime_owner(password_hash TEXT NOT NULL, auth_generation TEXT NOT NULL);
            CREATE TABLE runtime_sessions(token_hash TEXT PRIMARY KEY, csrf_hash TEXT NOT NULL, auth_generation TEXT NOT NULL,
                created_at REAL NOT NULL, idle_until REAL NOT NULL, absolute_until REAL NOT NULL);
            CREATE TABLE runtime_login_limit(singleton INTEGER PRIMARY KEY CHECK(singleton=1), window_start REAL NOT NULL, attempts INTEGER NOT NULL);
            CREATE TABLE runtime_backup_status(singleton INTEGER PRIMARY KEY CHECK(singleton=1), verified_at REAL NOT NULL);
            CREATE TABLE runtime_suppression_outbox(generation INTEGER PRIMARY KEY, receipt_id TEXT UNIQUE NOT NULL,
                kind TEXT NOT NULL, recorded_at TEXT NOT NULL);
            CREATE TRIGGER runtime_context_privacy AFTER INSERT ON context_command_receipts
            WHEN NEW.state IN ('applied','needs_review') AND NEW.command_kind IN ('revoke_capture_consent','forget_context','remove_raw_evidence','expire_raw_evidence')
            BEGIN
                UPDATE runtime_metadata SET privacy_generation=privacy_generation+1;
                INSERT INTO runtime_suppression_outbox SELECT privacy_generation,NEW.receipt_id,NEW.command_kind,NEW.recorded_at FROM runtime_metadata;
            END;
            CREATE TRIGGER runtime_college_privacy AFTER INSERT ON college_receipts
            WHEN NEW.state IN ('applied','needs_review') AND NEW.operation IN ('forget_claim','remove_raw_evidence','undo_update')
            BEGIN
                UPDATE runtime_metadata SET privacy_generation=privacy_generation+1;
                INSERT INTO runtime_suppression_outbox SELECT privacy_generation,NEW.receipt_id,NEW.operation,NEW.recorded_at FROM runtime_metadata;
            END;
            CREATE TRIGGER runtime_college_privacy_retry AFTER UPDATE OF state ON college_receipts
            WHEN NEW.state IN ('applied','needs_review') AND OLD.state NOT IN ('applied','needs_review')
              AND NEW.operation IN ('forget_claim','remove_raw_evidence','undo_update')
              AND NOT EXISTS(SELECT 1 FROM runtime_suppression_outbox WHERE receipt_id=NEW.receipt_id)
            BEGIN
                UPDATE runtime_metadata SET privacy_generation=privacy_generation+1;
                INSERT INTO runtime_suppression_outbox SELECT privacy_generation,NEW.receipt_id,NEW.operation,NEW.recorded_at FROM runtime_metadata;
            END;
            PRAGMA user_version=15701;
            ''')
            c.execute("INSERT INTO runtime_metadata VALUES (?,1,0,0,?)", (config.environment_id, int(recovery)))
            c.execute("INSERT INTO runtime_owner VALUES (?,?)", (password_hash, str(uuid.uuid4())))
        store.verify()
    finally:
        store.close()
