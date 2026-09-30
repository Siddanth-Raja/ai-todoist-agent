"""Local owner authentication. Sessions and explicit renewal share SQLite."""
from __future__ import annotations
import hashlib
import hmac
import secrets
import time
from .runtime_store import RuntimeRefusal


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hasher():
    from argon2 import PasswordHasher
    from argon2.low_level import Type
    return PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1, type=Type.ID)


class OwnerAuth:
    def __init__(self, store):
        self.store = store

    def login(self, password):
        from argon2.exceptions import VerificationError
        now = time.time()
        with self.store.write_gate():
            with self.store.connection() as c:
                c.execute("BEGIN IMMEDIATE")
                c.execute("DELETE FROM runtime_sessions WHERE absolute_until<=? OR idle_until<=?", (now, now))
                if c.execute("SELECT count(*) FROM runtime_sessions").fetchone()[0] >= 8:
                    raise RuntimeRefusal("session_limit_reached")
                limit = c.execute("SELECT window_start,attempts FROM runtime_login_limit WHERE singleton=1").fetchone()
                count = limit[1] if limit and now-limit[0] < 900 else 0
                start = limit[0] if count else now
                if count >= 5:
                    raise RuntimeRefusal("login_rate_limited")
                c.execute("INSERT OR REPLACE INTO runtime_login_limit VALUES (1,?,?)", (start, count+1))
                owner = c.execute("SELECT * FROM runtime_owner").fetchone()
            # Limit is durably consumed even when password verification fails.
            try:
                password_hasher().verify(owner["password_hash"], password)
            except (VerificationError, ValueError, TypeError):
                raise RuntimeRefusal("authentication_failed") from None
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            with self.store.connection() as c:
                c.execute("INSERT INTO runtime_sessions VALUES (?,?,?,?,?,?)",
                          (digest(token), digest(csrf), owner["auth_generation"], now, now+43200, now+604800))
            return token, csrf

    def verify(self, token, *, csrf=None):
        if not token:
            raise RuntimeRefusal("authentication_required")
        with self.store.connection(readonly=True) as c:
            row = c.execute("SELECT s.*,o.auth_generation AS current_generation FROM runtime_sessions s CROSS JOIN runtime_owner o WHERE s.token_hash=?", (digest(token),)).fetchone()
        now = time.time()
        if row is None or row["idle_until"] <= now or row["absolute_until"] <= now or row["auth_generation"] != row["current_generation"]:
            raise RuntimeRefusal("session_expired_or_revoked")
        if csrf is not None and not hmac.compare_digest(digest(csrf), row["csrf_hash"]):
            raise RuntimeRefusal("csrf_denied")
        return row

    def logout(self, token):
        with self.store.connection() as c:
            c.execute("DELETE FROM runtime_sessions WHERE token_hash=?", (digest(token),))

    def renew(self, token, csrf):
        row = self.verify(token, csrf=csrf)
        with self.store.connection() as c:
            c.execute("UPDATE runtime_sessions SET idle_until=? WHERE token_hash=?", (min(time.time()+43200, row["absolute_until"]), digest(token)))

    def reset(self, password_hash):
        # Administrative path only. Not an HTTP endpoint; destroys all sessions.
        import uuid
        with self.store.write_gate():
            with self.store.connection() as c:
                c.execute("BEGIN IMMEDIATE")
                c.execute("UPDATE runtime_owner SET password_hash=?,auth_generation=?", (password_hash,str(uuid.uuid4())))
                c.execute("DELETE FROM runtime_sessions")
