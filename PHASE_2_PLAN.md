# Phase 2: API Completion - Audit, Status Tracking, OAuth

## Overview
Phase 2 completes the FastAPI REST layer by integrating with Neo4j for audit logging, implementing task status tracking with lifecycle events, and establishing OAuth connector infrastructure.

**Gate Criteria**: All tests passing + audit queries functional + status tracking E2E working

## Architecture

### 1. Neo4j Audit Integration
**Purpose**: Expose Neo4j audit log queries as REST endpoints

**Components**:
- `api/services/audit_service.py` - Neo4j query wrapper
  - `get_task_audit_log(task_id)` - retrieve execution history
  - `query_violations(filters)` - search safety violations
  - `query_compliance_events(tenant_id, date_range)` - compliance reporting
  - `get_user_activity_log(user_id, limit)` - audit trail per user
  
- `api/models/audit.py` - Data contracts
  - `AuditEvent` - single audit record
  - `AuditLogResponse` - paginated results
  - `ComplianceReport` - compliance summary
  - `ViolationRecord` - safety violation details

- `api/routers/audit.py` - Existing stubs replaced with implementation
  - GET `/api/v1/audit/tasks` - task audit logs with filtering
  - GET `/api/v1/audit/violations` - safety violations with severity
  - GET `/api/v1/audit/compliance` - compliance metrics
  - GET `/api/v1/audit/user/{user_id}` - user activity trail

**Integration Points**:
- Call `orchestrator.persistence.Persistence.query_audit_log()`
- Serialize Neo4j results → Pydantic models
- Support filtering: date_range, severity, status, user_id

---

### 2. Task Status Tracking
**Purpose**: Real-time task execution state machine

**State Machine**:
```
SUBMITTED → PLANNING → SAFETY_REVIEW → EXECUTING → COMPLETE/FAILED/BLOCKED
```

**Components**:
- `api/services/task_service.py` - NEW
  - `submit_task(request)` → TaskSubmissionResponse with task_id
  - `get_task_status(task_id)` → current state + execution time + result
  - `get_task_result(task_id)` → ExecutionResponse or error details
  - `cancel_task(task_id)` → mark as CANCELLED if not executing

- `api/models/task.py` - Extended with status tracking
  - `TaskStatus` enum (SUBMITTED, PLANNING, SAFETY_REVIEW, EXECUTING, COMPLETE, FAILED, BLOCKED, CANCELLED)
  - `TaskStateRecord` - Current state + timestamps for each state
  - `TaskStatusResponse` - Full status with current_state, progress, estimated_completion

- `api/routers/tasks.py` - Extended endpoints
  - POST `/api/v1/tasks` - submit task (returns task_id + initial status)
  - GET `/api/v1/tasks/{id}` - current status + state timeline
  - GET `/api/v1/tasks/{id}/result` - execution result (only if COMPLETE)
  - DELETE `/api/v1/tasks/{id}` - cancel task (if not executing)
  - GET `/api/v1/tasks` - list all tasks for tenant with filtering

**Persistence**:
- Store task_id → state mapping in memory (Phase 2) / PostgreSQL (Phase 3)
- Neo4j records execution timeline (already via orchestrator)
- WebSocket `/stream` already emits state transitions

---

### 3. OAuth Connector Infrastructure
**Purpose**: Enable GitHub/Slack/Notion integrations with OAuth2 flow

**Components**:
- `api/services/connector_service.py` - NEW
  - `get_oauth_config(connector_type)` → client_id, auth_url
  - `exchange_auth_code(connector_type, code)` → access_token + user_profile
  - `list_user_connectors(user_id)` → active integrations
  - `revoke_connector(user_id, connector_type)` → disable integration

- `api/models/connector.py` - NEW
  - `ConnectorType` enum (GITHUB, SLACK, NOTION)
  - `OAuthConfig` - client_id, redirect_uri, auth_url, scopes
  - `ConnectorCredential` - encrypted access_token + user_profile
  - `ConnectorListResponse` - active connectors per user

- `api/routers/connectors.py` - Replace stubs with implementation
  - GET `/api/v1/connectors` - available connector types
  - GET `/api/v1/connectors/{type}/auth-url` - OAuth initiation URL
  - POST `/api/v1/connectors/{type}/oauth/callback` - Handle OAuth redirect
  - GET `/api/v1/connectors/me` - user's active connectors
  - DELETE `/api/v1/connectors/{type}` - revoke connector

