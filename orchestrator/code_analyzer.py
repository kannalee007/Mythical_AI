"""
AST-Based Code Analysis Module

Provides sophisticated code quality analysis using Python AST (Abstract Syntax Tree).
Detects issues that pattern matching alone cannot catch.
"""

import ast
import builtins
import sys
from typing import List, Dict, Optional, Tuple

# All names valid at module level without explicit import/assignment.
# Using the builtins module directly is reliable; hasattr(__builtins__, x) is NOT
# because __builtins__ is a dict in imported modules, not the builtins module object.
_BUILTIN_NAMES = frozenset(dir(builtins))


class CodeAnalyzer:
    """Analyze Python code using AST for quality issues."""

    def __init__(self, code: str):
        self.code = code
        self.tree = None
        self.errors = []

        try:
            self.tree = ast.parse(code)
        except SyntaxError as e:
            self.errors.append({
                "type": "syntax_error",
                "severity": "critical",
                "line": e.lineno,
                "message": f"Syntax error: {e.msg}",
                "col": e.offset,
            })

    def get_all_issues(self) -> List[Dict]:
        """Get all detected code quality issues."""
        if self.tree is None:
            return self.errors

        issues = self.errors.copy()
        issues.extend(self.find_undefined_variables())
        issues.extend(self.find_unused_variables())
        issues.extend(self.find_unused_imports())
        issues.extend(self.find_long_functions())
        issues.extend(self.find_complex_cyclomatic())
        issues.extend(self.find_except_all_handlers())
        issues.extend(self.find_mutable_defaults())
        issues.extend(self.find_bare_excepts())

        return sorted(issues, key=lambda x: x.get("line", 0))

    def find_undefined_variables(self) -> List[Dict]:
        """Find variables used before definition."""
        if not self.tree:
            return []

        visitor = UndefinedVariableDetector()
        visitor.visit(self.tree)

        return [
            {
                "type": "undefined_variable",
                "severity": "high",
                "line": u["line"],
                "column": u.get("col_offset", 0),
                "message": f"Variable '{u['name']}' used before definition",
                "fix_suggestion": f"Define {u['name']} before using it",
            }
            for u in visitor.undefined_vars
        ]

    def find_unused_variables(self) -> List[Dict]:
        """Find local variables that are never used."""
        if not self.tree:
            return []

        visitor = UnusedVariableDetector()
        visitor.visit(self.tree)
        visitor.finalize()  # FIXED: was never called — unused_vars was always empty

        return [
            {
                "type": "unused_variable",
                "severity": "low",
                "line": u["line"],
                "message": f"Local variable '{u['name']}' is assigned but never used",
                "fix_suggestion": f"Remove or use variable {u['name']}",
            }
            for u in visitor.unused_vars
        ]

    def find_unused_imports(self) -> List[Dict]:
        """Find imported modules that are never used."""
        if not self.tree:
            return []

        visitor = UnusedImportDetector()
        visitor.visit(self.tree)

        return [
            {
                "type": "unused_import",
                "severity": "low",
                "line": u["line"],
                "message": f"Import '{u['name']}' is unused",
                "fix_suggestion": f"Remove: {u['name']}",
            }
            for u in visitor.unused_imports
        ]

    def find_long_functions(self, threshold: int = 50) -> List[Dict]:
        """Find functions longer than threshold lines."""
        if not self.tree:
            return []
        issues = []
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_lines = node.end_lineno - node.lineno
                if func_lines > threshold:
                    issues.append({
                        "type": "long_function",
                        "severity": "medium",
                        "line": node.lineno,
                        "message": f"Function '{node.name}' is {func_lines} lines (threshold: {threshold})",
                        "fix_suggestion": f"Consider refactoring '{node.name}' into smaller functions",
                    })
        return issues

    def find_complex_cyclomatic(self, threshold: int = 10) -> List[Dict]:
        """Find functions with high cyclomatic complexity."""
        if not self.tree:
            return []
        issues = []
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                complexity = self._calculate_cyclomatic_complexity(node)
                if complexity > threshold:
                    issues.append({
                        "type": "high_complexity",
                        "severity": "medium",
                        "line": node.lineno,
                        "message": f"Function '{node.name}' complexity={complexity} (threshold: {threshold})",
                        "fix_suggestion": f"Reduce cyclomatic complexity of '{node.name}' with refactoring",
                    })
        return issues

    def find_except_all_handlers(self) -> List[Dict]:
        """Find except clauses that catch all exceptions."""
        if not self.tree:
            return []
        issues = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    if handler.type is None:
                        issues.append({
                            "type": "bare_except",
                            "severity": "high",
                            "line": handler.lineno,
                            "message": "Bare 'except:' catches all exceptions including KeyboardInterrupt",
                            "fix_suggestion": "Catch specific exceptions: except (ValueError, KeyError):",
                        })
        return issues

    def find_mutable_defaults(self) -> List[Dict]:
        """Find mutable default arguments (common Python bug)."""
        if not self.tree:
            return []
        issues = []
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for default in node.args.defaults + node.args.kw_defaults:
                    if default is None:
                        continue
                    if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        issues.append({
                            "type": "mutable_default",
                            "severity": "high",
                            "line": node.lineno,
                            "message": f"Function '{node.name}' has mutable default argument",
                            "fix_suggestion": "Use None as default and initialize inside function",
                        })
        return issues

    def find_bare_excepts(self) -> List[Dict]:
        """Stub — covered by find_except_all_handlers."""
        return []

    def _calculate_cyclomatic_complexity(self, node: ast.AST) -> int:
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        return complexity

    def suggest_fixes(self) -> List[Dict]:
        """Get all issues with fix suggestions."""
        return [i for i in self.get_all_issues() if i["type"] != "syntax_error"]


