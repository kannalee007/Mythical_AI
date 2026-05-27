# Constitutional Orchestrator - Prompting Best Practices

## Quick Start Prompts

Note: Copy only the text inside the code blocks. Do not include the triple backticks or a `Weaver>` prefix when pasting into the prompt.

### Read File
```
Read /codebase/config.yaml and report all database connection parameters
```

### Write File
```
Create /codebase/report.txt with a summary of all tasks executed in the last 24 hours. 
Save to /codebase/output.txt. Tags: [FILESYSTEM_MODIFY]
```

### API Call
```
Query StackOverflow API for "python async best practices".
Extract top 3 results with fields: title and link.
Constraints: Use https://api.stackexchange.com (JSON), no HTML scraping.
Output: Save to /codebase/results.json as pretty-printed JSON.
Tags: [API_REQUIRED] [FILESYSTEM_MODIFY]
```

### Data Processing
```
Process /codebase/data.csv: convert all dates to ISO 8601 format, 
remove rows with null values, save cleaned file to /codebase/data_clean.csv. 
Tags: [FILESYSTEM_MODIFY]
```

---

## Prompting Framework

### Effective Prompt Structure

```
[GOAL] [TARGET FILES] [CONSTRAINTS] [OUTPUT] [TAGS]
```

**Example:**

```
Goal: Extract all function definitions from my codebase
Target Files: /codebase/orchestrator/*.py
Constraints: Ignore test files, extract with docstrings
Output: Create summary file /codebase/functions.md with formatted list
Tags: [FILESYSTEM_MODIFY]
```

### Prompt Components

#### 1. Goal (What to do)

**Good**:
- "Extract all API endpoints from Flask app"
- "Convert Python 2 print statements to Python 3"
- "Generate test cases for /codebase/math_utils.py"

**Bad**:
- "Process the files" (too vague)
- "Make it better" (subjective)
- "Fix everything" (unbounded scope)

**Tips**:
- Use specific verbs: extract, convert, generate, analyze, refactor
- Mention the domain: Flask, Pandas, async, etc.
- Be concrete about deliverables

#### 2. Target Files (Where to work)

**Good**:
- `/codebase/orchestrator/weaver.py`
- `/codebase/config.yaml`
- `/codebase/orchestrator/*.py`
- `/codebase/data/*.csv`

**Bad**:
- `/path/to/file` (placeholder)
- `config.yaml` (relative path)
- `~/myfiles` (home directory)

**Rules**:
- Always use `/codebase/` prefix
- Use absolute paths
- Globs are supported: `*.py`, `*.json`

#### 3. Constraints (How to do it)

**Good**:
- "Don't use f-strings for file I/O"
- "Preserve all existing comments"
- "Use pandas for data operations"
- "Skip __init__.py files"
- "Add type hints (Python 3.11+)"

**Bad**:
- "Be careful" (vague)
- "Don't make mistakes" (obvious)

**Common Constraints**:
- Language/version: "Python 3.11+", "async/await only"
- Libraries: "Use pandas, not numpy", "Don't import requests"
- Formatting: "PEP 8 compliant", "Black formatter"
- Scope: "Only modify functions, not classes", "Skip comments"
- Safety: "No network calls", "Read-only", "Local files only"

#### 4. Output (Where to save results)

**Good**:
- "Save to /codebase/results.json with formatted output"
- "Print results to stdout (don't save)"
- "Create files in /codebase/output/ directory"
- "Modify files in-place"

**Bad**:
- "Output somewhere" (vague)
- No output specification (ambiguous)

**Output Modes**:
- **File**: `Save to /codebase/filename.ext`
- **Stdout**: `Print to console` or `Display results`
- **Multiple**: `Create /codebase/file1.txt and /codebase/file2.txt`
- **In-place**: `Modify /codebase/original.py`

#### 5. Tags (Safety declarations)

**Required Tags**:

