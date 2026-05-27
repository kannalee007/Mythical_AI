"""
RAG (Retrieval Augmented Generation) Module

Enables the orchestrator to retrieve and learn from past successful tasks,
improving plan generation through memory-based augmentation.

This module supports two retrieval backends:

  1. VectorRAG  — fully offline semantic search using sentence-transformers
                  (all-MiniLM-L6-v2, ~80 MB, downloaded once) + ChromaDB
                  (embedded, no server needed).  This is the default and
                  preferred backend.

  2. MemoryRetriever — keyword-based fallback that queries Neo4j directly.
                       Used automatically when the vector dependencies are
                       not installed or when a Neo4j persistence object is
                       provided without Chroma.

Install the vector backend once:
    pip install sentence-transformers chromadb

Both backends are fully offline — no data leaves the machine.
"""

import re
from typing import List, Dict, Optional

# ---------------------------------------------------------------------------
# Optional vector-search dependencies
# ---------------------------------------------------------------------------
try:
    from sentence_transformers import SentenceTransformer
    import chromadb
    from chromadb.config import Settings
    _VECTOR_AVAILABLE = True
except ImportError:
    _VECTOR_AVAILABLE = False

from orchestrator.persistence import Neo4jPersistence


# ---------------------------------------------------------------------------
# VectorRAG — offline semantic search with sentence-transformers + Chroma
# ---------------------------------------------------------------------------

