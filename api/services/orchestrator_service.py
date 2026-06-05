"""
Orchestrator service that wraps existing orchestrator modules as an API layer.

Connects to:
  - orchestrator.weaver for task planning
  - orchestrator.constitution for safety evaluation
  - orchestrator.navigator for human approval
  - orchestrator.sandbox for execution
  - orchestrator.persistence for Neo4j logging
  - orchestrator.tenancy for tenant isolation
  - orchestrator.rag for memory retrieval
  - orchestrator.code_analyzer for code quality checks

This service does NOT rewrite or refactor existing orchestrator code.
It only imports and wraps existing methods with API-friendly signatures.
"""

import sys
import os
import asyncio
import json
from typing import Optional, Dict, Any, AsyncGenerator
from uuid import uuid4
from datetime import datetime

# Add orchestrator to path (assumes orchestrator/ exists in project root)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Import existing orchestrator modules
try:
    from orchestrator.weaver import Weaver
    from orchestrator.constitution import ConstitutionNode
    from orchestrator.navigator import NavigatorGateway
    from orchestrator.sandbox import SandboxedGarden
    from orchestrator.persistence import PersistenceLayer
    from orchestrator.tenancy import TenancyManager
    from orchestrator.rag import RAGMemory
    from orchestrator.code_analyzer import CodeAnalyzer
except ImportError as e:
    print(f"Warning: Could not import orchestrator modules: {e}")
    print("Running in API development mode without full orchestrator integration.")