# ---------------------------------------------------------------------------
# AST visitors
# ---------------------------------------------------------------------------

class UndefinedVariableDetector(ast.NodeVisitor):
    """Detect variables used before definition.

    Tracks scope properly for: functions, async functions, for-loops,
    comprehensions, imports, and augmented assignments.
    """

    def __init__(self):
        self.undefined_vars: List[Dict] = []
        self._scope_stack: List[set] = [set()]  # stack of scopes; bottom = module level

    @property
    def _scope(self) -> set:
        return self._scope_stack[-1]

    def _is_defined(self, name: str) -> bool:
        # Check all scopes from innermost to outermost, plus builtins.
        return (
            any(name in s for s in self._scope_stack)
            or name in _BUILTIN_NAMES
        )

    def _push_scope(self):
        self._scope_stack.append(set())

    def _pop_scope(self):
        self._scope_stack.pop()

    # -- function / class / async function --

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._push_scope()
        # Parameters
        all_args = (
            node.args.args
            + node.args.posonlyargs
            + node.args.kwonlyargs
            + ([node.args.vararg] if node.args.vararg else [])
            + ([node.args.kwarg] if node.args.kwarg else [])
        )
        for arg in all_args:
            self._scope.add(arg.arg)
        self.generic_visit(node)
        self._pop_scope()

    visit_AsyncFunctionDef = visit_FunctionDef  # FIXED: async functions now handled

    def visit_ClassDef(self, node: ast.ClassDef):
        self._push_scope()
        self.generic_visit(node)
        self._pop_scope()

    # -- assignments --

    def visit_Assign(self, node: ast.Assign):
        # Visit RHS first, then define LHS names.
        self.visit(node.value)
        for target in node.targets:
            self._define_target(target)

    def visit_AugAssign(self, node: ast.AugAssign):
        self.visit(node.value)
        self._define_target(node.target)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if node.value:
            self.visit(node.value)
        self._define_target(node.target)

    def _define_target(self, target: ast.AST):
        if isinstance(target, ast.Name):
            self._scope.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._define_target(elt)

    # -- imports --  FIXED: import names were never added to scope

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self._scope.add(alias.asname if alias.asname else alias.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom):
        for alias in node.names:
            self._scope.add(alias.asname if alias.asname else alias.name)

    # -- for loops --  FIXED: loop variables were never added to scope

    def visit_For(self, node: ast.For):
        self.visit(node.iter)
        self._define_target(node.target)
        for stmt in node.body + node.orelse:
            self.visit(stmt)

    visit_AsyncFor = visit_For

    # -- comprehensions --  FIXED: comprehension vars were never tracked

    def _visit_comprehension(self, generators, elt_nodes):
        self._push_scope()
        for gen in generators:
            self.visit(gen.iter)
            self._define_target(gen.target)
            for cond in gen.ifs:
                self.visit(cond)
        for elt in elt_nodes:
            self.visit(elt)
        self._pop_scope()

    def visit_ListComp(self, node: ast.ListComp):
        self._visit_comprehension(node.generators, [node.elt])

    def visit_SetComp(self, node: ast.SetComp):
        self._visit_comprehension(node.generators, [node.elt])

    def visit_GeneratorExp(self, node: ast.GeneratorExp):
        self._visit_comprehension(node.generators, [node.elt])

    def visit_DictComp(self, node: ast.DictComp):
        self._visit_comprehension(node.generators, [node.key, node.value])

    # -- with statements --

    def visit_With(self, node: ast.With):
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars:
                self._define_target(item.optional_vars)
        for stmt in node.body:
            self.visit(stmt)

    visit_AsyncWith = visit_With

    # -- exception handlers --

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        if node.name:
            self._scope.add(node.name)
        self.generic_visit(node)

    # -- name usage --

    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load) and not self._is_defined(node.id):
            self.undefined_vars.append({
                "name": node.id,
                "line": node.lineno,
                "col_offset": node.col_offset,
            })