| Tag | Triggers When | Example |
|-----|---------------|---------|
| `[API_REQUIRED]` | Using `requests`, `urllib`, or network calls | API queries, web scraping |
| `[FILESYSTEM_MODIFY]` | Writing, deleting, renaming files | Save results, create reports |
| `[ROOT_REQUIRED]` | Needs `sudo`, `chmod 777`, system commands | System config, install packages |

**Usage**:
```
Tags: [API_REQUIRED] [FILESYSTEM_MODIFY]
```

**Missing tags → Failure examples**:
```
"Search GitHub for Python projects"  ✗ Missing [API_REQUIRED]
"Create results.txt with findings"   ✗ Missing [FILESYSTEM_MODIFY]
"Delete old logs"                     ✗ Missing [FILESYSTEM_MODIFY]
```

---

## Prompt Patterns

### Pattern 1: File Analysis

**Template**:
```
Analyze /codebase/{file} for {criteria}. 
Report {findings}.
Constraints: {constraints}
Output: Create /codebase/{report_file} with formatted results
Tags: [FILESYSTEM_MODIFY]
```

**Examples**:

```
Analyze /codebase/orchestrator/weaver.py for code quality issues (unused imports, 
long functions > 50 lines, complex logic). Report findings as markdown.
Constraints: Use ast module for parsing, ignore docstrings
Output: Create /codebase/code_review.md with structured findings
Tags: [FILESYSTEM_MODIFY]
```

```
Analyze /codebase/requirements.txt for outdated packages.
Report packages with new major versions available.
Constraints: Don't break dependencies, check PyPI API only
Output: Create /codebase/outdated_packages.json
Tags: [API_REQUIRED] [FILESYSTEM_MODIFY]
```

### Pattern 2: Code Refactoring

**Template**:
```
Refactor /codebase/{files} to {goal}.
Apply {specific_rules}.
Constraints: {preserve_what}.
Output: Modify files in-place, save changes to /codebase/{files}
Tags: [FILESYSTEM_MODIFY]
```

**Examples**:

```
Refactor /codebase/orchestrator/*.py to add type hints to all function signatures.
Apply Python 3.11+ type annotations (use typing module for complex types).
Constraints: Preserve all comments, don't change logic, verify with mypy
Output: Modify files in-place
Tags: [FILESYSTEM_MODIFY]
```

```
Refactor /codebase/utils.py to extract duplicate error handling into a decorator.
Create new function error_handler() and apply to all functions that handle exceptions.
Constraints: Ensure all error messages remain identical, keep existing behavior
Output: Modify /codebase/utils.py in-place
Tags: [FILESYSTEM_MODIFY]
```

### Pattern 3: Data Processing

**Template**:
```
Process /codebase/{input_file} by {operations}.
Use {library} for operations.
Constraints: {data_constraints}.
Output: Save cleaned/transformed data to /codebase/{output_file}
Tags: [FILESYSTEM_MODIFY]
```

**Examples**:

```
Process /codebase/sales_data.csv by:
1. Filter rows where amount > 0
2. Convert date column to ISO 8601 format
3. Remove duplicates on customer_id
4. Calculate monthly totals

Use pandas library. Constraints: Preserve original file, handle missing values as NaN.
Output: Save processed data to /codebase/sales_summary.csv
Tags: [FILESYSTEM_MODIFY]
```

### Pattern 4: API Integration

**Template**:
```
Query {API} for {criteria}.
Extract {fields} from response.
Save results to /codebase/{output_file}.
Constraints: {API_constraints}.
Tags: [API_REQUIRED] [FILESYSTEM_MODIFY]
```

**Examples**:

```
Query StackOverflow API for top 5 questions tagged "python-asyncio".
Extract: question_id, title, score, created_date, owner_reputation.
Save results to /codebase/stackoverflow_results.json as pretty-printed JSON.
Constraints: Use official API (https://api.stackexchange.com), handle rate limits with backoff.
Tags: [API_REQUIRED] [FILESYSTEM_MODIFY]
```

