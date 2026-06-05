#!/usr/bin/env python3
"""Query utility for the Constitutional Orchestrator knowledge graph."""

import argparse
import json
import sys

from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from orchestrator.persistence import Neo4jPersistence

console = Console()


def show_stats(persistence: Neo4jPersistence, tenant_id: str | None = None):
    """Show aggregate statistics."""
    stats = persistence.get_execution_statistics(tenant_id=tenant_id)

    console.rule("[bold]Execution Statistics[/bold]")

    # Task summary
    tasks = stats["tasks"]
    console.print(f"\n[bold]Tasks:[/bold]")
    console.print(f"  Total: {tasks['total']}")
    console.print(f"  Successful: [green]{tasks['successful']}[/green]")
    console.print(f"  Failed: [red]{tasks['failed']}[/red]")
    console.print(f"  Success Rate: {tasks['success_rate']:.1f}%")

    # Violations
    if stats["violations_by_severity"]:
        console.print(f"\n[bold]Violations by Severity:[/bold]")
        for v in stats["violations_by_severity"]:
            color = {"critical": "red", "high": "yellow", "medium": "blue"}.get(
                v["severity"], "white"
            )
            console.print(f"  [{color}]{v['severity']}[/{color}]: {v['count']}")

    # Top tags
    if stats["top_tags"]:
        console.print(f"\n[bold]Most Common Tags:[/bold]")
        for t in stats["top_tags"]:
            console.print(f"  {t['tag']}: {t['count']} tasks")


def show_recent_tasks(
    persistence: Neo4jPersistence,
    limit: int = 10,
    failed_only: bool = False,
    tenant_id: str | None = None,
):
    """Show recent tasks."""
    if failed_only:
        tasks = persistence.find_failed_tasks(limit, tenant_id=tenant_id)
        title = f"Recent Failed Tasks (last {len(tasks)})"
    else:
        # Query for recent tasks
        with persistence.driver.session() as session:
            result = session.run(
                """
                MATCH (t:Task)
                WHERE $tenant_id IS NULL OR t.tenant_id = $tenant_id
                RETURN t.task_id as task_id, t.request as request,
                       t.timestamp as timestamp, t.status as status, t.success as success
                ORDER BY t.timestamp DESC
                LIMIT $limit
                """,
                limit=limit,
                tenant_id=tenant_id,
            )
            tasks = [dict(record) for record in result]
        title = f"Recent Tasks (last {len(tasks)})"

    table = Table(title=title)
    table.add_column("Task ID", style="cyan", no_wrap=True)
    table.add_column("Status", style="bold")
    table.add_column("Request", style="green")
    table.add_column("Timestamp", style="dim")

    for t in tasks:
        status_color = "green" if t.get("success") else "red"
        status_text = t.get("status", "UNKNOWN")
        table.add_row(
            t["task_id"][:8] + "...",
            f"[{status_color}]{status_text}[/{status_color}]",
            t["request"][:50] + "..." if len(t["request"]) > 50 else t["request"],
            t["timestamp"][:19] if t["timestamp"] else "",
        )

    console.print(table)


def show_task_details(
    persistence: Neo4jPersistence,
    task_id: str,
    tenant_id: str | None = None,
):
    """Show detailed view of a specific task."""
    task_data = persistence.get_task_by_id(task_id, tenant_id=tenant_id)

    if not task_data:
        console.print(f"[red]Task {task_id} not found[/red]")
        return

    task = task_data["task"]

    # Build tree view
    tree = Tree(f"[bold cyan]{task['task_id']}[/bold cyan]")
    tree.add(f"[dim]Request:[/dim] {task['request']}")
    tree.add(f"[dim]Status:[/dim] [bold]{'SUCCESS' if task.get('success') else 'FAILED'}[/bold]")
    tree.add(f"[dim]Timestamp:[/dim] {task.get('timestamp', 'unknown')}")

    # Code blocks
    if task_data["code_blocks"]:
        blocks_branch = tree.add("[bold]Code Blocks[/bold]")
        for cb in sorted(task_data["code_blocks"], key=lambda x: x.get("execution_order", 0)):
            lang = cb.get("language", "unknown")
            desc = cb.get("description", "")[:40]
            blocks_branch.add(f"[{lang}] {desc}...")

    # Artifacts
    if task_data["artifacts"]:
        art_branch = tree.add("[bold]Artifacts[/bold]")
        for a in task_data["artifacts"]:
            art_branch.add(f"{a['path']} ({a.get('type', 'file')})")

    # Violations
    if task_data["violations"]:
        viol_branch = tree.add("[bold red]Violations[/bold red]")
        for v in task_data["violations"]:
            severity = v.get("severity", "unknown")
            color = {"critical": "red", "high": "yellow", "medium": "blue"}.get(severity, "white")
            viol_branch.add(f"[{color}]{v['rule_id']}[/{color}]: {v['rule_name']}")

    # Tags
    if task_data["tags"]:
        tag_branch = tree.add("[bold]Tags[/bold]")
        for t in task_data["tags"]:
            tag_branch.add(f"{t['name']}")

    console.print(tree)


