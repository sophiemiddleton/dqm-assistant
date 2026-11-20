"""Findings and reports per run, as JSON files. Computed once, served many times."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

from dqm_assistant.findings import Finding


class Store:
    def __init__(self, root: str):
        self.root = Path(root)

    def _p(self, kind: str, subsystem: str, run: int) -> Path:
        return self.root / subsystem / kind / f"{run}.json"

    def save_findings(self, subsystem: str, run: int, findings: List[Finding]) -> None:
        p = self._p("findings", subsystem, run)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([f.to_dict() for f in findings], indent=1))

    def findings(self, subsystem: str, run: int) -> Optional[List[Finding]]:
        p = self._p("findings", subsystem, run)
        return [Finding.from_dict(d) for d in json.loads(p.read_text())] if p.exists() else None

    def save_report(self, subsystem: str, run: int, report: dict) -> None:
        p = self._p("reports", subsystem, run)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, indent=1))

    def report(self, subsystem: str, run: int) -> Optional[dict]:
        p = self._p("reports", subsystem, run)
        return json.loads(p.read_text()) if p.exists() else None

    def runs(self, subsystem: str, kind: str = "findings") -> List[int]:
        d = self.root / subsystem / kind
        return sorted(int(p.stem) for p in d.glob("*.json")) if d.exists() else []

    def previous(self, subsystem: str, run: int, n: int) -> List[Tuple[int, List[Finding]]]:
        """The n most recent assessed runs before `run`, oldest first."""
        before = [r for r in self.runs(subsystem) if r < run][-n:]
        return [(r, self.findings(subsystem, r) or []) for r in before]