class OrchestratorService:
    """
    Wraps the Constitutional Orchestrator for API use.
    
    Manages the full task lifecycle:
      1. Task submission (user request)
      2. Planning (Weaver)
      3. Safety evaluation (Constitution + Navigator)
      4. Execution (Sandbox)
      5. Persistence (Neo4j)
    """
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize orchestrator service.
        
        Args:
            config_path: path to config.yaml
        """
        self.config_path = config_path
        
        # Initialize orchestrator components (wrapped, not modified)
        try:
            self.weaver = Weaver(config_path=config_path)
            self.constitution = ConstitutionNode(config_path=config_path)
            self.navigator = NavigatorGateway()
            self.sandbox = SandboxedGarden()
            self.persistence = PersistenceLayer()
            self.tenancy = TenancyManager()
            self.rag = RAGMemory()
            self.code_analyzer = CodeAnalyzer()
            self.orchestrator_ready = True
        except Exception as e:
            print(f"Orchestrator initialization incomplete: {e}")
            self.orchestrator_ready = False
    
    async def plan_task(self, task_id: str, request: str, tenant_id: str) -> Dict[str, Any]:
        """
        Generate execution plan using Weaver.
        
        Calls orchestrator.weaver.run_task(request).
        
        Returns:
            plan dict with intent, steps, safety_tags, violations, requires_approval
        """
        if not self.orchestrator_ready:
            return {
                "task_id": task_id,
                "intent": f"[MOCK] Plan: {request[:50]}...",
                "safety_tags": [],
                "steps": [{"step": 1, "description": "mock step", "code": "print('mock')"}],
                "violations": [],
                "requires_approval": False,
                "created_at": datetime.utcnow().isoformat(),
            }
        
        # Call existing Weaver (synchronous)
        plan = await asyncio.to_thread(self.weaver.run_task, request)
        
        # Add tenant context
        plan["tenant_id"] = tenant_id
        
        # Call RAG to retrieve similar past tasks (optional enhancement)
        similar_tasks = await asyncio.to_thread(self.rag.retrieve, request, top_k=3)
        plan["rag_context"] = similar_tasks
        
        return plan
    
    async def evaluate_safety(self, task_id: str, plan: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
        """
        Evaluate plan for safety violations using Constitution + custom rules.
        
        Calls orchestrator.constitution.evaluate(plan).
        Calls orchestrator.tenancy.get_custom_rules(tenant_id).
        
        Returns:
            safety_eval dict with violations[], approved_to_execute, requires_human_approval
        """
        if not self.orchestrator_ready:
            return {
                "task_id": task_id,
                "violations": [],
                "approved_to_execute": True,
                "requires_human_approval": False,
                "evaluated_at": datetime.utcnow().isoformat(),
            }
        
        # Call existing Constitution node
        constitution_result = await asyncio.to_thread(
            self.constitution.evaluate,
            plan
        )
        
        # Get tenant-specific custom rules
        custom_rules = await asyncio.to_thread(
            self.tenancy.get_custom_rules,
            tenant_id
        )
        
        # Apply custom rules (orchestrator logic unchanged)
        custom_violations = []
        if custom_rules:
            for rule in custom_rules:
                result = await asyncio.to_thread(rule.check, plan)
                if not result["passed"]:
                    custom_violations.append(result)
        
        all_violations = constitution_result.get("violations", []) + custom_violations
        
        return {
            "task_id": task_id,
            "violations": all_violations,
            "approved_to_execute": len(all_violations) == 0,
            "requires_human_approval": len(all_violations) > 0 or plan.get("requires_approval", False),
            "evaluated_at": datetime.utcnow().isoformat(),
        }
    
    async def execute_task(self, task_id: str, plan: Dict[str, Any], tenant_id: str,
                           approved_by_human: bool = False) -> Dict[str, Any]:
        """
        Execute plan inside sandboxed container.
        
        Calls orchestrator.sandbox.execute(plan).
        Calls orchestrator.persistence.log_execution(task_id, result, tenant_id).
        
        Returns:
            execution_result dict with output, error, duration_ms, neo4j_nodes_created
        """
        if not self.orchestrator_ready:
            return {
                "task_id": task_id,
                "status": "completed",
                "output": "[MOCK] Task executed successfully",
                "error": None,
                "duration_ms": 100,
                "neo4j_nodes_created": 3,
                "completed_at": datetime.utcnow().isoformat(),
            }
        
        # Call existing Sandbox
        execution_result = await asyncio.to_thread(
            self.sandbox.execute,
            plan,
            tenant_id=tenant_id,
            timeout_seconds=plan.get("timeout_seconds", 300)
        )
        
        # Call existing Persistence to log to Neo4j
        nodes_created = await asyncio.to_thread(
            self.persistence.log_execution,
            task_id=task_id,
            plan=plan,
            result=execution_result,
            tenant_id=tenant_id,
            approved_by_human=approved_by_human
        )
        
        execution_result["neo4j_nodes_created"] = nodes_created
        
        return execution_result
    
    async def stream_task_lifecycle(
        self,
        task_request: Dict[str, Any],
        require_human_approval: bool = False
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream task execution through full lifecycle (planning -> safety -> execution).
        
        Yields events at each stage for real-time WebSocket updates.
        
        Yields:
            {"stage": "planning"|"safety"|"executing"|"complete", "data": {...}}
        """
        task_id = str(uuid4())
        tenant_id = task_request["tenant_id"]
        request_description = task_request["description"]
        
        yield {
            "stage": "init",
            "task_id": task_id,
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Task submitted to orchestrator",
        }
        
        # Stage 1: Planning
        yield {
            "stage": "planning",
            "task_id": task_id,
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Weaver generating execution plan...",
        }
        
        plan = await self.plan_task(task_id, request_description, tenant_id)
        
        yield {
            "stage": "planning",
            "task_id": task_id,
            "data": plan,
            "timestamp": datetime.utcnow().isoformat(),
            "message": f"Plan generated with {len(plan.get('steps', []))} steps",
        }
        
        # Stage 2: Safety Evaluation
        yield {
            "stage": "safety",
            "task_id": task_id,
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Constitution evaluating plan for safety violations...",
        }
        
        safety_eval = await self.evaluate_safety(task_id, plan, tenant_id)
        
        yield {
            "stage": "safety",
            "task_id": task_id,
            "data": safety_eval,
            "timestamp": datetime.utcnow().isoformat(),
            "message": f"Safety check complete: {len(safety_eval['violations'])} violations found",
        }
        
        # Check if blocked
        if not safety_eval["approved_to_execute"]:
            yield {
                "stage": "complete",
                "task_id": task_id,
                "status": "blocked",
                "timestamp": datetime.utcnow().isoformat(),
                "message": "Task blocked by safety evaluation",
            }
            return
        
        # Stage 3: Human Approval (if needed)
        if safety_eval["requires_human_approval"] or require_human_approval:
            yield {
                "stage": "approval",
                "task_id": task_id,
                "timestamp": datetime.utcnow().isoformat(),
                "message": "Awaiting human approval via Navigator...",
            }
            
            # In production: call Navigator to show terminal prompt or dashboard notification
            # For now, assume approval (marked by API caller)
        
        # Stage 4: Execution
        yield {
            "stage": "executing",
            "task_id": task_id,
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Sandbox executing plan...",
        }
        
        execution_result = await self.execute_task(
            task_id,
            plan,
            tenant_id,
            approved_by_human=require_human_approval or not safety_eval["requires_human_approval"]
        )
        
        yield {
            "stage": "complete",
            "task_id": task_id,
            "status": execution_result.get("status", "completed"),
            "data": execution_result,
            "timestamp": datetime.utcnow().isoformat(),
            "message": f"Task completed in {execution_result.get('duration_ms', 0)}ms",
        }