def find_by_tag(persistence: Neo4jPersistence, tag_name: str, tenant_id: str | None = None):
    """Find tasks by tag."""
    tasks = persistence.find_tasks_by_tag(tag_name, tenant_id=tenant_id)

    if not tasks:
        console.print(f"[yellow]No tasks found with tag '{tag_name}'[/yellow]")
        return

    table = Table(title=f"Tasks with tag: {tag_name}")
    table.add_column("Task ID", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Request", style="green")
    table.add_column("Timestamp", style="dim")

    for t in tasks:
        status_color = "green" if t.get("status") == "SUCCESS" else "red"
        table.add_row(
            t["task_id"][:8] + "...",
            f"[{status_color}]{t['status']}[/{status_color}]",
            t["request"][:50] + "..." if len(t["request"]) > 50 else t["request"],
            t["timestamp"][:19] if t["timestamp"] else "",
        )

    console.print(table)


def interactive_shell(persistence: Neo4jPersistence):
    """Interactive Cypher query shell."""
    console.print("\n[bold]Neo4j Interactive Query Shell[/bold]")
    console.print("Type Cypher queries or 'exit' to quit.\n")

    while True:
        query = console.input("[bold cyan]neo4j>[/bold cyan] ")

        if query.lower() in ("exit", "quit", "q"):
            break

        if not query.strip():
            continue

        try:
            with persistence.driver.session() as session:
                result = session.run(query)
                records = list(result)

                if not records:
                    console.print("[dim](no results)[/dim]")
                    continue

                # Display as table
                if records:
                    keys = records[0].keys()
                    table = Table()
                    for key in keys:
                        table.add_column(key, overflow="fold")

                    for record in records[:50]:  # Limit to 50 rows
                        row = []
                        for key in keys:
                            value = record[key]
                            if isinstance(value, (dict, list)):
                                row.append(json.dumps(value, default=str)[:100])
                            else:
                                row.append(str(value)[:100])
                        table.add_row(*row)

                    console.print(table)
                    if len(records) > 50:
                        console.print(f"[dim](showing 50 of {len(records)} results)[/dim]")

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


def main():
    parser = argparse.ArgumentParser(
        description="Query the Constitutional Orchestrator knowledge graph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python query_graph.py --stats              # Show overall statistics
  python query_graph.py --recent             # Show recent tasks
  python query_graph.py --failed             # Show recent failed tasks
  python query_graph.py --task <task_id>     # Show task details
  python query_graph.py --tag API_REQUIRED   # Find tasks by tag
    python query_graph.py --stats --tenant acme # Tenant-scoped statistics
  python query_graph.py --shell              # Interactive Cypher shell
        """,
    )

    parser.add_argument("--stats", action="store_true", help="Show execution statistics")
    parser.add_argument("--recent", action="store_true", help="Show recent tasks")
    parser.add_argument("--failed", action="store_true", help="Show recent failed tasks")
    parser.add_argument("--task", metavar="ID", help="Show details for specific task ID")
    parser.add_argument("--tag", metavar="NAME", help="Find tasks by tag")
    parser.add_argument("--shell", action="store_true", help="Start interactive Cypher shell")
    parser.add_argument("--limit", type=int, default=10, help="Limit for recent/failed queries")
    parser.add_argument("--tenant", help="Filter queries to a specific tenant")
    parser.add_argument("--uri", default="bolt://localhost:7687", help="Neo4j URI")
    parser.add_argument("--user", default="neo4j", help="Neo4j username")
    parser.add_argument("--password", default="password", help="Neo4j password")

    args = parser.parse_args()

    # Connect to Neo4j
    try:
        persistence = Neo4jPersistence(args.uri, args.user, args.password)
    except Exception as e:
        console.print(f"[red]Failed to connect to Neo4j: {e}[/red]")
        sys.exit(1)

    # Run requested command
    if args.stats:
        show_stats(persistence, tenant_id=args.tenant)
    elif args.task:
        show_task_details(persistence, args.task, tenant_id=args.tenant)
    elif args.tag:
        find_by_tag(persistence, args.tag, tenant_id=args.tenant)
    elif args.failed:
        show_recent_tasks(persistence, limit=args.limit, failed_only=True, tenant_id=args.tenant)
    elif args.shell:
        interactive_shell(persistence)
    else:
        # Default: show recent tasks
        show_recent_tasks(persistence, limit=args.limit, tenant_id=args.tenant)


if __name__ == "__main__":
    main()