class VectorRAG:
    """
    Fully offline semantic memory store using sentence-transformers + ChromaDB.

    Tasks are embedded once on insertion and retrieved by cosine similarity.
    The Chroma collection is persisted to disk at ``chroma_path`` so memory
    survives process restarts.

    Usage:
        rag = VectorRAG()                       # default path: .chroma_store/
        rag.add_task("task-001", "read CSV and plot histogram", code, success=True)
        results = rag.find_similar("plot data from file", top_k=3)
    """

    _MODEL_NAME = "all-MiniLM-L6-v2"   # ~80 MB, downloaded once, runs offline forever
    _COLLECTION  = "orchestrator_tasks"

    def __init__(self, chroma_path: str = ".chroma_store"):
        if not _VECTOR_AVAILABLE:
            raise ImportError(
                "VectorRAG requires sentence-transformers and chromadb.\n"
                "Install them with:  pip install sentence-transformers chromadb"
            )

        self._model = SentenceTransformer(self._MODEL_NAME)

        # Chroma in persistent-client mode: data is stored on disk and
        # reloaded automatically on the next startup.
        self._client = chromadb.PersistentClient(
            path=chroma_path,
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=self._COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def add_task(
        self,
        task_id: str,
        request: str,
        code: Optional[str],
        success: bool,
        tags: Optional[List[str]] = None,
    ) -> None:
        """Embed and store a completed task in the vector store.

        Calling this for the same task_id twice is safe — the old embedding
        is replaced (upsert semantics).
        """
        # Build a rich text representation to embed: request + key code lines.
        code_preview = ""
        if code:
            # Keep the first 300 chars of code for the embedding; the full
            # code is stored in metadata so we can return it on retrieval.
            code_preview = code[:300]

        document = f"REQUEST: {request}\nCODE_PREVIEW: {code_preview}"
        embedding = self._model.encode(document).tolist()

        metadata = {
            "task_id": task_id,
            "request": request,
            "success": success,
            "tags": ",".join(tags or []),
            "code": code or "",
        }

        self._collection.upsert(
            ids=[task_id],
            embeddings=[embedding],
            documents=[document],
            metadatas=[metadata],
        )

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def find_similar(
        self,
        query: str,
        top_k: int = 5,
        success_only: bool = True,
    ) -> List[Dict]:
        """Return the top-k most semantically similar past tasks.

        Args:
            query:        Natural language description of the current task.
            top_k:        Maximum number of results to return.
            success_only: When True, only return tasks that succeeded.

        Returns:
            List of dicts with keys: task_id, request, code, tags, success,
            similarity_score.  Ordered from most to least similar.
        """
        total = self._collection.count()
        if total == 0:
            return []

        embedding = self._model.encode(query).tolist()

        # Fetch more than top_k so we can filter by success flag post-query.
        fetch_n = min(top_k * 3, total)
        results = self._collection.query(
            query_embeddings=[embedding],
            n_results=fetch_n,
            include=["metadatas", "distances"],
        )

        matches = []
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for meta, dist in zip(metadatas, distances):
            if success_only and not meta.get("success", False):
                continue

            # Chroma returns L2 distances for cosine collections when using
            # the HNSW index — convert to a 0-1 similarity score.
            similarity = max(0.0, 1.0 - dist)

            matches.append({
                "task_id": meta["task_id"],
                "request": meta["request"],
                "code": meta.get("code") or None,
                "tags": [t for t in meta.get("tags", "").split(",") if t],
                "success": meta.get("success", False),
                "similarity_score": round(similarity, 4),
            })

            if len(matches) >= top_k:
                break

        return matches

    def build_context_prompt(self, current_request: str, top_k: int = 3) -> str:
        """Build a prompt section showing the most similar past successful tasks."""
        similar = self.find_similar(current_request, top_k=top_k, success_only=True)
        if not similar:
            return ""

        lines = ["\n## EXAMPLES FROM PAST SUCCESSFUL TASKS\n"]
        for i, task in enumerate(similar, 1):
            score_pct = int(task["similarity_score"] * 100)
            lines.append(f"### Example {i} (similarity {score_pct}%): {task['request'][:80]}")
            if task["code"]:
                preview = task["code"][:400]
                lines.append(f"```python\n{preview}\n```")
            lines.append("")

        return "\n".join(lines)

    def total_tasks(self) -> int:
        """Return total number of tasks stored in the vector store."""
        return self._collection.count()


# ---------------------------------------------------------------------------
# MemoryRetriever — keyword-based Neo4j retrieval (fallback / legacy)
# ---------------------------------------------------------------------------

class MemoryRetriever:
    """Retrieve similar past tasks from Neo4j for context augmentation.

    This is the keyword-matching fallback used when the vector backend is not
    available or when Neo4j is the primary storage backend.
    """

    def __init__(self, persistence: Neo4jPersistence):
        """Initialize with Neo4j connection."""
        self.persistence = persistence
        # Do NOT cache persistence.driver directly — holding a raw driver
        # reference means this class silently breaks if persistence.close() is
        # called.  All session work is routed through self.persistence instead.

    def find_similar_tasks(
        self,
        current_request: str,
        limit: int = 5,
        success_only: bool = True,
    ) -> List[Dict]:
        """Find similar past tasks based on keyword matching.

        Args:
            current_request: User's current request text.
            limit:           Max results to return.
            success_only:    Only return successful tasks.

        Returns:
            List of similar task records with code and results.
        """
        keywords = self._extract_keywords(current_request)
        tags = self._extract_tags(current_request)

        if not keywords and not tags:
            return []

        with self.persistence.driver.session() as session:
            query = """
            MATCH (t:Task)-[:TAGGED]->(tag:Tag)
            WHERE ($success_only = false OR t.success = true)
            WITH t, tag,
                SIZE([k IN $keywords WHERE k IN LOWER(t.request)]) as keyword_matches
            WHERE keyword_matches > 0 OR tag.name IN $tags
            RETURN DISTINCT t.task_id as task_id,
                  t.request as request,
                  t.status as status,
                  t.timestamp as timestamp,
                  keyword_matches,
                  COLLECT(tag.name) as tags
            ORDER BY keyword_matches DESC, t.timestamp DESC
            LIMIT $limit
            """

            results = session.run(
                query,
                keywords=keywords,
                tags=tags,
                success_only=success_only,
                limit=limit,
            )

            tasks = []
            for record in results:
                task_id = record["task_id"]
                task_data = self.persistence.get_task_by_id(task_id)
                if task_data:
                    tasks.append({
                        "task_id": task_id,
                        "request": record["request"],
                        "status": record["status"],
                        "timestamp": record["timestamp"],
                        "tags": record["tags"],
                        "code": task_data["code_blocks"][0]["code"] if task_data["code_blocks"] else None,
                        "artifacts": task_data["artifacts"],
                    })

            return tasks

    def find_tasks_by_tag(self, tag_name: str, limit: int = 10) -> List[Dict]:
        """Find all successful tasks with a specific tag."""
        with self.persistence.driver.session() as session:
            query = """
            MATCH (t:Task)-[:TAGGED]->(tag:Tag)
            WHERE tag.name = $tag_name AND t.success = true
            RETURN t.task_id as task_id,
                   t.request as request,
                   t.timestamp as timestamp
            ORDER BY t.timestamp DESC
            LIMIT $limit
            """

            results = session.run(query, tag_name=tag_name, limit=limit)
            tasks = []
            for record in results:
                task_id = record["task_id"]
                task_data = self.persistence.get_task_by_id(task_id)
                if task_data:
                    tasks.append({
                        "task_id": task_id,
                        "request": record["request"],
                        "code": task_data["code_blocks"][0]["code"] if task_data["code_blocks"] else None,
                        "artifacts": task_data["artifacts"],
                        "timestamp": record["timestamp"],
                    })
            return tasks

    def get_best_practice(self, category: str) -> Optional[str]:
        """Get best practice code snippet for a category."""
        patterns = {
            "api_call": self._get_best_api_pattern(),
            "file_write": self._get_best_file_write_pattern(),
            "file_read": self._get_best_file_read_pattern(),
            "data_processing": self._get_best_data_processing_pattern(),
            "error_handling": self._get_best_error_handling_pattern(),
        }
        return patterns.get(category)

    def build_context_prompt(self, current_request: str) -> str:
        """Build augmented prompt context from past successes."""
        similar_tasks = self.find_similar_tasks(current_request, limit=3)

        if not similar_tasks:
            return ""

        context = "\n## EXAMPLES FROM PAST SUCCESSFUL TASKS\n\n"
        for i, task in enumerate(similar_tasks, 1):
            context += f"### Example {i}: {task['request'][:60]}...\n"
            if task["code"]:
                context += f"```python\n{task['code'][:500]}...\n```\n"
            context += "\n"

        return context

    def get_execution_stats_summary(self) -> Dict:
        """Get summary statistics to inform planning."""
        stats = self.persistence.get_execution_statistics()
        return {
            "total_tasks": stats["tasks"]["total"],
            "success_rate": f"{stats['tasks']['success_rate']:.1f}%",
            "most_common_tags": [t["tag"] for t in stats["top_tags"][:3]],
            "critical_violations": (
                stats["violations_by_severity"][0]["count"]
                if stats["violations_by_severity"] else 0
            ),
        }

    def _extract_keywords(self, request: str) -> List[str]:
        """Extract important keywords from request."""
        words = re.findall(r"\w+", request.lower())
        stopwords = {"the", "a", "an", "to", "from", "and", "or", "in", "with", "for"}
        return [w for w in words if w not in stopwords and len(w) > 3]

    def _extract_tags(self, request: str) -> List[str]:
        """Extract safety tags from request."""
        tags = re.findall(r"\[([A-Z_]+)\]", request)
        return [f"[{tag}]" for tag in tags]

    # ------------------------------------------------------------------
    # Hardcoded best-practice fallback snippets
    # ------------------------------------------------------------------

    def _get_best_api_pattern(self) -> str:
        tasks = self.find_tasks_by_tag("[API_REQUIRED]", limit=1)
        if tasks and tasks[0]["code"]:
            return tasks[0]["code"]
        return (
            "import requests\nimport json\n\ntry:\n"
            "    response = requests.get(url, timeout=10)\n"
            "    response.raise_for_status()\n"
            "    data = response.json()\nexcept requests.RequestException as e:\n"
            "    print(f\"API Error: {e}\")"
        )

    def _get_best_file_write_pattern(self) -> str:
        return (
            "import json\nfrom pathlib import Path\n\n"
            "output_path = Path('/codebase/output.json')\n"
            "data = {\"result\": \"success\"}\n"
            "output_str = json.dumps(data, indent=2)\n"
            "output_path.write_text(output_str)\n"
            "print(f\"Saved to {output_path}\")"
        )

    def _get_best_file_read_pattern(self) -> str:
        return (
            "from pathlib import Path\n\n"
            "config_path = Path('/codebase/config.yaml')\n"
            "if config_path.exists():\n"
            "    content = config_path.read_text()\nelse:\n"
            "    print(f\"File not found: {config_path}\")"
        )

    def _get_best_data_processing_pattern(self) -> str:
        return (
            "import pandas as pd\n\n"
            "df = pd.read_csv('/codebase/data.csv')\n"
            "df = df.dropna()\n"
            "df['date'] = pd.to_datetime(df['date'])\n"
            "print(f\"Processed {len(df)} rows\")\n"
            "df.to_csv('/codebase/data_clean.csv', index=False)"
        )

    def _get_best_error_handling_pattern(self) -> str:
        return (
            "import logging\n\nlogger = logging.getLogger(__name__)\n\ntry:\n"
            "    result = perform_operation()\n"
            "    logger.info(f\"Success: {result}\")\n"
            "except FileNotFoundError:\n    logger.error(\"Required file not found\")\n"
            "except Exception as e:\n    logger.exception(f\"Unexpected error: {e}\")\n    raise"
        )


# ---------------------------------------------------------------------------
# CodeSearcher — pattern search over persisted code blocks (Neo4j)
# ---------------------------------------------------------------------------

class CodeSearcher:
    """Search codebase for patterns and examples in Neo4j."""

    def __init__(self, persistence: Neo4jPersistence):
        self.persistence = persistence

    def find_code_by_pattern(self, pattern: str, limit: int = 10) -> List[str]:
        """Find past code blocks matching a regex pattern."""
        with self.persistence.driver.session() as session:
            query = """
            MATCH (t:Task)-[:GENERATED_BY]->(cb:CodeBlock)
            WHERE t.success = true
            RETURN cb.code as code
            LIMIT $limit_raw
            """
            results = session.run(query, limit_raw=limit * 3)

            matching_code = []
            for record in results:
                code = record["code"]
                if re.search(pattern, code, re.IGNORECASE):
                    matching_code.append(code)
                    if len(matching_code) >= limit:
                        break

            return matching_code

    def get_common_imports(self, tag: Optional[str] = None) -> List[str]:
        """Get most commonly used imports in successful tasks."""
        with self.persistence.driver.session() as session:
            if tag:
                query = """
                MATCH (t:Task)-[:GENERATED_BY]->(cb:CodeBlock),
                      (t)-[:TAGGED]->(tg:Tag)
                WHERE tg.name = $tag AND t.success = true
                RETURN cb.code as code
                """
                results = session.run(query, tag=tag)
            else:
                query = """
                MATCH (t:Task)-[:GENERATED_BY]->(cb:CodeBlock)
                WHERE t.success = true
                RETURN cb.code as code
                LIMIT 100
                """
                results = session.run(query)

            import_pattern = re.compile(r"^(?:from|import)\s+[\w.]+", re.MULTILINE)
            import_counts: Dict[str, int] = {}

            for record in results:
                code = record["code"]
                imports = import_pattern.findall(code)
                for imp in imports:
                    import_counts[imp] = import_counts.get(imp, 0) + 1

            sorted_imports = sorted(import_counts.items(), key=lambda x: x[1], reverse=True)
            return [imp for imp, _ in sorted_imports[:10]]


# ---------------------------------------------------------------------------
# augment_weaver_prompt — convenience function used by run_orchestrator.py
# ---------------------------------------------------------------------------

def augment_weaver_prompt(
    original_prompt: str,
    current_request: str,
    persistence: Optional[Neo4jPersistence] = None,
    vector_rag: Optional["VectorRAG"] = None,
) -> str:
    """Augment LLM prompt with memory context from past successful tasks.

    Prefers VectorRAG (semantic) when available, falls back to keyword search
    via MemoryRetriever when Neo4j persistence is provided but Chroma is not.

    Args:
        original_prompt:  The base prompt to augment.
        current_request:  The user's current request (used as query).
        persistence:      Optional Neo4j persistence (for keyword fallback).
        vector_rag:       Optional VectorRAG instance (preferred).

    Returns:
        Augmented prompt string.
    """
    context = ""

    if vector_rag is not None:
        # Preferred: semantic search — fully offline, no Neo4j required.
        context = vector_rag.build_context_prompt(current_request)
    elif persistence is not None:
        # Fallback: keyword search against Neo4j.
        retriever = MemoryRetriever(persistence)
        context = retriever.build_context_prompt(current_request)

        # Also add best-practice snippet if relevant.
        best_practice = None
        req_lower = current_request.lower()
        if any(k in req_lower for k in ("api", "request", "http")):
            best_practice = retriever.get_best_practice("api_call")
        elif any(k in req_lower for k in ("write", "save", "create")):
            best_practice = retriever.get_best_practice("file_write")

        if best_practice:
            context += f"\n## BEST PRACTICE CODE\n```python\n{best_practice}\n```\n"

    augmented = original_prompt
    if context:
        augmented += f"\n{context}"

    augmented += "\nRemember: Use examples above as reference, but adapt to current request.\n"
    return augmented
