"""Rich-based display utilities for terminalbench."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runner import RunResult

try:
    from rich.console import Console
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


console = Console() if RICH_AVAILABLE else None


def print_rich_summary(results: list["RunResult"]) -> None:
    """Print a rich-formatted summary table."""
    if not RICH_AVAILABLE or not results:
        return

    from collections import defaultdict

    by_agent = defaultdict(list)
    for r in results:
        by_agent[r.agent_key].append(r)

    table = Table(title="Results Summary", show_header=True, header_style="bold cyan")
    table.add_column("Agent", style="dim")
    table.add_column("Passed", justify="right", style="green")
    table.add_column("Failed", justify="right", style="red")
    table.add_column("Total", justify="right")
    table.add_column("Accuracy", justify="right")
    table.add_column("Avg Time", justify="right")

    for agent_key in sorted(by_agent.keys()):
        agent_results = by_agent[agent_key]
        passed = sum(1 for r in agent_results if r.success)
        failed = len(agent_results) - passed
        total = len(agent_results)
        accuracy = (passed / total * 100) if total > 0 else 0.0
        avg_time = sum(r.elapsed_sec for r in agent_results) / total if total > 0 else 0.0

        table.add_row(
            agent_key,
            str(passed),
            str(failed),
            str(total),
            f"{accuracy:.1f}%",
            f"{avg_time:.1f}s",
        )

    console.print()
    console.print(table)


def print_task_matrix(results: list["RunResult"]) -> None:
    """Print a task results matrix."""
    if not RICH_AVAILABLE or not results:
        return

    from collections import defaultdict

    by_agent = defaultdict(list)
    for r in results:
        by_agent[r.agent_key].append(r)

    all_tasks = sorted(set(r.task_id for r in results))
    all_agents = sorted(by_agent.keys())

    if len(all_agents) <= 1:
        return

    table = Table(title="Task Results Matrix", show_header=True, header_style="bold")
    table.add_column("Task", style="dim")
    for agent in all_agents:
        table.add_column(agent, justify="center")

    task_results = {(r.task_id, r.agent_key): r for r in results}
    for task_id in all_tasks:
        row = [task_id]
        for agent in all_agents:
            r = task_results.get((task_id, agent))
            if r and r.success:
                row.append("[green]PASS[/green]")
            elif r:
                row.append("[red]FAIL[/red]")
            else:
                row.append("-")
        table.add_row(*row)

    console.print()
    console.print(table)


def print_plain_summary(results: list["RunResult"]) -> None:
    """Print plain text summary (fallback when rich unavailable)."""
    if not results:
        return

    from collections import defaultdict

    by_agent = defaultdict(list)
    for r in results:
        by_agent[r.agent_key].append(r)

    print()
    print("=" * 60)
    print("                    RESULTS SUMMARY")
    print("=" * 60)
    print(f"{'Agent':<12} {'Passed':>7} {'Failed':>7} {'Total':>6} {'Accuracy':>9} {'Avg Time':>10}")
    print("-" * 60)

    for agent_key in sorted(by_agent.keys()):
        agent_results = by_agent[agent_key]
        passed = sum(1 for r in agent_results if r.success)
        failed = len(agent_results) - passed
        total = len(agent_results)
        accuracy = (passed / total * 100) if total > 0 else 0.0
        avg_time = sum(r.elapsed_sec for r in agent_results) / total if total > 0 else 0.0
        print(f"{agent_key:<12} {passed:>7} {failed:>7} {total:>6} {accuracy:>8.1f}% {avg_time:>9.1f}s")

    print("=" * 60)


def print_summary(results: list["RunResult"]) -> None:
    """Print summary using rich if available, plain text otherwise."""
    if RICH_AVAILABLE:
        print_rich_summary(results)
        print_task_matrix(results)
    else:
        print_plain_summary(results)
