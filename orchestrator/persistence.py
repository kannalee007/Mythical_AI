"""Neo4j persistence layer for orchestrator knowledge graph."""

import hashlib
import json
from contextlib import suppress
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from neo4j import GraphDatabase

if TYPE_CHECKING:
    from orchestrator.weaver import TaskResult


class Neo4jPersistence:
    """Persists orchestrator task results to Neo4j knowledge graph."""

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "password",
    ):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self._ensure_schema()

    def _ensure_schema(self):
        """Create constraints and indexes if they don't exist."""
        with self.driver.session() as session:
            # Constraints
            constraints = [
                "CREATE CONSTRAINT task_id IF NOT EXISTS FOR (t:Task) REQUIRE t.task_id IS UNIQUE",
                "CREATE CONSTRAINT codeblock_id IF NOT EXISTS FOR (c:CodeBlock) REQUIRE c.id IS UNIQUE",
                "CREATE CONSTRAINT artifact_path IF NOT EXISTS FOR (a:Artifact) REQUIRE a.path IS UNIQUE",
                "CREATE CONSTRAINT violation_uid IF NOT EXISTS FOR (v:Violation) REQUIRE v.uid IS UNIQUE",
                "CREATE CONSTRAINT tag_name IF NOT EXISTS FOR (t:Tag) REQUIRE t.name IS UNIQUE",
            ]
            for cypher in constraints:
                with suppress(Exception):
                    session.run(cypher)

            # Indexes
            indexes = [
                "CREATE INDEX task_timestamp IF NOT EXISTS FOR (t:Task) ON (t.timestamp)",
                "CREATE INDEX task_status IF NOT EXISTS FOR (t:Task) ON (t.status)",
                "CREATE INDEX codeblock_lang IF NOT EXISTS FOR (c:CodeBlock) ON (c.language)",
            ]
            for cypher in indexes:
                with suppress(Exception):
                    session.run(cypher)

    def close(self):
        """Close the Neo4j driver."""
        self.driver.close()

    def persist_task(self, result: "TaskResult", request: str) -> str:
        """
        Persist a complete TaskResult to the knowledge graph.

        Returns the task node ID for reference.
        """
        timestamp = datetime.utcnow().isoformat()

        # Determine task status
        if result.sandbox_result is None:
            status = "NO_EXECUTION"
            success = False
        else:
            status = "SUCCESS" if result.sandbox_result.success else "FAILED"
            success = result.sandbox_result.success

        # Compute plan hash
        plan_hash = hashlib.sha256(result.plan_text.encode()).hexdigest()[:16]

        with self.driver.session() as session:
            # Create Task node
            session.run(
                """
                MERGE (t:Task {task_id: $task_id})
                SET t.request = $request,
                    t.timestamp = $timestamp,
                    t.status = $status,
                    t.success = $success,
                    t.plan_hash = $plan_hash
                """,
                task_id=result.task_id,
                request=request,
                timestamp=timestamp,
                status=status,
                success=success,
                plan_hash=plan_hash,
            )

            # Create Plan node and link
            session.run(
                """
                MATCH (t:Task {task_id: $task_id})
                MERGE (p:Plan {hash: $plan_hash})
                SET p.plan_text = $plan_text,
                    p.created_at = $timestamp
                MERGE (t)-[:HAS_PLAN]->(p)
                """,
                task_id=result.task_id,
                plan_hash=plan_hash,
                plan_text=result.plan_text,
                timestamp=timestamp,
            )

            # Create CodeBlock nodes with execution order
            for i, block in enumerate(result.code_blocks):
                block_id = f"{result.task_id}_block_{i}"
                code_hash = hashlib.sha256(block["code"].encode()).hexdigest()[:16]

                session.run(
                    """
                    MATCH (t:Task {task_id: $task_id})
                    MERGE (c:CodeBlock {id: $block_id})
                    SET c.language = $language,
                        c.code_hash = $code_hash,
                        c.code = $code,
                        c.description = $description,
                        c.execution_order = $order,
                        c.timestamp = $timestamp
                    MERGE (t)-[:EXECUTES {order: $order}]->(c)
                    """,
                    task_id=result.task_id,
                    block_id=block_id,
                    language=block.get("language", "unknown"),
                    code_hash=code_hash,
                    code=block.get("code", ""),
                    description=block.get("description", ""),
                    order=i,
                    timestamp=timestamp,
                )

                # Link consecutive blocks (DEPENDS_ON for ordering)
                if i > 0:
                    prev_block_id = f"{result.task_id}_block_{i-1}"
                    session.run(
                        """
                        MATCH (c1:CodeBlock {id: $prev_id})
                        MATCH (c2:CodeBlock {id: $curr_id})
                        MERGE (c2)-[:DEPENDS_ON {step: $step}]->(c1)
                        """,
                        prev_id=prev_block_id,
                        curr_id=block_id,
                        step=i,
                    )

            # Create Artifact nodes
            for artifact_path in result.artifacts:
                # Determine artifact type from extension
                ext = artifact_path.split(".")[-1].lower() if "." in artifact_path else "unknown"
                artifact_type = {"png": "image", "jpg": "image", "csv": "data", "txt": "text", "json": "data"}.get(ext, "file")

                session.run(
                    """
                    MATCH (t:Task {task_id: $task_id})
                    MERGE (a:Artifact {path: $path})
                    SET a.type = $type,
                        a.extension = $ext,
                        a.produced_at = $timestamp
                    MERGE (t)-[:PRODUCES]->(a)
                    """,
                    task_id=result.task_id,
                    path=artifact_path,
                    type=artifact_type,
                    ext=ext,
                    timestamp=timestamp,
                )

            # Create Violation nodes from constitutional check
            for violation in result.constitutional_verdict.violations:
                violation_uid = f"{result.task_id}_{violation.get('rule_id', 'unknown')}"

                session.run(
                    """
                    MATCH (t:Task {task_id: $task_id})
                    MERGE (v:Violation {uid: $uid})
                    SET v.rule_id = $rule_id,
                        v.rule_name = $rule_name,
                        v.severity = $severity,
                        v.pattern = $pattern,
                        v.detected_at = $timestamp
                    MERGE (t)-[:HAS_VIOLATION]->(v)
                    """,
                    task_id=result.task_id,
                    uid=violation_uid,
                    rule_id=violation.get("rule_id", "unknown"),
                    rule_name=violation.get("rule_name", ""),
                    severity=violation.get("severity", "unknown"),
                    pattern=violation.get("pattern", ""),
                    timestamp=timestamp,
                )

            # Add constitutional verdict tags
            for tag in result.constitutional_verdict.human_review_tags:
                session.run(
                    """
                    MATCH (t:Task {task_id: $task_id})
                    MERGE (tag:Tag {name: $name})
                    MERGE (t)-[:TAGGED {source: 'constitution'}]->(tag)
                    """,
                    task_id=result.task_id,
                    name=tag,
                )

            # Store sandbox result if available
            if result.sandbox_result:
                session.run(
                    """
                    MATCH (t:Task {task_id: $task_id})
                    SET t.exit_code = $exit_code,
                        t.execution_time_ms = $exec_time,
                        t.stdout_preview = $stdout,
                        t.stderr_preview = $stderr,
                        t.container_id = $container_id
                    """,
                    task_id=result.task_id,
                    exit_code=result.sandbox_result.exit_code,
                    exec_time=result.sandbox_result.execution_time_ms,
                    stdout=result.sandbox_result.stdout[:500],  # Preview only
                    stderr=result.sandbox_result.stderr[:500],
                    container_id=result.sandbox_result.container_id,
                )

        return result.task_id

    def get_task_by_id(self, task_id: str) -> Optional[dict]:
        """Retrieve a task and its relationships by ID."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (t:Task {task_id: $task_id})
                OPTIONAL MATCH (t)-[:EXECUTES]->(c:CodeBlock)
                OPTIONAL MATCH (t)-[:PRODUCES]->(a:Artifact)
                OPTIONAL MATCH (t)-[:HAS_VIOLATION]->(v:Violation)
                OPTIONAL MATCH (t)-[:TAGGED]->(tag:Tag)
                RETURN t,
                       collect(DISTINCT c) as code_blocks,
                       collect(DISTINCT a) as artifacts,
                       collect(DISTINCT v) as violations,
                       collect(DISTINCT tag) as tags
                """,
                task_id=task_id,
            )
            record = result.single()
            if record:
                return {
                    "task": dict(record["t"]),
                    "code_blocks": [dict(c) for c in record["code_blocks"]],
                    "artifacts": [dict(a) for a in record["artifacts"]],
                    "violations": [dict(v) for v in record["violations"]],
                    "tags": [dict(t) for t in record["tags"]],
                }
            return None

    def find_tasks_by_tag(self, tag_name: str) -> list[dict]:
        """Find all tasks with a specific tag."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (t:Task)-[:TAGGED]->(tag:Tag {name: $name})
                RETURN t.task_id as task_id, t.request as request, t.timestamp as timestamp, t.status as status
                ORDER BY t.timestamp DESC
                """,
                name=tag_name,
            )
            return [dict(record) for record in result]

    def find_failed_tasks(self, limit: int = 10) -> list[dict]:
        """Find recent failed tasks."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (t:Task)
                WHERE t.success = false OR t.status = 'FAILED'
                RETURN t.task_id as task_id, t.request as request, t.timestamp as timestamp, t.exit_code as exit_code
                ORDER BY t.timestamp DESC
                LIMIT $limit
                """,
                limit=limit,
            )
            return [dict(record) for record in result]

    def get_execution_statistics(self) -> dict:
        """Get aggregate statistics about task execution."""
        with self.driver.session() as session:
            # Overall counts
            counts = session.run(
                """
                MATCH (t:Task)
                RETURN count(t) as total,
                       count(CASE WHEN t.success = true THEN 1 END) as successful,
                       count(CASE WHEN t.success = false THEN 1 END) as failed
                """
            ).single()

            # Violation counts by severity
            violations = session.run(
                """
                MATCH (v:Violation)
                RETURN v.severity as severity, count(v) as count
                ORDER BY count DESC
                """
            )

            # Most common tags
            tags = session.run(
                """
                MATCH (t:Task)-[:TAGGED]->(tag:Tag)
                RETURN tag.name as tag, count(t) as count
                ORDER BY count DESC
                LIMIT 10
                """
            )

            return {
                "tasks": {
                    "total": counts["total"],
                    "successful": counts["successful"],
                    "failed": counts["failed"],
                    "success_rate": counts["successful"] / counts["total"] * 100 if counts["total"] > 0 else 0,
                },
                "violations_by_severity": [dict(v) for v in violations],
                "top_tags": [dict(t) for t in tags],
            }
