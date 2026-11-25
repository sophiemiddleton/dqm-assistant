"""dqm-assistant as an MCP server: what an orchestrator (Genesis, Claude, ...) sees.

    python -m dqm_assistant.server --config config.yaml                       # stdio (Genesis local)
    python -m dqm_assistant.server --config config.yaml --http --port 8030    # next to the mu2eaigpvm01 servers
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from mcp.server.mcpserver import MCPServer

from dqm_assistant.service import Service

INSTRUCTIONS = """Data-quality assessment of Mu2e runs. Start with assess_run: it returns a stored
report (verdict GOOD / BAD / NEEDS-EXPERT, issue groups with class and evidence, what was not
checked). Drill into get_findings or history only when asked or when confidence is low.
Class meanings: new, persistent, reference_artefact (suspect the reference, not the run),
method_artefact (one method in a known false-alarm mode), expected (explained by run type).
This service suggests; it never sets a good-run flag."""

SKILL = Path(__file__).resolve().parents[1] / "skills" / "mu2e-dqm.md"


def _instructions() -> str:
    """The skill file's body (frontmatter dropped), so every MCP client gets the same guidance
    at initialize -- hep-genesis passes server instructions to the model. Falls back to the
    short text above if the file is missing."""
    try:
        text = SKILL.read_text()
    except OSError:
        return INSTRUCTIONS
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return text.strip() or INSTRUCTIONS


mcp = MCPServer("dqm-assistant", instructions=_instructions())
_svc: Optional[Service] = None


def svc() -> Service:
    assert _svc is not None, "server not configured"
    return _svc


@mcp.tool()
def assess_run(run: int, subsystem: str = "CRV", refresh: bool = False) -> dict:
    """What's going on with this run? Returns the stored run report, computing it if needed
    (minutes if a vision detector is enabled). refresh=True recomputes."""
    return svc().assess_run(run, subsystem, refresh)


@mcp.tool()
def get_findings(run: int, subsystem: str = "CRV", method: Optional[str] = None) -> list:
    """The raw per-method findings behind a report (flag, score, reference, locus, evidence)."""
    return svc().get_findings(run, subsystem, method)


@mcp.tool()
def compare(run: int, item: str, subsystem: str = "CRV", method: str = "ks") -> list:
    """Run one method on one histogram/metric of one run, now, against the run's reference.
    Also the only way to run an on-demand method (list_methods: on_demand true), e.g. vision."""
    return svc().compare(run, item, subsystem, method)


@mcp.tool()
def history(item: str, run_min: int, run_max: int, subsystem: str = "CRV",
            method: Optional[str] = None) -> list:
    """Flag and score of one item over a run range, from stored assessments ("since when?")."""
    return svc().history(item, subsystem, run_min, run_max, method)


@mcp.tool()
def list_flagged(subsystem: str = "CRV", since_run: int = 0, cls: Optional[str] = None) -> list:
    """Runs whose report is not GOOD, optionally only groups of one class (e.g. 'new')."""
    return svc().list_flagged(subsystem, since_run, cls)


@mcp.tool()
def list_methods(subsystem: str = "CRV") -> list:
    """Method cards of the enabled detectors: what each compares and how it is known to fail.
    on_demand true: not part of assess_run; run it with compare(run, item, method=...)."""
    return svc().list_methods(subsystem)


@mcp.tool()
def get_reference(run: int, subsystem: str = "CRV") -> Optional[dict]:
    """The approved reference that applies to this run, or null if none does."""
    return svc().get_reference(run, subsystem)


def main(argv=None) -> None:
    global _svc
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--http", action="store_true")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8030)
    a = ap.parse_args(argv)
    _svc = Service(a.config, use_llm=not a.no_llm)
    if a.http:
        mcp.run("streamable-http", host=a.host, port=a.port)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
