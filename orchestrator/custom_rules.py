"""
Custom Rules Management Module

Enables users to define, manage, and enable custom safety rules
beyond the built-in constitutional rules.
"""

import yaml
import json
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path


class CustomRulesManager:
    """Manage user-defined custom safety rules."""

    def __init__(self, config_path: str = "config.yaml"):
        """Initialize with config file."""
        self.config_path = Path(config_path)
        self.custom_rules_file = Path("custom_rules.yaml")
        self.rules = self._load_custom_rules()

    def _load_custom_rules(self) -> List[Dict]:
        """Load custom rules from file."""
        if not self.custom_rules_file.exists():
            return []
        
        try:
            with open(self.custom_rules_file) as f:
                data = yaml.safe_load(f)
                return data.get("custom_rules", [])
        except Exception as e:
            print(f"Warning: Failed to load custom rules: {e}")
            return []

    def _save_custom_rules(self):
        """Save custom rules to file."""
        with open(self.custom_rules_file, 'w') as f:
            yaml.dump({"custom_rules": self.rules}, f, default_flow_style=False)

    def add_rule(
        self,
        rule_id: str,
        name: str,
        description: str,
        patterns: List[str],
        severity: str = "medium",
        enabled: bool = True,
        exception_tags: Optional[List[str]] = None,
        auto_fix_suggestion: Optional[str] = None
    ) -> Dict:
        """
        Add a new custom rule.
        
        Args:
            rule_id: Unique identifier (e.g., "CUSTOM_001")
            name: Human-readable rule name
            description: What the rule checks for
            patterns: List of regex patterns to match
            severity: "critical", "high", "medium", or "low"
            enabled: Whether rule is active
            exception_tags: Tags that allow exceptions to this rule
            auto_fix_suggestion: Suggestion for fixing violations
            
        Returns:
            The created rule
        """
        rule = {
            "id": rule_id,
            "name": name,
            "description": description,
            "patterns": patterns,
            "severity": severity,
            "enabled": enabled,
            "exception_tags": exception_tags or [],
            "auto_fix_suggestion": auto_fix_suggestion,
            "custom": True,
            "created_at": datetime.utcnow().isoformat()  # UTC timestamp, not CWD path
        }
        
        # Check for duplicates
        if any(r["id"] == rule_id for r in self.rules):
            raise ValueError(f"Rule {rule_id} already exists")
        
        self.rules.append(rule)
        self._save_custom_rules()
        
        return rule

    def delete_rule(self, rule_id: str):
        """Delete a custom rule."""
        self.rules = [r for r in self.rules if r["id"] != rule_id]
        self._save_custom_rules()

    def enable_rule(self, rule_id: str):
        """Enable a rule."""
        for rule in self.rules:
            if rule["id"] == rule_id:
                rule["enabled"] = True
                self._save_custom_rules()
                return

    def disable_rule(self, rule_id: str):
        """Disable a rule."""
        for rule in self.rules:
            if rule["id"] == rule_id:
                rule["enabled"] = False
                self._save_custom_rules()
                return

    def list_rules(self, enabled_only: bool = True) -> List[Dict]:
        """List custom rules."""
        if enabled_only:
            return [r for r in self.rules if r["enabled"]]
        return self.rules

    def get_rule(self, rule_id: str) -> Optional[Dict]:
        """Get a specific rule."""
        for rule in self.rules:
            if rule["id"] == rule_id:
                return rule
        return None

    def update_rule(self, rule_id: str, **kwargs):
        """Update a rule's properties."""
        rule = self.get_rule(rule_id)
        if not rule:
            raise ValueError(f"Rule {rule_id} not found")
        
        rule.update(kwargs)
        self._save_custom_rules()

    def validate_rule(self, rule: Dict) -> List[str]:
        """Validate rule structure. Returns list of errors."""
        errors = []
        
        required_fields = {"id", "name", "description", "patterns", "severity"}
        for field in required_fields:
            if field not in rule:
                errors.append(f"Missing required field: {field}")
        
        if rule.get("severity") not in {"critical", "high", "medium", "low"}:
            errors.append(f"Invalid severity: {rule.get('severity')}")
        
        if not isinstance(rule.get("patterns", []), list):
            errors.append("Patterns must be a list")
        
        if len(rule.get("patterns", [])) == 0:
            errors.append("At least one pattern required")
        
        return errors

    def to_dict(self) -> Dict:
        """Export rules as dictionary."""
        return {
            "custom_rules": self.rules,
            "count": len(self.rules),
            "enabled_count": sum(1 for r in self.rules if r["enabled"])
        }

    def to_json(self) -> str:
        """Export rules as JSON."""
        return json.dumps(self.to_dict(), indent=2)


