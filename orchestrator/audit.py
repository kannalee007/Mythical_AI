"""Audit logging for orchestrator lifecycle events."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from orchestrator.utils import console


@dataclass
class AuditConfig:
    """Runtime settings for audit logging."""

    enabled: bool
    log_file: str
    include_plan: bool
    max_plan_chars: int
    max_output_chars: int
    redact_patterns: list[str]
    redact_replacement: str
    hmac_key_env: str
    hmac_key: str
    sqlite_enabled: bool
    sqlite_path: str


class AuditLogger:
    """Append structured audit events to a JSONL log file."""

    def __init__(self, config: AuditConfig, tenant_id: Optional[str] = None):
        self._config = config
        self._tenant_id = tenant_id
        self._hmac_key = self._resolve_hmac_key()
        self._index = AuditIndex(self._config.sqlite_path) if self._config.sqlite_enabled else None
        self._last_hash = None
        if self._index:
            self._last_hash = self._index.get_last_hash()
        if not self._last_hash:
            self._last_hash = self._load_last_hash_from_file()
        if not self._last_hash:
            self._last_hash = "GENESIS"

    @classmethod
    def from_config(cls, config: dict, tenant_id: Optional[str] = None) -> "AuditLogger":
        audit_cfg = config.get("audit", {})
        cfg = AuditConfig(
            enabled=bool(audit_cfg.get("enabled", True)),
            log_file=str(audit_cfg.get("log_file", "audit_events.log")),
            include_plan=bool(audit_cfg.get("include_plan", False)),
            max_plan_chars=int(audit_cfg.get("max_plan_chars", 2000)),
            max_output_chars=int(audit_cfg.get("max_output_chars", 2000)),
            redact_patterns=list(audit_cfg.get("redact_patterns", [])),
            redact_replacement=str(audit_cfg.get("redact_replacement", "[REDACTED]")),
            hmac_key_env=str(audit_cfg.get("hmac_key_env", "")),
            hmac_key=str(audit_cfg.get("hmac_key", "")),
            sqlite_enabled=bool(audit_cfg.get("sqlite", {}).get("enabled", True)),
            sqlite_path=str(audit_cfg.get("sqlite", {}).get("path", "audit_events.sqlite3")),
        )
        return cls(cfg, tenant_id=tenant_id)

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def log_event(
        self,
        event_type: str,
        task_id: str,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        if not self._config.enabled:
            return

        cleaned_data = self._redact_data(data or {})
        prev_hash = self._last_hash or "GENESIS"
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "task_id": task_id,
            "tenant_id": self._tenant_id,
            "data": cleaned_data,
        }
        event_hash, event_hmac = self._compute_hash(entry, prev_hash)
        entry["prev_hash"] = prev_hash
        entry["hash"] = event_hash
        if event_hmac:
            entry["hmac"] = event_hmac

        path = os.path.abspath(self._config.log_file)
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        try:
            fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, default=str) + "\n")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except OSError as exc:
            console.print(f"[yellow]Audit log write failed: {exc}[/yellow]")
            return

        self._last_hash = event_hash
        if self._index:
            try:
                self._index.insert_event(entry)
            except OSError as exc:
                console.print(f"[yellow]Audit index write failed: {exc}[/yellow]")

    def trim_text(self, text: str, limit: Optional[int] = None) -> str:
        cap = limit if limit is not None else self._config.max_output_chars
        if len(text) <= cap:
            return text
        return text[:cap] + "..."

    def maybe_include_plan(self, plan: str) -> Optional[str]:
        if not self._config.include_plan:
            return None
        return self.trim_text(plan, self._config.max_plan_chars)

    def _resolve_hmac_key(self) -> Optional[str]:
        env_key = self._config.hmac_key_env
        if env_key:
            value = os.environ.get(env_key)
            if value:
                return value
        if self._config.hmac_key:
            return self._config.hmac_key
        return None

    def _compute_hash(self, entry: dict[str, Any], prev_hash: str) -> tuple[str, Optional[str]]:
        payload = {
            "timestamp": entry.get("timestamp"),
            "event_type": entry.get("event_type"),
            "task_id": entry.get("task_id"),
            "tenant_id": entry.get("tenant_id"),
            "data": entry.get("data"),
            "prev_hash": prev_hash,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if not self._hmac_key:
            return digest, None
        signature = hmac.new(
            self._hmac_key.encode("utf-8"),
            digest.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return digest, signature

    def _load_last_hash_from_file(self) -> Optional[str]:
        path = os.path.abspath(self._config.log_file)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - 65536))
                chunk = handle.read().decode("utf-8", errors="ignore")
        except OSError:
            return None

        lines = [line for line in chunk.splitlines() if line.strip()]
        if not lines:
            return None
        with suppress(json.JSONDecodeError):
            record = json.loads(lines[-1])
            return record.get("hash")
        return None

    def _redact_data(self, payload: Any) -> Any:
        if payload is None:
            return None
        if isinstance(payload, str):
            return self._redact_text(payload)
        if isinstance(payload, list):
            return [self._redact_data(item) for item in payload]
        if isinstance(payload, dict):
            return {key: self._redact_data(value) for key, value in payload.items()}
        return payload

    def _redact_text(self, text: str) -> str:
        redacted = text
        for pattern in self._config.redact_patterns:
            try:
                compiled = re.compile(pattern)
            except re.error:
                continue

            def _mask(match: re.Match[str]) -> str:
                value = match.group(0)
                for sep in ("=", ":"):
                    if sep in value:
                        prefix = value.split(sep, 1)[0]
                        return f"{prefix}{sep}{self._config.redact_replacement}"
                return self._config.redact_replacement

            redacted = compiled.sub(_mask, redacted)

        return redacted


class AuditIndex:
    """SQLite index for audit events and task summaries."""

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._ensure_schema()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    event_type TEXT,
                    task_id TEXT,
                    tenant_id TEXT,
                    data_json TEXT,
                    prev_hash TEXT,
                    hash TEXT,
                    hmac TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_audit_events_task ON audit_events(task_id);
                CREATE INDEX IF NOT EXISTS idx_audit_events_time ON audit_events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_audit_events_type ON audit_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_audit_events_tenant ON audit_events(tenant_id);

                CREATE TABLE IF NOT EXISTS audit_tasks (
                    task_id TEXT PRIMARY KEY,
                    tenant_id TEXT,
                    request TEXT,
                    intent TEXT,
                    tags_json TEXT,
                    target_file TEXT,
                    status TEXT,
                    success INTEGER,
                    blocked_reason TEXT,
                    started_at TEXT,
                    updated_at TEXT,
                    artifacts_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_audit_tasks_time ON audit_tasks(updated_at);
                CREATE INDEX IF NOT EXISTS idx_audit_tasks_tenant ON audit_tasks(tenant_id);

                CREATE TABLE IF NOT EXISTS audit_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                """
            )

    def get_last_hash(self) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM audit_meta WHERE key = 'last_hash'"
            ).fetchone()
            return row["value"] if row else None

    def insert_event(self, entry: dict[str, Any]) -> None:
        data_json = json.dumps(entry.get("data", {}), default=str)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (
                    timestamp, event_type, task_id, tenant_id,
                    data_json, prev_hash, hash, hmac
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.get("timestamp"),
                    entry.get("event_type"),
                    entry.get("task_id"),
                    entry.get("tenant_id"),
                    data_json,
                    entry.get("prev_hash"),
                    entry.get("hash"),
                    entry.get("hmac"),
                ),
            )
            self._update_task(conn, entry)
            conn.execute(
                "INSERT OR REPLACE INTO audit_meta (key, value) VALUES ('last_hash', ?)",
                (entry.get("hash"),),
            )

    def list_events(
        self,
        tenant_id: Optional[str] = None,
        task_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if tenant_id:
            clauses.append("tenant_id = ?")
            params.append(tenant_id)
        if task_id:
            clauses.append("task_id = ?")
            params.append(task_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit_clause = ""
        if limit is not None:
            limit_clause = "LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        query = (
            "SELECT timestamp, event_type, task_id, tenant_id, data_json, prev_hash, hash, hmac "
            "FROM audit_events "
            f"{where} ORDER BY id DESC {limit_clause}"
        )
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            data = {}
            with suppress(json.JSONDecodeError):
                data = json.loads(row["data_json"] or "{}")
            results.append(
                {
                    "timestamp": row["timestamp"],
                    "event_type": row["event_type"],
                    "task_id": row["task_id"],
                    "tenant_id": row["tenant_id"],
                    "data": data,
                    "prev_hash": row["prev_hash"],
                    "hash": row["hash"],
                    "hmac": row["hmac"],
                }
            )

        return results

    def count_events(self, tenant_id: Optional[str] = None, task_id: Optional[str] = None) -> int:
        clauses = []
        params: list[Any] = []
        if tenant_id:
            clauses.append("tenant_id = ?")
            params.append(tenant_id)
        if task_id:
            clauses.append("task_id = ?")
            params.append(task_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT COUNT(*) as total FROM audit_events {where}"
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
            return int(row["total"] if row else 0)

    def list_tasks(
        self,
        tenant_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if tenant_id:
            clauses.append("tenant_id = ?")
            params.append(tenant_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = (
            "SELECT * FROM audit_tasks "
            f"{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_task(row) for row in rows]

    def count_tasks(self, tenant_id: Optional[str] = None) -> int:
        clauses = []
        params: list[Any] = []
        if tenant_id:
            clauses.append("tenant_id = ?")
            params.append(tenant_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) as total FROM audit_tasks {where}", params).fetchone()
            return int(row["total"] if row else 0)

    def summarize_tasks(self, tenant_id: Optional[str] = None) -> dict[str, int]:
        clauses = []
        params: list[Any] = []
        if tenant_id:
            clauses.append("tenant_id = ?")
            params.append(tenant_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT status, COUNT(*) as count FROM audit_tasks {where} GROUP BY status"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return {row["status"]: int(row["count"]) for row in rows}

    def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM audit_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return self._row_to_task(row) if row else None

    def _row_to_task(self, row: sqlite3.Row) -> dict[str, Any]:
        tags = []
        artifacts = []
        with suppress(json.JSONDecodeError):
            tags = json.loads(row["tags_json"] or "[]")
        with suppress(json.JSONDecodeError):
            artifacts = json.loads(row["artifacts_json"] or "[]")

        return {
            "task_id": row["task_id"],
            "tenant_id": row["tenant_id"],
            "request": row["request"],
            "intent": row["intent"],
            "tags": tags,
            "target_file": row["target_file"],
            "status": row["status"],
            "success": row["success"],
            "blocked_reason": row["blocked_reason"],
            "started_at": row["started_at"],
            "updated_at": row["updated_at"],
            "artifacts": artifacts,
        }

    def _update_task(self, conn: sqlite3.Connection, entry: dict[str, Any]) -> None:
        task_id = entry.get("task_id")
        if not task_id:
            return

        row = conn.execute(
            "SELECT * FROM audit_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        task = self._row_to_task(row) if row else {
            "task_id": task_id,
            "tenant_id": entry.get("tenant_id") or "default",
            "request": "",
            "intent": "",
            "tags": [],
            "target_file": "",
            "status": "UNKNOWN",
            "success": None,
            "blocked_reason": "",
            "started_at": entry.get("timestamp"),
            "updated_at": entry.get("timestamp"),
            "artifacts": [],
        }

        event_type = entry.get("event_type")
        data = entry.get("data", {})
        if event_type == "task_started":
            task["request"] = data.get("request", task.get("request", ""))
            task["started_at"] = entry.get("timestamp")
        elif event_type == "plan_generated":
            task["intent"] = data.get("intent", task.get("intent", ""))
            task["tags"] = data.get("tags", task.get("tags", []))
            task["target_file"] = data.get("target_file", task.get("target_file", ""))
        elif event_type == "task_blocked":
            task["status"] = "BLOCKED"
            task["blocked_reason"] = data.get("reason", "")
            task["success"] = 0
        elif event_type == "task_completed":
            task["status"] = data.get("status", "UNKNOWN")
            task["success"] = 1 if data.get("success") else 0
            task["artifacts"] = data.get("artifacts", [])

        task["updated_at"] = entry.get("timestamp")

        conn.execute(
            """
            INSERT INTO audit_tasks (
                task_id, tenant_id, request, intent, tags_json, target_file,
                status, success, blocked_reason, started_at, updated_at, artifacts_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                tenant_id = excluded.tenant_id,
                request = excluded.request,
                intent = excluded.intent,
                tags_json = excluded.tags_json,
                target_file = excluded.target_file,
                status = excluded.status,
                success = excluded.success,
                blocked_reason = excluded.blocked_reason,
                started_at = excluded.started_at,
                updated_at = excluded.updated_at,
                artifacts_json = excluded.artifacts_json
            """,
            (
                task["task_id"],
                task.get("tenant_id") or "default",
                task.get("request"),
                task.get("intent"),
                json.dumps(task.get("tags", [])),
                task.get("target_file"),
                task.get("status"),
                task.get("success"),
                task.get("blocked_reason"),
                task.get("started_at"),
                task.get("updated_at"),
                json.dumps(task.get("artifacts", [])),
            ),
        )
