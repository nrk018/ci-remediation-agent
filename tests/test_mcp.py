import asyncio

from mcp_server.server import mcp
from app.tools import open_fix_pr


def test_mcp_registers_tools_and_approval_gate():
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}
    assert names == {
        "get_failed_runs",
        "fetch_logs",
        "search_similar_failures",
        "diagnose_failure",
        "propose_fix",
        "open_fix_pr",
    }
    refused = open_fix_pr("acme/app", 1, approved=False)
    assert refused["ok"] is False
    assert "approved" in refused["error"]