class RuleTemplates:
    """Pre-built rule templates for common use cases."""
    
    @staticmethod
    def sql_injection_prevention() -> Dict:
        """Detect potential SQL injection."""
        return {
            "id": "CUSTOM_SQL_001",
            "name": "SQL Injection Prevention",
            "description": "Detect potential SQL injection vulnerabilities",
            "patterns": [
                r"f['\"].*SELECT.*\{",  # f-string SQL
                r"query.*\+.*['\"]",    # String concatenation
                r"format\(.*sql",       # String format with SQL
                r"'%s'.*%",            # % formatting
            ],
            "severity": "critical",
            "exception_tags": ["[SQL_VERIFIED]"],
            "auto_fix_suggestion": "Use parameterized queries with placeholders"
        }

    @staticmethod
    def hardcoded_secrets() -> Dict:
        """Detect hardcoded secrets."""
        return {
            "id": "CUSTOM_SEC_001",
            "name": "Hardcoded Secrets Detection",
            "description": "Detect potential hardcoded passwords or API keys",
            "patterns": [
                r"password\s*=\s*['\"]",
                r"api_key\s*=\s*['\"]",
                r"secret\s*=\s*['\"]",
                r"token\s*=\s*['\"][a-zA-Z0-9]{20,}",
            ],
            "severity": "critical",
            "exception_tags": [],
            "auto_fix_suggestion": "Use environment variables or .env files for secrets"
        }

    @staticmethod
    def logging_pii() -> Dict:
        """Detect potential PII in logs."""
        return {
            "id": "CUSTOM_PRIVACY_001",
            "name": "Potential PII Logging",
            "description": "Detect logging of personally identifiable information",
            "patterns": [
                r"print\(.*email",
                r"print\(.*password",
                r"print\(.*credit_card",
                r"print\(.*ssn",
                r"logger.*\..*\(.*email",
            ],
            "severity": "high",
            "exception_tags": ["[AUDIT_APPROVED]"],
            "auto_fix_suggestion": "Sanitize sensitive data before logging"
        }

    @staticmethod
    def large_memory_allocation() -> Dict:
        """Detect potential memory issues."""
        return {
            "id": "CUSTOM_PERF_001",
            "name": "Large Memory Allocation",
            "description": "Detect potential memory exhaustion issues",
            "patterns": [
                r"\[\].*for.*in.*range\(10\d{6,}\)",  # Large list comprehension
                r"list\(range\(10\d{6,}\)\)",          # Large list creation
                r"\".*\" \* 10\d{6,}",                 # Large string multiplication
            ],
            "severity": "medium",
            "exception_tags": ["[TESTED_OK]"],
            "auto_fix_suggestion": "Use generators or iterators instead of lists"
        }

    @staticmethod
    def unsafe_deserialization() -> Dict:
        """Detect unsafe deserialization."""
        return {
            "id": "CUSTOM_SEC_002",
            "name": "Unsafe Deserialization",
            "description": "Detect pickle/eval usage with untrusted data",
            "patterns": [
                r"pickle\.load",
                r"eval\(",
                r"exec\(",
                r"__import__",
            ],
            "severity": "critical",
            "exception_tags": ["[TRUSTED_DATA]"],
            "auto_fix_suggestion": "Use json.loads() instead of pickle for untrusted data"
        }

    @staticmethod
    def test_coverage() -> Dict:
        """Require test coverage for critical functions."""
        return {
            "id": "CUSTOM_QA_001",
            "name": "Test Coverage Requirement",
            "description": "Flag functions without corresponding tests",
            "patterns": [
                r"def (calculate|validate|authorize|authenticate|process)",  # Critical functions
            ],
            "severity": "medium",
            "exception_tags": ["[TESTED]"],
            "auto_fix_suggestion": "Add unit tests for critical functions"
        }

    @staticmethod
    def deprecated_function() -> Dict:
        """Detect deprecated function usage."""
        return {
            "id": "CUSTOM_DEP_001",
            "name": "Deprecated Function Usage",
            "description": "Detect usage of deprecated functions",
            "patterns": [
                r"\.iteritems\(\)",  # Python 3 deprecation
                r"\.has_key\(",      # Python 3 deprecation
                r"unicode\(",        # Python 3 deprecation
            ],
            "severity": "medium",
            "exception_tags": [],
            "auto_fix_suggestion": "Update to modern Python 3 equivalents"
        }

    @staticmethod
    def get_all_templates() -> Dict[str, Dict]:
        """Get all available templates."""
        return {
            "sql_injection": RuleTemplates.sql_injection_prevention(),
            "hardcoded_secrets": RuleTemplates.hardcoded_secrets(),
            "logging_pii": RuleTemplates.logging_pii(),
            "memory_allocation": RuleTemplates.large_memory_allocation(),
            "unsafe_deserialization": RuleTemplates.unsafe_deserialization(),
            "test_coverage": RuleTemplates.test_coverage(),
            "deprecated_functions": RuleTemplates.deprecated_function(),
        }


def create_example_custom_rules():
    """Create example custom_rules.yaml file."""
    manager = CustomRulesManager()

    templates = RuleTemplates.get_all_templates()
    for key, template in templates.items():
        try:
            # Template dicts use 'id' but add_rule() expects 'rule_id' — remap.
            rule_kwargs = {k if k != "id" else "rule_id": v for k, v in template.items()}
            manager.add_rule(**rule_kwargs)
        except ValueError:
            pass  # Already exists

    return manager


# Example usage:
if __name__ == "__main__":
    # Create manager
    manager = CustomRulesManager()
    
    # Add a SQL injection rule
    manager.add_rule(
        rule_id="DEMO_SQL_001",
        name="Detect SQL String Concat",
        description="Flag SQL queries built with string concatenation",
        patterns=[r"query\s*=.*\+", r"SELECT.*\{"],
        severity="critical",
        exception_tags=["[SQL_VERIFIED]"],
        auto_fix_suggestion="Use prepared statements with parameterized queries"
    )
    
    # List rules
    print("Custom Rules:")
    for rule in manager.list_rules(enabled_only=False):
        print(f"  - {rule['id']}: {rule['name']} (Enabled: {rule['enabled']})")
    
    # Export
    print("\nExport (JSON):")
    print(manager.to_json())
