"""Persistent, destination-scoped serialization and uncertain-write protection."""
import fcntl
import hashlib
import sqlite3
from pathlib import Path

from services.patient_service import PatientLookupError, PatientMatchConflictError


class VacdImportGuard:
    def __init__(self, path, destination, document_key, content_hash):
        self.path = Path(path)
        self.destination = hashlib.sha256(destination.encode()).hexdigest()
        self.document_key = hashlib.sha256(document_key.encode()).hexdigest()
        self.content_hash = content_hash
        self.completed = False

    def __enter__(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.lock = (self.path.parent / f"vacd-{self.destination}.lock").open("a")
            fcntl.flock(self.lock, fcntl.LOCK_EX)
            self.db = sqlite3.connect(self.path, timeout=60)
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS vacd_imports ("
                "destination TEXT, document_key TEXT, content_hash TEXT NOT NULL, "
                "state TEXT NOT NULL, PRIMARY KEY(destination, document_key))"
            )
            uncertain = self.db.execute(
                "SELECT 1 FROM vacd_imports WHERE destination=? AND state != 'completed' LIMIT 1",
                (self.destination,),
            ).fetchone()
            if uncertain:
                raise PatientMatchConflictError(
                    "Previous VACD write has an uncertain outcome; reconcile with destination before retry"
                )
            row = self.db.execute(
                "SELECT content_hash, state FROM vacd_imports "
                "WHERE destination=? AND document_key=?",
                (self.destination, self.document_key),
            ).fetchone()
            if row:
                if row[0] != self.content_hash:
                    raise PatientMatchConflictError(
                        "CDA document identity was reused with different content; manual review required"
                    )
                self.completed = True
            elif self.db.execute(
                "SELECT 1 FROM vacd_imports WHERE destination=? "
                "AND content_hash=? AND state='completed' LIMIT 1",
                (self.destination, self.content_hash),
            ).fetchone():
                # Older imports used generated VACD document UUIDs as keys.
                self.completed = True
            return self
        except (OSError, sqlite3.Error) as ex:
            self.__exit__(None, None, None)
            raise PatientLookupError("VACD import register unavailable; send blocked") from ex
        except Exception:
            self.__exit__(None, None, None)
            raise

    def record(self, state):
        try:
            with self.db:
                self.db.execute(
                    "INSERT OR REPLACE INTO vacd_imports VALUES (?, ?, ?, ?)",
                    (self.destination, self.document_key, self.content_hash, state),
                )
        except sqlite3.Error as ex:
            raise PatientLookupError("VACD import register unavailable; send blocked") from ex

    def clear(self):
        try:
            with self.db:
                self.db.execute(
                    "DELETE FROM vacd_imports WHERE destination=? AND document_key=?",
                    (self.destination, self.document_key),
                )
        except sqlite3.Error as ex:
            raise PatientLookupError("VACD import register unavailable; send blocked") from ex

    def __exit__(self, *args):
        if hasattr(self, "db"):
            self.db.close()
        if hasattr(self, "lock"):
            self.lock.close()