```
Query GitHub API to find all repositories matching "orchestration AND python".
Extract: repo_name, url, stars, language, last_updated.
Save top 20 results to /codebase/github_search.json.
Constraints: Use public API only, no authentication required.
Tags: [API_REQUIRED] [FILESYSTEM_MODIFY]
```

### Pattern 5: Report Generation

**Template**:
```
Generate report on {topic} from {sources}.
Include {sections}.
Format as {format}.
Save to /codebase/{report_file}.
Tags: [FILESYSTEM_MODIFY]
```

**Examples**:

```
Generate system health report from Neo4j execution history.
Include:
1. Success rate (last 100 tasks)
2. Top 5 most common request types
3. Critical violations (last 7 days)
4. Average execution time by tag

Format as HTML with styled tables and summary metrics.
Save to /codebase/system_report.html
Tags: [API_REQUIRED] [FILESYSTEM_MODIFY]
```

---

## Advanced Techniques

### Technique 1: Multi-Step Workflows

Chain multiple prompts together:

**Step 1**:
```
Extract all Python functions from /codebase/orchestrator/ and save function signatures 
to /codebase/function_index.json. Tags: [FILESYSTEM_MODIFY]
```

**Step 2** (after Step 1 completes):
```
Read /codebase/function_index.json and generate call graph showing dependencies 
between functions. Save as /codebase/call_graph.md. Tags: [FILESYSTEM_MODIFY]
```

**Tip**: Use Neo4j query_graph to verify Step 1 completed before running Step 2

### Technique 2: Conditional Logic

Use explicit conditionals in prompts:

```
If /codebase/results.json contains errors array with > 5 items:
  - Generate detailed error report to /codebase/error_analysis.md
  - Email errors to team (not supported in sandbox - save to file instead)
Else:
  - Save summary statistics to /codebase/summary.txt

Do not use nested ternary operators in code.
Tags: [FILESYSTEM_MODIFY]
```

### Technique 3: Parameterized Prompts

Create template prompts for reuse:

```python
def create_analysis_prompt(file_path, criteria, output_file):
    return f"""
Analyze {file_path} for {criteria}.
Generate detailed report.
Output: Save to {output_file}
Tags: [FILESYSTEM_MODIFY]
"""

# Usage
prompt = create_analysis_prompt(
    "/codebase/weaver.py",
    "performance bottlenecks and optimization opportunities",
    "/codebase/perf_report.md"
)
```

### Technique 4: Validation Prompts

Double-check results:

**After main task**:
```
Verify /codebase/output.json is valid JSON, properly formatted, 
and contains exactly 5 records. Print validation result.
Tags: (none - read only)
```

### Technique 5: Debugging Prompts

Investigate failures:

```
The previous task failed. Analyze the error in orchestrator_decisions.log.
Identify root cause and propose fix. 
Output: Save analysis to /codebase/failure_analysis.md
Tags: [FILESYSTEM_MODIFY]
```

---

## Common Mistakes & Fixes

### Mistake 1: Vague Goals

❌ **Bad**:
```
Process the files
```

✅ **Good**:
```
Extract all Python function definitions from /codebase/orchestrator/*.py 
and create a searchable index saved to /codebase/function_index.json. 
Tags: [FILESYSTEM_MODIFY]
```

### Mistake 2: Missing File Paths

❌ **Bad**:
```
Read the config file
```

✅ **Good**:
```
Read /codebase/config.yaml and report database section
```

### Mistake 3: Missing Tags

❌ **Bad**:
```
Query GitHub API and save results
```

✅ **Good**:
```
Query GitHub API and save results to /codebase/repos.json
Tags: [API_REQUIRED] [FILESYSTEM_MODIFY]
```

### Mistake 4: Ambiguous Output

❌ **Bad**:
```
Analyze logs and report findings
```

✅ **Good**:
```
Analyze /codebase/app.log and save formatted report to /codebase/log_analysis.md
Tags: [FILESYSTEM_MODIFY]
```