**Integration Points**:
- Call `orchestrator.connectors.registry.ConnectorRegistry` to get connector instances
- Use `orchestrator.connectors.secrets.SecretsManager` for token encryption
- OAuth state validation to prevent CSRF

**Environment Variables**:
```
GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, GITHUB_REDIRECT_URI
SLACK_CLIENT_ID, SLACK_CLIENT_SECRET, SLACK_REDIRECT_URI
NOTION_CLIENT_ID, NOTION_CLIENT_SECRET, NOTION_REDIRECT_URI
```

---

### 4. Error Handling & Validation
**Purpose**: Consistent error responses across all endpoints

**Components**:
- `api/errors.py` - NEW
  - `APIError` base exception
  - `ValidationError` - 400
  - `AuthenticationError` - 401
  - `AuthorizationError` - 403
  - `NotFoundError` - 404
  - `ConflictError` - 409
  - `RateLimitError` - 429
  - `InternalError` - 500

- Global exception handlers in `api/main.py`
  - Catch all APIError → format JSON response
  - Log to audit trail via `audit_service`
  - Include request_id + correlation_id

- Input validation via Pydantic
  - DateRange validation (start < end)
  - TaskRequest validation (task_type must be recognized)
  - ConnectorType validation (only known types)

---

## Implementation Order

1. **Audit Service** (audit_service.py + models/audit.py)
   - Parse Neo4j results
   - Define response models
   - Handle pagination + filtering

2. **Task Service** (task_service.py)
   - Implement state machine
   - Track task lifecycle
   - Implement cancellation logic

3. **Connector Service** (connector_service.py + models/connector.py)
   - Wrap orchestrator.connectors.registry
   - Implement OAuth flow
   - Handle token encryption

4. **Error Handling** (errors.py + main.py updates)
   - Define exception hierarchy
   - Register global handlers
   - Add audit logging

5. **Router Updates** (audit.py, tasks.py, connectors.py)
   - Replace stubs with implementations
   - Wire up dependency injection
   - Add request validation

6. **Tests** (test_api_*.py)
   - Audit query tests (mock Neo4j)
   - Task status tracking tests
   - OAuth flow tests (mock auth provider)
   - Error handling tests

---

## Success Criteria

- [ ] All Neo4j audit endpoints return correct data format
- [ ] Task status transitions match state machine
- [ ] OAuth redirect flow completes without errors
- [ ] All error cases return proper HTTP status codes
- [ ] 100% of Phase 2 tests passing
- [ ] WebSocket stream compatible with status updates
- [ ] Request validation catches invalid inputs
- [ ] No N+1 queries on list endpoints

---

## Deliverables

**Code**:
- ✅ api/services/audit_service.py
- ✅ api/services/task_service.py
- ✅ api/services/connector_service.py
- ✅ api/models/audit.py
- ✅ api/models/connector.py
- ✅ api/errors.py
- ✅ api/routers/audit.py (implementation)
- ✅ api/routers/tasks.py (extensions)
- ✅ api/routers/connectors.py (implementation)
- ✅ Updated api/main.py (error handlers)

**Tests**:
- ✅ tests/test_api_audit.py (10+ tests)
- ✅ tests/test_api_task_tracking.py (12+ tests)
- ✅ tests/test_api_oauth.py (8+ tests)
- ✅ tests/test_api_errors.py (6+ tests)

**Configuration**:
- ✅ .env.example (OAuth credentials)
- ✅ Updated requirements.txt (if new deps)

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Neo4j not available | Mock Persistence for tests; fallback to empty results |
| OAuth provider rate limits | Implement token caching + exponential backoff |
| Token storage security | Use orchestrator.connectors.secrets.SecretsManager |
| State machine edge cases | Comprehensive state validation + test coverage |
| N+1 queries | Pre-fetch related data; use Neo4j projections |

---

## Next Steps

1. ✅ Review this plan
2. Start Audit Service implementation
3. Implement Task Service state machine
4. Wire OAuth with connector registry
5. Add comprehensive error handling
6. Write tests for all 3 systems
7. Validation gate (100% tests passing)
