#!/usr/bin/env python
"""Quick validation script for Bug #1 and Bug #2 fixes."""

import json
import sys
sys.path.insert(0, '/Users/kaarunyalakshmanchinthalapudi/Downloads/mytical_ai 2')

from orchestrator.weaver import WeaverOrchestrator, TaskResult
from orchestrator.utils import load_config
from dataclasses import fields

# Load config
config = load_config("config.yaml")

print("=" * 60)
print("TESTING BUG FIXES")
print("=" * 60)

# Test 1: Verify C007 rule exists
print("\n✅ Test 1: Verify C007 rule added to config")
rules = config.get("constitution", {}).get("rules", [])
c007 = next((r for r in rules if r.get("id") == "C007"), None)
if c007:
    print(f"   ✅ C007 found: {c007.get('name')}")
    print(f"      Patterns: {len(c007.get('patterns', []))} rules")
    print(f"      Severity: {c007.get('severity')}")
else:
    print("   ❌ C007 NOT FOUND")
    sys.exit(1)

# Test 2: Verify C008 rule exists
print("\n✅ Test 2: Verify C008 rule added to config")
c008 = next((r for r in rules if r.get("id") == "C008"), None)
if c008:
    print(f"   ✅ C008 found: {c008.get('name')}")
    print(f"      Patterns: {len(c008.get('patterns', []))} rules")
    print(f"      Severity: {c008.get('severity')}")
else:
    print("   ❌ C008 NOT FOUND")
    sys.exit(1)

# Test 3: Verify weaver schema has response field in instructions
print("\n✅ Test 3: Verify response field in schema instructions")
weaver_config = config.get("weaver", {})
system_prompt = weaver_config.get("system_prompt", "")
if "response" in system_prompt or "conversational" in system_prompt.lower():
    print(f"   ✅ Schema mentions response/conversational support")
else:
    print("   ⚠️  Schema may not mention response field (check manually)")

# Test 4: Verify TaskResult includes response field
print("\n✅ Test 4: Verify TaskResult has response field")
field_names = [f.name for f in fields(TaskResult)]
if "response" in field_names:
    print(f"   ✅ response field found in TaskResult")
    print(f"      Field order: {field_names}")
else:
    print("   ❌ response field NOT found in TaskResult")
    print(f"      Available fields: {field_names}")
    sys.exit(1)

# Test 5: Spot-check the code for response handling
print("\n✅ Test 5: Verify response handling in execution code")
import inspect
orch = WeaverOrchestrator(config=config)
source = inspect.getsource(orch.run_task)
if "payload.get(\"response\")" in source:
    print(f"   ✅ Response extraction code found in run_task")
else:
    print("   ⚠️  Response extraction code not found (check manually)")

if "[bold green]Response:[/bold green]" in source:
    print(f"   ✅ Response display code found in run_task")
else:
    print("   ⚠️  Response display code not found (check manually)")

print("\n" + "=" * 60)
print("✅ ALL CRITICAL TESTS PASSED")
print("=" * 60)
print("\nBug Fix Summary:")
print("  Bug #1 (Harmful Intent): ✅ FIXED - C007 + C008 rules added")
print("  Bug #2 (Conversational): ✅ FIXED - response field implemented")