### Mistake 5: Unsafe Constraints

❌ **Bad**:
```
Use any library you want
Don't worry about performance
```

✅ **Good**:
```
Use only standard library and pandas
Optimize for O(n) time complexity
```

### Mistake 6: Multi-file Ambiguity

❌ **Bad**:
```
Refactor the code
```

✅ **Good**:
```
Refactor /codebase/orchestrator/weaver.py and /codebase/orchestrator/utils.py 
to extract common error handling logic into /codebase/orchestrator/exceptions.py
Tags: [FILESYSTEM_MODIFY]
```

---

## Safety Considerations

### Safe Patterns

✅ **Safe - read only**:
```
Read /codebase/data.json and analyze structure
(No tags needed - auto-approved)
```

✅ **Safe - file write**:
```
Create /codebase/report.txt with summary
Tags: [FILESYSTEM_MODIFY]
```

✅ **Safe - API with tag**:
```
Query weather API for forecast
Tags: [API_REQUIRED]
```

### Dangerous Patterns

❌ **Dangerous - missing tags**:
```
Call requests.get() and save results
(Missing [API_REQUIRED] tag)
```

❌ **Dangerous - unbounded loops**:
```
Download all pages from website until done
(Violates infinite loop policy)
```

❌ **Dangerous - environment access**:
```
Read environment variables and save to file
(Violates data exfiltration policy)
```

---

## Monitoring & Feedback Loop

### Check Task Status

```bash
# View recent execution
python query_graph.py --limit 5 --recent

# Check for failures
python query_graph.py --failed

# Analyze violations
python query_graph.py --tag "[API_REQUIRED]"
```

### Debug Failed Tasks

```bash
# View detailed task info
python query_graph.py --task <task_id>

# Check logs
tail orchestrator_decisions.log

# Manual Neo4j query
python query_graph.py --shell
# Then: MATCH (t:Task {task_id: "xyz"}) RETURN t
```

### Iterate on Prompts

1. Submit initial prompt
2. Check result with `query_graph.py`
3. If failed, read logs to understand why
4. Refine prompt with constraints/tags
5. Retry improved version
6. Document working pattern for reuse

---

## Examples by Use Case

### Use Case: API Integration Testing

```
Test StackOverflow API pagination by:
1. Query for page 1: top Python questions (limit 100)
2. Query for page 2 with offset
3. Compare record counts and verify no duplicates
4. Save test results to /codebase/api_test_results.json

Constraints: Use requests library, add retry logic with exponential backoff
Tags: [API_REQUIRED] [FILESYSTEM_MODIFY]
```

### Use Case: Data ETL Pipeline

```
Process /codebase/raw_users.csv:
1. Clean: remove rows where email is null or invalid
2. Transform: standardize phone numbers to E.164 format
3. Enrich: add registration_date from /codebase/events.json
4. Validate: ensure all required fields present
5. Export: save to /codebase/users_processed.csv with processing report

Use pandas. Constraints: Handle CSV encoding issues, preserve original file.
Tags: [FILESYSTEM_MODIFY]
```

### Use Case: Code Quality Analysis

```
Generate code quality report for /codebase/orchestrator/:
1. Check for unused imports using ast module
2. Identify functions > 50 lines (too long)
3. Count cyclomatic complexity per function
4. List type annotation coverage percentage
5. Generate executive summary with score

Output: Create /codebase/code_quality_report.md and /codebase/code_quality_data.json
Constraints: Use only standard library, don't modify files
Tags: [FILESYSTEM_MODIFY]
```

---

## Additional Resources

- [DEPLOYMENT.md](DEPLOYMENT.md) - Production setup and configuration
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design and components
- Execution history: `python query_graph.py --stats`
- Example tasks: `python query_graph.py --recent --limit 20`

---

**Last updated**: 2026-04-25
**Version**: 1.0
**Author**: Constitutional Orchestrator Team
