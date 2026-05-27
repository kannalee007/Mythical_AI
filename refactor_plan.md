# Refactor Plan

Scope: [orchestrator/*.py](orchestrator) and [query_graph.py](query_graph.py)

## Summary
- Functions and methods indexed: 123
- Files analyzed: 11

## Prioritized Findings
1. Duplicate logic across helpers
   - orchestrator/code_analyzer.py:291 visit_Name <-> orchestrator/code_analyzer.py:328 visit_Name (similarity 1.0)
   - orchestrator/custom_rules.py:95 enable_rule <-> orchestrator/custom_rules.py:103 disable_rule (similarity 0.948)
   - orchestrator/code_analyzer.py:314 visit_Import <-> orchestrator/code_analyzer.py:321 visit_ImportFrom (similarity 0.887)
   - orchestrator/code_analyzer.py:73 find_unused_variables <-> orchestrator/code_analyzer.py:94 find_unused_imports (similarity 0.785)
   - orchestrator/code_analyzer.py:278 __init__ <-> orchestrator/code_analyzer.py:310 __init__ (similarity 0.778)
   - orchestrator/custom_rules.py:90 delete_rule <-> orchestrator/custom_rules.py:95 enable_rule (similarity 0.75)

2. Flatten deeply nested branching in [query_graph.py](query_graph.py)
   - main depth 4 at line 208

3. Remove unused imports in [orchestrator/code_analyzer.py](orchestrator/code_analyzer.py)
   - line 9: sys (sys)
   - line 10: Optional (from typing import Optional)
   - line 10: Tuple (from typing import Tuple)

4. Remove unused imports in [orchestrator/constitution.py](orchestrator/constitution.py)
   - line 5: Optional (from typing import Optional)

5. Split long functions over 50 lines in [orchestrator/constitution.py](orchestrator/constitution.py)
   - evaluate line 56-151 (96 lines)

6. Replace swallowed exceptions in [orchestrator/custom_rules.py](orchestrator/custom_rules.py)
   - line 314: pass in handler

7. Remove unused imports in [orchestrator/persistence.py](orchestrator/persistence.py)
   - line 4: json (json)
   - line 12: TaskResult (from orchestrator.weaver import TaskResult)

8. Split long functions over 50 lines in [orchestrator/persistence.py](orchestrator/persistence.py)
   - persist_task line 56-227 (172 lines)

9. Remove unused imports in [orchestrator/rag.py](orchestrator/rag.py)
   - line 8: json (json)

10. Split long functions over 50 lines in [orchestrator/rag.py](orchestrator/rag.py)
   - find_similar_tasks line 21-83 (63 lines)

11. Split long functions over 50 lines in [orchestrator/sandbox.py](orchestrator/sandbox.py)
   - execute line 94-211 (118 lines)

12. Remove unused imports in [orchestrator/utils.py](orchestrator/utils.py)
   - line 6: Any (from typing import Any)

13. Split long functions over 50 lines in [orchestrator/weaver.py](orchestrator/weaver.py)
   - _plan_task line 91-143 (53 lines)
   - run_task line 245-450 (206 lines)

14. Flatten deeply nested branching in [orchestrator/weaver.py](orchestrator/weaver.py)
   - run_task depth 4 at line 245

## File Notes
- [query_graph.py](query_graph.py)
  - deeply nested: main(depth 4)
- [orchestrator/__init__.py](orchestrator/__init__.py)
- [orchestrator/code_analyzer.py](orchestrator/code_analyzer.py)
  - dead imports: sys@9, Optional@10, Tuple@10
- [orchestrator/constitution.py](orchestrator/constitution.py)
  - dead imports: Optional@5
  - long functions: evaluate(96)
- [orchestrator/custom_rules.py](orchestrator/custom_rules.py)
  - swallowed exceptions: 314
- [orchestrator/navigator.py](orchestrator/navigator.py)
- [orchestrator/persistence.py](orchestrator/persistence.py)
  - dead imports: json@4, TaskResult@12
  - long functions: persist_task(172)
- [orchestrator/rag.py](orchestrator/rag.py)
  - dead imports: json@8
  - long functions: find_similar_tasks(63)
- [orchestrator/sandbox.py](orchestrator/sandbox.py)
  - long functions: execute(118)
- [orchestrator/utils.py](orchestrator/utils.py)
  - dead imports: Any@6
- [orchestrator/weaver.py](orchestrator/weaver.py)
  - long functions: _plan_task(53), run_task(206)
  - deeply nested: run_task(depth 4)
