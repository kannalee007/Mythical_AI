"""FastAPI dashboard for audit logs and compliance views."""

from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dashboard.data import (
    build_task_index,
    compliance_summary,
    compliance_summary_sqlite,
    discover_audit_logs,
    discover_audit_stores,
    count_events_sqlite,
    count_tasks_sqlite,
    format_timestamp,
    get_task_sqlite,
    load_config,
    load_policy,
    list_tasks_sqlite,
    read_events,
    summarize_tasks_sqlite,
    summarize_tasks,
)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

config = load_config(CONFIG_PATH)
dashboard_cfg = config.get("dashboard", {})
DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN") or str(
    dashboard_cfg.get("auth_token", "")
)
DASHBOARD_EVENT_LIMIT = int(dashboard_cfg.get("event_limit", 1000))
DASHBOARD_PAGE_SIZE = int(dashboard_cfg.get("page_size", 50))
DASHBOARD_EVENT_PAGE_SIZE = int(dashboard_cfg.get("event_page_size", 200))

_INVALID_TOKENS = {"", "CHANGE_ME", "CHANGEME", "REPLACE_ME"}
if DASHBOARD_TOKEN.strip().upper() in _INVALID_TOKENS:
    raise RuntimeError(
        "Dashboard auth token is required. Set DASHBOARD_TOKEN or dashboard.auth_token."
    )

app = FastAPI(title="Mythical AI Dashboard", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=TEMPLATES_DIR)

templates.env.filters["fmt_ts"] = format_timestamp


def _require_token(request: Request) -> None:
    if not DASHBOARD_TOKEN:
        return

    supplied = request.headers.get("X-Auth-Token") or request.query_params.get("token")
    if supplied != DASHBOARD_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )


def _select_audit_paths(tenant_id: str) -> tuple[str, str, list[dict[str, str]], list[dict[str, str]]]:
    logs = discover_audit_logs(BASE_DIR, CONFIG_PATH)
    stores = discover_audit_stores(BASE_DIR, CONFIG_PATH)
    chosen_log = next((log for log in logs if log["tenant_id"] == tenant_id), None) or logs[0]
    chosen_store = next((store for store in stores if store["tenant_id"] == tenant_id), None) or stores[0]
    return chosen_store["path"], chosen_log["path"], stores, logs


def _load_context(tenant_id: str, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    store_path, log_path, stores, logs = _select_audit_paths(tenant_id)
    offset = max(page - 1, 0) * page_size
    use_sqlite = os.path.exists(store_path)

    if use_sqlite:
        tasks = list_tasks_sqlite(store_path, tenant_id=tenant_id, limit=page_size, offset=offset)
        total_tasks = count_tasks_sqlite(store_path, tenant_id=tenant_id)
        summary = summarize_tasks_sqlite(store_path, tenant_id=tenant_id)
        compliance = compliance_summary_sqlite(store_path, tenant_id=tenant_id)
        tasks_index = {task["task_id"]: task for task in tasks}
        events: list[dict[str, Any]] = []
    else:
        events = read_events(log_path, limit=DASHBOARD_EVENT_LIMIT)
        tasks_index = build_task_index(events)
        tasks = sorted(
            tasks_index.values(),
            key=lambda item: item.get("updated_at") or "",
            reverse=True,
        )
        total_tasks = len(tasks)
        summary = summarize_tasks(tasks_index)
        compliance = compliance_summary(events)

    total_pages = max(1, (total_tasks + page_size - 1) // page_size)

    return {
        "tenant_id": tenant_id,
        "log_path": log_path,
        "store_path": store_path,
        "logs": logs,
        "stores": stores,
        "events": events,
        "tasks_index": tasks_index,
        "tasks": tasks,
        "summary": summary,
        "compliance": compliance,
        "use_sqlite": use_sqlite,
        "page": page,
        "page_size": page_size,
        "total_tasks": total_tasks,
        "total_pages": total_pages,
    }


@app.get("/health", response_class=HTMLResponse)
async def health() -> str:
    return "ok"


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(_require_token)])
async def index(request: Request, tenant: str = "default") -> HTMLResponse:
    context = _load_context(tenant, page=1, page_size=DASHBOARD_PAGE_SIZE)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            **context,
        },
    )


@app.get("/tasks", response_class=HTMLResponse, dependencies=[Depends(_require_token)])
async def tasks(
    request: Request,
    tenant: str = "default",
    page: int = 1,
    page_size: int = DASHBOARD_PAGE_SIZE,
) -> HTMLResponse:
    context = _load_context(tenant, page=page, page_size=page_size)
    return templates.TemplateResponse(
        "tasks.html",
        {
            "request": request,
            **context,
        },
    )


@app.get(
    "/tasks/{task_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(_require_token)],
)
async def task_detail(
    request: Request,
    task_id: str,
    tenant: str = "default",
    page: int = 1,
    page_size: int = DASHBOARD_EVENT_PAGE_SIZE,
) -> HTMLResponse:
    context = _load_context(tenant, page=1, page_size=DASHBOARD_PAGE_SIZE)
    event_offset = max(page - 1, 0) * page_size

    if context["use_sqlite"]:
        task = get_task_sqlite(context["store_path"], task_id)
        events = read_events(
            context["log_path"],
            limit=page_size,
            offset=event_offset,
            sqlite_path=context["store_path"],
            task_id=task_id,
        )
        total_events = count_events_sqlite(
            context["store_path"],
            tenant_id=tenant,
            task_id=task_id,
        )
    else:
        task = context["tasks_index"].get(task_id)
        events = [e for e in context["events"] if e.get("task_id") == task_id]
        total_events = len(events)

    total_event_pages = max(1, (total_events + page_size - 1) // page_size)

    return templates.TemplateResponse(
        "task_detail.html",
        {
            "request": request,
            **context,
            "task": task,
            "task_events": events,
            "event_page": page,
            "event_page_size": page_size,
            "total_event_pages": total_event_pages,
            "total_events": total_events,
        },
    )


@app.get("/tenants", response_class=HTMLResponse, dependencies=[Depends(_require_token)])
async def tenants(request: Request) -> HTMLResponse:
    logs = discover_audit_logs(BASE_DIR, CONFIG_PATH)
    stores = discover_audit_stores(BASE_DIR, CONFIG_PATH)
    return templates.TemplateResponse(
        "tenants.html",
        {
            "request": request,
            "logs": logs,
            "stores": stores,
        },
    )


@app.get(
    "/policies/{tenant_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(_require_token)],
)
async def tenant_policy(request: Request, tenant_id: str) -> HTMLResponse:
    policy = load_policy(BASE_DIR, tenant_id)
    return templates.TemplateResponse(
        "policy.html",
        {
            "request": request,
            "tenant_id": tenant_id,
            "policy": policy,
        },
    )


@app.get("/compliance", response_class=HTMLResponse, dependencies=[Depends(_require_token)])
async def compliance(request: Request, tenant: str = "default") -> HTMLResponse:
    context = _load_context(tenant, page=1, page_size=DASHBOARD_PAGE_SIZE)
    return templates.TemplateResponse(
        "compliance.html",
        {
            "request": request,
            **context,
        },
    )
