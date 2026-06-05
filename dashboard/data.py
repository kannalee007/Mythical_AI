"""Audit log parsing and dashboard helpers."""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from datetime import datetime
from typing import Any

import yaml


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def discover_audit_logs(base_dir: str, config_path: str) -> list[dict[str, str]]:
    config = load_config(config_path)
    audit_cfg = config.get("audit", {})
    logs = []

    default_log = str(audit_cfg.get("log_file", "audit_events.log"))
    logs.append({"tenant_id": "default", "path": os.path.abspath(default_log)})

    tenants_dir = os.path.join(base_dir, ".tenants")
    if os.path.isdir(tenants_dir):
        for name in sorted(os.listdir(tenants_dir)):
            tenant_path = os.path.join(tenants_dir, name)
            audit_path = os.path.join(tenant_path, "audit", "audit_events.log")
            logs.append({"tenant_id": name, "path": audit_path})

    return logs


def discover_audit_stores(base_dir: str, config_path: str) -> list[dict[str, str]]:
    config = load_config(config_path)
    audit_cfg = config.get("audit", {})
    sqlite_cfg = audit_cfg.get("sqlite", {})
    stores = []

    default_path = str(sqlite_cfg.get("path", "audit_events.sqlite3"))
    stores.append({"tenant_id": "default", "path": os.path.abspath(default_path)})

    tenants_dir = os.path.join(base_dir, ".tenants")
    if os.path.isdir(tenants_dir):
        for name in sorted(os.listdir(tenants_dir)):
            tenant_path = os.path.join(tenants_dir, name)
            store_path = os.path.join(tenant_path, "audit", "audit_events.sqlite3")
            stores.append({"tenant_id": name, "path": store_path})

    return stores


