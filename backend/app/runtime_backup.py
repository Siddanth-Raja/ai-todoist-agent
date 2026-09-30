"""age ciphertext and authenticated manifests; local isolated vault adapter.

This adapter proves local behavior only. It is NOT OCI or the independent Mac
backup client. Remote generation safety requires its later conditional API gate.
"""
from __future__ import annotations
from contextlib import closing
from pathlib import Path
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import tempfile
import time
import uuid
from .runtime_store import RuntimeRefusal

MAX_DB = 250 * 1024 * 1024
MAX_VAULT = 3 * 1024**3  # Two environment vaults together fit the approved 6 GiB cap.
MIN_FREE = 20 * 1024**3
MAX_AGE = 7 * 86400


def canonical(value):
    return json.dumps(value, sort_keys=True,separators=(",",":")).encode()


def sign(value, key):
    return {"value":value,"mac":hmac.new(key,canonical(value),hashlib.sha256).hexdigest()}


def verified(envelope,key):
    expected = sign(envelope["value"],key)["mac"]
    if not hmac.compare_digest(envelope["mac"],expected):
        raise RuntimeRefusal("backup_manifest_authentication_failed")
    return envelope["value"]


def atomic(path, data):
    path = Path(path)
    if path.is_symlink():
        raise RuntimeRefusal("unsafe_backup_path")
    temporary = path.parent / (".partial-"+secrets.token_hex(12))
    try:
        fd = os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary,path)
        directory = os.open(path.parent,os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


class LocalVault:
    def __init__(self,path,environment_id,key, *, reserve=MIN_FREE, cap=MAX_VAULT):
        self.path = Path(path)
        self.environment_id = environment_id
        self.key = key
        self.reserve,self.cap = reserve,cap
        if len(key) != 32 or not self.path.is_dir() or self.path.is_symlink():
            raise RuntimeRefusal("vault_configuration_invalid")
        marker = self.path / "vault.json"
        expected = {"environment_id":environment_id,"kind":"synthetic-vault"}
        if marker.exists():
            if verified(json.loads(marker.read_text()),key) != expected:
                raise RuntimeRefusal("vault_environment_mismatch")
        else:
            if any(self.path.iterdir()):
                raise RuntimeRefusal("vault_not_empty")
            atomic(marker,canonical(sign(expected,key)))

    def capacity(self,extra=0):
        import shutil
        size = sum(p.stat().st_size for p in self.path.rglob("*") if p.is_file())
        if size+extra > self.cap or shutil.disk_usage(self.path).free-extra < self.reserve:
            raise RuntimeRefusal("backup_capacity_exhausted")

    def ledger(self):
        path = self.path / "suppression.json"
        if not path.exists():
            return {"environment_id":self.environment_id,"generation":0,"records":[]}
        value = verified(json.loads(path.read_text()),self.key)
        if value["environment_id"] != self.environment_id or [r["generation"] for r in value["records"]] != list(range(1,value["generation"]+1)):
            raise RuntimeRefusal("suppression_history_incomplete")
        return value

    def sync(self,store):
        """Read back contiguous history and delete affected copies BEFORE ack.

        A lost response leaves local ack pending; exact retry compares the ledger.
        All earlier snapshots are conservatively affected by a privacy operation.
        No upload/deletion is inside the local SQLite transaction.
        """
        if store.config.environment_id != self.environment_id:
            raise RuntimeRefusal("vault_environment_mismatch")
        with store.write_gate():
            with store.connection(readonly=True) as c:
                generation = c.execute("SELECT privacy_generation FROM runtime_metadata").fetchone()[0]
                records = [dict(r) for r in c.execute("SELECT * FROM runtime_suppression_outbox ORDER BY generation")]
            if [r["generation"] for r in records] != list(range(1,generation+1)):
                raise RuntimeRefusal("suppression_history_incomplete")
            current = self.ledger()
            if current["generation"] > generation or current["records"] != records[:current["generation"]]:
                raise RuntimeRefusal("suppression_history_diverged")
            target = {"environment_id":self.environment_id,"generation":generation,"records":records}
            data = canonical(sign(target,self.key))
            self.capacity(len(data))
            atomic(self.path / "suppression.json",data)
            if self.ledger() != target:
                raise RuntimeRefusal("suppression_readback_failed")
            self.rotate(min_generation=generation)
            with store.connection() as c:
                c.execute("UPDATE runtime_metadata SET synced_generation=? WHERE privacy_generation=?",(generation,generation))
            return generation

    def rotate(self, *, now=None,min_generation=0):
        now = time.time() if now is None else now
        records = []
        for path in self.path.glob("*.manifest.json"):
            value = verified(json.loads(path.read_text()),self.key)
            if value["environment_id"] != self.environment_id:
                raise RuntimeRefusal("backup_environment_mismatch")
            records.append((path,value))
        # Original age, including quarantined copies. No retention extension.
        retained = sorted(records,key=lambda pair:pair[1]["created_at"],reverse=True)
        daily = migration = 0
        for path,value in retained:
            keep = now-value["created_at"] < MAX_AGE and value["generation"] >= min_generation
            if value["kind"] == "daily":
                daily += 1
                keep &= daily <= 7
            elif value["kind"] == "pre-migration":
                migration += 1
                keep &= migration <= 1
            else:
                keep = False
            if not keep:
                (self.path / (value["backup_id"]+".age")).unlink(missing_ok=True)
                path.unlink()
        # Remove failed uploads/orphan ciphertext; never count them as success.
        ids = {p.name.removesuffix(".manifest.json") for p in self.path.glob("*.manifest.json")}
        for p in self.path.glob("*.age"):
            if p.stem not in ids:
                p.unlink()
        for p in self.path.glob(".partial-*"):
            p.unlink()
        self.capacity()

    def backup(self,store,recipient, *, kind="daily",now=None):
        import pyrage
        if kind not in {"daily","pre-migration"}:
            raise RuntimeRefusal("backup_kind_invalid")
        with store.write_gate():
            generation = self.sync(store)
            store.verify()
            backup_id = str(uuid.uuid4())
            fd,scratch = tempfile.mkstemp(prefix="backup-",suffix=".sqlite3",dir=store.config.root)
            os.close(fd)
            try:
                with closing(sqlite3.connect(scratch)) as destination, store.connection(readonly=True) as source:
                    source.backup(destination)
                    if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or destination.execute("PRAGMA foreign_key_check").fetchone():
                        raise RuntimeRefusal("backup_integrity_failure")
                if Path(scratch).stat().st_size > MAX_DB:
                    raise RuntimeRefusal("backup_too_large")
                plaintext = Path(scratch).read_bytes()
                ciphertext = pyrage.encrypt(plaintext,[pyrage.x25519.Recipient.from_str(recipient)])
            finally:
                Path(scratch).unlink(missing_ok=True)
            created = time.time() if now is None else now
            manifest = {"backup_id":backup_id,"environment_id":self.environment_id,"schema":15701,
                        "generation":generation,"created_at":created,"kind":kind,
                        "sha256":hashlib.sha256(ciphertext).hexdigest()}
            self.rotate(now=created,min_generation=generation)
            self.capacity(len(ciphertext)+len(canonical(manifest))+512)
            atomic(self.path / (backup_id+".age"),ciphertext)
            atomic(self.path / (backup_id+".manifest.json"),canonical(sign(manifest,self.key)))
            if verified(json.loads((self.path / (backup_id+".manifest.json")).read_text()),self.key) != manifest or hashlib.sha256((self.path / (backup_id+".age")).read_bytes()).hexdigest() != manifest["sha256"]:
                raise RuntimeRefusal("backup_readback_failed")
            self.rotate(now=created,min_generation=generation)
            with store.connection() as c:
                c.execute("INSERT OR REPLACE INTO runtime_backup_status VALUES (1,?)",(created,))
            return backup_id

    def quarantine(self):
        # Logical quarantine, not extra copies; restores still require live authority.
        atomic(self.path / "QUARANTINED",b"Historical restore blocked: complete history unavailable.\n")
        self.rotate()

    def restore(self,backup_id,identity,new_config,password_hash, *, authority=None):
        """Restore to a NEW isolated synthetic root; never over an active database.

        Authority must be a surviving verified RuntimeStore holding its exclusive
        lock. Never accept a caller-provided integer/old manifest as completeness.
        """
        import pyrage
        if authority is None:
            self.quarantine()
            raise RuntimeRefusal("historical_restore_quarantined")
        if new_config.root.exists() or new_config.environment_id == self.environment_id or not new_config.root.is_absolute():
            raise RuntimeRefusal("isolated_new_recovery_required")
        if (new_config.actor_id,new_config.workspace_id) != (authority.config.actor_id,authority.config.workspace_id):
            raise RuntimeRefusal("recovery_owner_mapping_mismatch")
        if str(uuid.UUID(backup_id)) != backup_id:
            raise RuntimeRefusal("backup_identity_invalid")
        try:
            authority.verify()
        except Exception:
            self.quarantine()
            raise RuntimeRefusal("historical_restore_quarantined") from None
        with authority.write_gate():
            authority.verify()
            if authority.config.environment_id != self.environment_id:
                raise RuntimeRefusal("restore_authority_mismatch")
            try:
                generation = self.sync(authority)
            except Exception:
                self.quarantine()
                raise
            value = verified(json.loads((self.path / (backup_id+".manifest.json")).read_text()),self.key)
            if value["environment_id"] != self.environment_id or value["schema"] != 15701 or value["generation"] != generation or time.time()-value["created_at"] >= MAX_AGE:
                self.quarantine()
                raise RuntimeRefusal("restore_suppression_or_age_mismatch")
            ciphertext = (self.path / (backup_id+".age")).read_bytes()
            if hashlib.sha256(ciphertext).hexdigest() != value["sha256"]:
                raise RuntimeRefusal("backup_checksum_failed")
            plaintext = pyrage.decrypt(ciphertext,[pyrage.x25519.Identity.from_str(identity)])
            if len(plaintext) > MAX_DB:
                raise RuntimeRefusal("backup_too_large")
            # Backup already includes all current suppressions; do not replay commands.
            from .runtime_store import bootstrap,RuntimeStore
            bootstrap(new_config,password_hash,recovery=True)
            atomic(new_config.database,plaintext)
            restored = RuntimeStore(new_config)
            restored.acquire()
            try:
                with restored.connection() as c:
                    c.execute("BEGIN IMMEDIATE")
                    c.execute("UPDATE runtime_metadata SET environment_id=?,recovery_capture_disabled=1",(new_config.environment_id,))
                    c.execute("UPDATE runtime_owner SET password_hash=?,auth_generation=?",(password_hash,str(uuid.uuid4())))
                    c.execute("DELETE FROM runtime_sessions")
                    c.execute("DELETE FROM runtime_login_limit")
                    # Retain recovered data bound to its original trusted owner/workspace.
                    if (new_config.actor_id,new_config.workspace_id) != (authority.config.actor_id,authority.config.workspace_id):
                        raise RuntimeRefusal("recovery_owner_mapping_mismatch")
                restored.install()
                restored.verify()
            finally:
                restored.close()
                authority.install()
            return new_config.root