class UnusedVariableDetector(ast.NodeVisitor):
    """Detect assigned but unused variables."""

    def __init__(self):
        self.unused_vars: List[Dict] = []
        self.assigned: Dict[str, tuple] = {}  # name -> (line, col)
        self.used: set = set()

    def visit_Assign(self, node: ast.Assign):
        self.generic_visit(node)
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.assigned[target.id] = (node.lineno, target.col_offset)

    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load):
            self.used.add(node.id)

    def finalize(self):
        """Populate unused_vars — must be called after visit()."""
        for var_name, (line, col) in self.assigned.items():
            if var_name not in self.used and not var_name.startswith("_"):
                self.unused_vars.append({
                    "name": var_name,
                    "line": line,
                    "col_offset": col,
                })


class UnusedImportDetector(ast.NodeVisitor):
    """Detect unused imports."""

    def __init__(self):
        self.imports: Dict[str, tuple] = {}  # name -> (line, module)
        self.used: set = set()

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            self.imports[name] = (node.lineno, alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            self.imports[name] = (node.lineno, f"{node.module}.{alias.name}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load):
            self.used.add(node.id)

    def visit_Attribute(self, node: ast.Attribute):
        # Track top-level name of attribute access (e.g. os.path -> 'os')
        if isinstance(node.value, ast.Name):
            self.used.add(node.value.id)
        self.generic_visit(node)

    @property
    def unused_imports(self) -> List[Dict]:
        return [
            {"name": name, "line": line, "module": module}
            for name, (line, module) in self.imports.items()
            if name not in self.used
        ]


def analyze_code_quality(code: str) -> Dict:
    """Comprehensive code quality analysis. Returns summary and detailed issues."""
    analyzer = CodeAnalyzer(code)
    issues = analyzer.get_all_issues()

    by_severity: Dict[str, List] = {}
    for issue in issues:
        s = issue.get("severity", "info")
        by_severity.setdefault(s, []).append(issue)

    return {
        "total_issues": len(issues),
        "by_severity": by_severity,
        "issues": issues,
        "summary": {
            "critical": len(by_severity.get("critical", [])),
            "high": len(by_severity.get("high", [])),
            "medium": len(by_severity.get("medium", [])),
            "low": len(by_severity.get("low", [])),
        },
    }