def read_events(
    log_path: str,
    limit: int | None = None,
    offset: int = 0,
    sqlite_path: str | None = None,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    if sqlite_path and os.path.exists(sqlite_path):
        return _read_events_sqlite(sqlite_path, limit=limit, offset=offset, task_id=task_id)

    if not os.path.exists(log_path):
        return []

    events: list[dict[str, Any]] = []
    with open(log_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if limit is not None:
        return events[-limit:]
    return events


def build_task_index(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    tasks: dict[str, dict[str, Any]] = {}

    for event in events:
        task_id = event.get("task_id")
        if not task_id:
            continue
        task = tasks.setdefault(
            task_id,
            {
                "task_id": task_id,
                "tenant_id": event.get("tenant_id") or "default",
                "request": "",
                "intent": "",
                "tags": [],
                "target_file": "",
                "status": "UNKNOWN",
                "success": None,
                "blocked_reason": "",
                "started_at": event.get("timestamp"),
                "updated_at": event.get("timestamp"),
                "artifacts": [],
            },
        )
        task["updated_at"] = event.get("timestamp")

        event_type = event.get("event_type")
        data = event.get("data", {})

        if event_type == "task_started":
            task["request"] = data.get("request", "")
        elif event_type == "plan_generated":
            task["intent"] = data.get("intent", "")
            task["tags"] = data.get("tags", [])
            task["target_file"] = data.get("target_file", "")
        elif event_type == "task_blocked":
            task["status"] = "BLOCKED"
            task["blocked_reason"] = data.get("reason", "")
            task["success"] = False
        elif event_type == "task_completed":
            task["status"] = data.get("status", "UNKNOWN")
            task["success"] = data.get("success")
            task["artifacts"] = data.get("artifacts", [])

    return tasks


def summarize_tasks(tasks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    totals = Counter()
    for task in tasks.values():
        status = task.get("status", "UNKNOWN")
        totals[status] += 1

    return {
        "total": sum(totals.values()),
        "by_status": dict(totals),
    }


def compliance_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    violations_by_severity = Counter()
    regulatory_events = [e for e in events if e.get("event_type") == "regulatory_verdict"]

    for event in regulatory_events:
        for violation in event.get("data", {}).get("violations", []):
            severity = violation.get("severity", "unknown")
            violations_by_severity[severity] += 1

    return {
        "total_events": len(regulatory_events),
        "violations_by_severity": dict(violations_by_severity),
    }


def list_tasks_sqlite(
    sqlite_path: str,
    tenant_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
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
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [_row_to_task(row) for row in rows]


def get_task_sqlite(sqlite_path: str, task_id: str) -> dict[str, Any] | None:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM audit_tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    conn.close()
    return _row_to_task(row) if row else None


def count_tasks_sqlite(sqlite_path: str, tenant_id: str | None = None) -> int:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    clauses = []
    params: list[Any] = []
    if tenant_id:
        clauses.append("tenant_id = ?")
        params.append(tenant_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    row = conn.execute(
        f"SELECT COUNT(*) as total FROM audit_tasks {where}",
        params,
    ).fetchone()
    conn.close()
    return int(row["total"] if row else 0)


def summarize_tasks_sqlite(sqlite_path: str, tenant_id: str | None = None) -> dict[str, Any]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    clauses = []
    params: list[Any] = []
    if tenant_id:
        clauses.append("tenant_id = ?")
        params.append(tenant_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT status, COUNT(*) as count FROM audit_tasks {where} GROUP BY status",
        params,
    ).fetchall()
    conn.close()

    counts = {row["status"]: int(row["count"]) for row in rows}
    return {
        "total": sum(counts.values()),
        "by_status": counts,
    }


def compliance_summary_sqlite(sqlite_path: str, tenant_id: str | None = None) -> dict[str, Any]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    clauses = ["event_type = 'regulatory_verdict'"]
    params: list[Any] = []
    if tenant_id:
        clauses.append("tenant_id = ?")
        params.append(tenant_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT data_json FROM audit_events {where}",
        params,
    ).fetchall()
    conn.close()

    violations_by_severity = Counter()
    for row in rows:
        try:
            data = json.loads(row["data_json"] or "{}")
        except json.JSONDecodeError:
            continue
        for violation in data.get("violations", []):
            severity = violation.get("severity", "unknown")
            violations_by_severity[severity] += 1

    return {
        "total_events": len(rows),
        "violations_by_severity": dict(violations_by_severity),
    }


def count_events_sqlite(
    sqlite_path: str,
    tenant_id: str | None = None,
    task_id: str | None = None,
) -> int:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    clauses = []
    params: list[Any] = []
    if tenant_id:
        clauses.append("tenant_id = ?")
        params.append(tenant_id)
    if task_id:
        clauses.append("task_id = ?")
        params.append(task_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    row = conn.execute(
        f"SELECT COUNT(*) as total FROM audit_events {where}",
        params,
    ).fetchone()
    conn.close()
    return int(row["total"] if row else 0)


def _read_events_sqlite(
    sqlite_path: str,
    limit: int | None = None,
    offset: int = 0,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    clauses = []
    params: list[Any] = []
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
    rows = conn.execute(query, params).fetchall()
    conn.close()

    results: list[dict[str, Any]] = []
    for row in rows:
        try:
            data = json.loads(row["data_json"] or "{}")
        except json.JSONDecodeError:
            data = {}
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


def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    tags = []
    artifacts = []
    try:
        tags = json.loads(row["tags_json"] or "[]")
    except json.JSONDecodeError:
        tags = []
    try:
        artifacts = json.loads(row["artifacts_json"] or "[]")
    except json.JSONDecodeError:
        artifacts = []

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


def load_policy(base_dir: str, tenant_id: str) -> dict[str, Any] | None:
    policy_path = os.path.join(base_dir, ".tenants", tenant_id, "policy.yaml")
    if not os.path.exists(policy_path):
        return None
    try:
        with open(policy_path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except Exception:
        return None


def format_timestamp(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value
