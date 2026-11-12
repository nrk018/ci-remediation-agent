"""MCP server. Write tools refuse to open a pull request unless approved is true."""

from __future__ import annotations

from mcp.server import MCPServer

from app.tools import (
    diagnose_failure,
    fetch_logs,
    get_failed_runs,
    open_fix_pr,
    propose_fix,
    search_similar_failures,
)

mcp = MCPServer(
    "ci-remediation",
    instructions=(
        "Diagnose failed GitHub Actions runs and draft fixes. "
        "open_fix_pr opens a pull request only when approved is true. "
        "This server never merges."
    ),
)


@mcp.tool(name="get_failed_runs", description="List recent failed GitHub Actions runs for a repository.")
def get_failed_runs_tool(repo: str, limit: int = 10) -> list[dict]:
    return get_failed_runs(repo, limit)


@mcp.tool(
    name="fetch_logs",
    description="Download a failed run and return the trimmed error window and signature.",
)
def fetch_logs_tool(repo: str, run_id: int) -> dict:
    return fetch_logs(repo, run_id)


@mcp.tool(
    name="search_similar_failures",
    description="Search failure memory for similar past failures and the fixes that worked.",
)
def search_similar_failures_tool(signature: str, k: int = 3) -> list[dict]:
    return search_similar_failures(signature, k)


@mcp.tool(
    name="diagnose_failure",
    description="Diagnose a failed run. Returns category, root cause, and confidence.",
)
def diagnose_failure_tool(repo: str, run_id: int) -> dict:
    return diagnose_failure(repo, run_id)


@mcp.tool(name="propose_fix", description="Propose a patch for a failed run. The patch is not applied.")
def propose_fix_tool(repo: str, run_id: int) -> dict:
    return propose_fix(repo, run_id)


@mcp.tool(
    name="open_fix_pr",
    description="Open a fix pull request. Refuses unless approved is true. Does not merge.",
)
def open_fix_pr_tool(repo: str, run_id: int, approved: bool = False) -> dict:
    return open_fix_pr(repo, run_id, approved)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
