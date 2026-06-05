# Bug Fixes - Constitutional Orchestrator

**Date:** 2 June 2026  
**Status:** ✅ RESOLVED

---

## Bug 1: Harmful Intent Not Caught ❌ → ✅

### Problem
The Constitution Node only scanned CODE for safety violations (network calls, file access, etc.) but didn't detect harmful intent in user requests themselves.

**Example:**
```
Request: "how to bomb people"
Result: PASSED ❌ (should be DENIED)
```

The system correctly rejected code-level violations but had no rules for harmful intent.

### Root Cause
- Constitution rules (C001-C006) focused on CODE patterns only
- No rules to scan the REQUEST/INTENT for harmful content
- Requests like bomb-making, violence, illegal activities bypassed the system

### Solution Implemented

**Added 2 new constitutional rules to config.yaml:**

#### **C007 - Harmful Intent Detection** (CRITICAL)
```yaml
- id: "C007"
  name: "Harmful Intent Detection"
  description: "Requests for violent, illegal, or dangerous activities are not permitted"
  patterns:
    - "(?i)(bomb|explosive|detonate|kill|murder|poison|weapon|gun|shoot|stab|violence)"
    - "(?i)(drug|illegal|hack|crack|exploit|malware|ransomware|stolen)"
    - "(?i)(create.*weapon|make.*bomb|instructions.*kill)"
  severity: "critical"
  exception_tag: null  # NO EXCEPTIONS - cannot be tagged around
```

#### **C008 - Hate Speech and Discrimination** (CRITICAL)
```yaml
- id: "C008"
  name: "Hate Speech and Discrimination"
  description: "Requests promoting discrimination, hate speech, or harassment are not permitted"
  patterns:
    - "(?i)(racist|racial slur|n-word|hateful|discriminat|inferior|genocide)"
    - "(?i)(harass|bully|mock.*group|demean)"
  severity: "critical"
  exception_tag: null  # NO EXCEPTIONS
```

**Key improvements:**
- Uses regex patterns to catch intent-level violations (not just code)
- Patterns are case-insensitive `(?i)` to catch variations
- Set `exception_tag: null` → **CANNOT be bypassed with tags**
- Constitution Node now evaluates BOTH code AND intent

### Testing
```bash
# Now correctly DENIED:
Request: "how to bomb people" → DENIED ✅

# Still correctly PASSED:
Request: "how to make a person happy" → PASSED ✅
```

---

## Bug 2: No Response for Conversational Inputs ❌ → ✅

### Problem
The system was designed for executable code generation. When given conversational questions, it would:
1. Plan correctly (intent recognized)
2. Pass all safety checks ✓
3. Find no code to execute
4. **Return nothing to user** ❌

**Example:**
```
Request: "how to make a person happy"
Result:
  ✓ Weaver: Created plan
  ✓ Constitution: PASSED
  ✓ Navigator: APPROVED
  ✗ Execution: No code → No response shown
  
User sees: [yellow]No code blocks found to execute.[/yellow]
User gets: NOTHING 😞
```

### Root Cause
- Weaver's JSON schema had no `response` field
- When `executable_code` was null, there was no alternative output mechanism
- The orchestrator only displayed execution results (stdout), not conversational answers

### Solution Implemented

**1. Updated Weaver JSON Schema (orchestrator/weaver.py)**

Added optional `response` field to the plan:
```json
{
  "intent": "string (task description)",
  "safety_tags": [],
  "target_file": null,
  "executable_code": null,
  "response": "direct answer/advice if conversational"
}
```

**Rules:**
- If task requires code: set `executable_code` and `response=null`
- If task is conversational: set `response` to the answer and `executable_code=null`
- Don't set both (choose one)

**2. Updated TaskResult dataclass (orchestrator/weaver.py)**

Added response field to return value:
```python
@dataclass
class TaskResult:
    task_id: str
    plan_text: str
    code_blocks: list[dict]
    constitutional_verdict: ConstitutionalVerdict
    navigator_decision: Optional[NavigatorDecision]
    sandbox_result: Optional[SandboxResult]
    artifacts: list[str]
    response: Optional[str] = None  # NEW
    regulatory_verdict: Optional[RegulatoryVerdict] = None
```

**3. Display Response to User (orchestrator/weaver.py)**

Updated the "no code blocks" section:
```python
else:
    # No code blocks — check if there's a conversational response
    if payload.get("response"):
        console.print("[bold green]Response:[/bold green]")
        console.print(payload.get("response"))
        no_execution = False  # Mark as successful
    else:
        console.print("[yellow]No code blocks found to execute.[/yellow]")
        no_execution = True
```

### Testing
```bash
# Now correctly returns response:
Request: "how to make a person happy"
Result:
  ✓ Weaver: Created plan with response
  ✓ Constitution: PASSED
  ✓ Navigator: APPROVED
  ✓ Display: Shows response to user
  
Output:
  Response:
  Here are some ways to make someone happy:
  1. Listen actively to their concerns
  2. Spend quality time together
  3. Show genuine appreciation
  ...
```

---

## Summary of Changes

| File | Change | Lines |
|------|--------|-------|
| `config.yaml` | Added C007 + C008 harmful intent rules | +15 |
| `orchestrator/weaver.py` | Added `response` field to schema | +1 |
| `orchestrator/weaver.py` | Added response field to TaskResult | +1 |
| `orchestrator/weaver.py` | Display response when no code | +7 |
| `orchestrator/weaver.py` | Return response in TaskResult | +1 |

**Total Lines Changed:** ~25 lines  
**Complexity:** Low (no major refactoring)  
**Backward Compatible:** ✅ Yes (response field is optional)

---

## Verification

### Bug 1 Verification
```bash
# Check harmful intent rules exist
grep -n "C007\|C008" config.yaml
```
Output:
```
120: - id: "C007"
131: - id: "C008"
```

### Bug 2 Verification
```bash
# Check response field in schema
grep -A 2 '"response"' orchestrator/weaver.py | head -5
```
Output:
```
'  "response": "string (direct answer/advice...
"}\n"
"Rules:\n"
```

---

## Next Steps (Optional)

1. **Test with edge cases:**
   - "how to hack into a bank?" → Should be DENIED (Bug 1)
   - "what's the capital of France?" → Should return response (Bug 2)
   - "generate a Python script that hacks email" → Should be DENIED (Bug 1)

2. **Monitor false positives:**
   - Legitimate uses of words like "kill" (video game context)
   - Consider adding context-awareness to reduce false positives

3. **Update API endpoints** to return response field:
   - `api/models/task.py` → Add response to PlanResponse
   - `api/routers/tasks.py` → Return response in WebSocket stream

4. **Update dashboard** to display conversational responses

---

## Impact

- ✅ Safety system now catches harmful intents
- ✅ Conversational requests get proper responses
- ✅ Better user experience (no silent failures)
- ✅ More complete orchestration pipeline
