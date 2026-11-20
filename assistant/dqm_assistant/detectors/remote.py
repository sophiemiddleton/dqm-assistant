"""Any method that emits dqm-method-scores/1 (method-scores/SCHEMA.md at the repo root).

The method runs elsewhere (another env, a service, a batch job) and returns one JSON document
per run. This plugin fetches the document, checks it, and turns it into Findings by the
schema's rules: one finding per item per run, BAD if any unit crossed the method's threshold,
carrying the worst unit; unlisted items are GOOD; n_scored == 0 gives no finding (not checked).
It adds no method-specific logic. What the method is and how it fails comes from the
`card` in the config.

    - type: remote
      method: my_method
      card: {compares: "...", granularity: "metric", needs_reference: false,
             false_alarms: ["..."], calibrated: false}
      # exactly one transport:
      command: [/path/env/bin/python, -m, my_method, --sid, "{sid}", "{run}"]
      # url: http://localhost:8020/score        POST {"sid": .., "run": ..} -> document
      # path: /data/scores/{sid}/{run}.json     a file per run
      timeout: 600

A Python subclass can override `fetch` for an in-process scorer (see tranad.py).
"""

from __future__ import annotations

import json
import subprocess
import urllib.request
from typing import Any, Dict, List, Optional

from dqm_assistant.context import RunContext
from dqm_assistant.detectors.base import Detector, NotJudged, register
from dqm_assistant.findings import BAD, GOOD, UNSURE, Finding, MethodCard

SCHEMA = "dqm-method-scores/1"
_REQUIRED = ("schema", "method", "method_version", "sid", "run", "granularity", "n_scored",
             "items", "results")
_FLAGS = (GOOD, BAD, UNSURE)


class SchemaError(ValueError):
    """The document does not follow dqm-method-scores/1."""


def validate(doc: Any) -> Dict[str, Any]:
    """Raise SchemaError naming the first problem; return the document unchanged if it is valid."""
    if not isinstance(doc, dict):
        raise SchemaError(f"expected a JSON object, got {type(doc).__name__}")
    if doc.get("schema") != SCHEMA:
        raise SchemaError(f"schema is {doc.get('schema')!r}, expected {SCHEMA!r}")
    missing = [k for k in _REQUIRED if k not in doc]
    if missing:
        raise SchemaError(f"missing field(s): {', '.join(missing)}")
    if doc["granularity"] not in ("subrun", "run"):
        raise SchemaError(f"granularity {doc['granularity']!r} is not 'subrun' or 'run'")
    if doc.get("direction", "higher_is_worse") not in ("higher_is_worse", "lower_is_worse"):
        raise SchemaError(f"direction {doc['direction']!r} is not higher_is_worse/lower_is_worse")
    if not isinstance(doc["n_scored"], int) or doc["n_scored"] < 0:
        raise SchemaError(f"n_scored must be a non-negative integer, got {doc['n_scored']!r}")
    if doc.get("error") and doc["n_scored"]:
        raise SchemaError("error is set but n_scored > 0")
    items = set(doc["items"])
    for i, r in enumerate(doc["results"]):
        if not isinstance(r, dict) or "item" not in r or "flag" not in r:
            raise SchemaError(f"results[{i}] needs 'item' and 'flag'")
        if r["flag"] not in _FLAGS:
            raise SchemaError(f"results[{i}].flag {r['flag']!r} is not one of {_FLAGS}")
        if r["item"] not in items:
            raise SchemaError(f"results[{i}].item {r['item']!r} is not listed in items")
    return doc


def _excess(r: Dict[str, Any], lower_is_worse: bool) -> float:
    """How far past its threshold a result is (>1 = past), for picking the worst unit."""
    s, t = r.get("score"), r.get("threshold")
    if s is None or not t:
        return 0.0
    s, t = float(s), float(t)
    if lower_is_worse:
        return t / s if s > 0 else float("inf")
    return s / t


def _short(metric: str) -> str:
    return "/".join(str(metric).split("/")[-2:])          # subgroup/name of a DQM metric path


def to_findings(doc: Dict[str, Any], subsystem: str, method: Optional[str] = None) -> List[Finding]:
    """A validated document -> one Finding per item (none if the method had no data)."""
    if not doc["n_scored"]:
        return []
    method = method or doc["method"]
    lower = doc.get("direction") == "lower_is_worse"
    unit = doc["granularity"]                              # "subrun" or "run"
    base_ev = {f"{unit}s_scored": doc["n_scored"]} if unit == "subrun" else {}
    out = []
    for item in doc["items"]:
        rs = [r for r in doc["results"] if r["item"] == item]
        bad = [r for r in rs if r["flag"] == BAD]
        unsure = [r for r in rs if r["flag"] == UNSURE]
        base = dict(run=int(doc["run"]), subsystem=subsystem, item=item, method=method,
                    method_version=str(doc["method_version"]), reference=doc.get("reference"))
        if not bad and not unsure:
            good = [r for r in rs if r["flag"] == GOOD]
            g = good[0] if len(good) == 1 else {}
            out.append(Finding(flag=GOOD, score=_num(g.get("score")),
                               threshold=_num(g.get("threshold")),
                               evidence={**base_ev, **_extra(g)}, **base))
            continue
        pool, flag = (bad, BAD) if bad else (unsure, UNSURE)
        worst = max(pool, key=lambda r: (_excess(r, lower), len(r.get("top") or [])))
        top = list(worst.get("top") or [])
        locus = worst.get("locus") or (", ".join(_short(d["metric"]) for d in top[:3]) or None)
        ev = dict(base_ev)
        if unit == "subrun":
            ev[f"subruns_{flag.lower()}"] = len(pool)
            ev["worst_subrun"] = worst.get("subrun")
        if top:
            ev["top"] = top[:5]
        ev.update(_extra(worst))
        out.append(Finding(flag=flag, subrun=worst.get("subrun"), score=_num(worst.get("score")),
                           threshold=_num(worst.get("threshold")), locus=locus, evidence=ev,
                           **base))
    return out


def _num(x) -> Optional[float]:
    return None if x is None else float(x)


_RESULT_KEYS = {"item", "flag", "subrun", "score", "threshold", "locus", "top", "evidence"}


def _extra(r: Dict[str, Any]) -> Dict[str, Any]:
    """A result's evidence plus any keys the schema does not define."""
    ev = dict(r.get("evidence") or {})
    ev.update({k: v for k, v in r.items() if k not in _RESULT_KEYS})
    return ev


@register("remote")
class RemoteDetector(Detector):
    """Fetch a dqm-method-scores/1 document per run and read it by the schema's rules."""

    card: MethodCard

    def __init__(self, method: Optional[str] = None, card: Optional[Dict[str, Any]] = None,
                 command: Optional[List[str]] = None, url: Optional[str] = None,
                 path: Optional[str] = None, timeout: float = 600, env: Optional[Dict] = None,
                 **options):
        super().__init__(**options)
        transports = [t for t in (command, url, path) if t]
        if type(self).fetch is RemoteDetector.fetch and len(transports) != 1:
            raise ValueError("remote detector needs exactly one of command, url, path")
        self.command, self.url, self.path = command, url, path
        self.timeout, self.env = timeout, env
        if card is not None or not hasattr(type(self), "card"):
            c = dict(card or {})
            c.setdefault("name", method or self.name)
            c.setdefault("compares", "unknown")
            c.setdefault("granularity", "unknown")
            c.setdefault("needs_reference", False)
            for k in ("blind_spots", "false_alarms"):
                c[k] = tuple(c.get(k, ()))
            self.card = MethodCard(**c)
        self.method = self.card.name                       # Finding.method and "not checked" name
        self.version = "remote"

    @property
    def method_id(self) -> str:
        return self.method

    # -- transport -------------------------------------------------------------------------
    def fetch(self, ctx: RunContext) -> Dict[str, Any]:
        """Return the raw document for ctx.run. Subclasses may override (in-process scorer)."""
        fill = {"sid": ctx.sid, "run": ctx.run, "subsystem": ctx.subsystem}
        if self.path:
            with open(self.path.format(**fill)) as f:
                return json.load(f)
        if self.url:
            req = urllib.request.Request(self.url, data=json.dumps(fill).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.load(resp)
        return self._run_command(fill)

    def _run_command(self, fill: Dict[str, Any]) -> Dict[str, Any]:
        import os
        argv = [str(a).format(**fill) for a in self.command]
        env = {**os.environ, **{k: str(v) for k, v in (self.env or {}).items()}}
        p = subprocess.run(argv, capture_output=True, text=True, timeout=self.timeout, env=env)
        if p.returncode:
            tail = (p.stderr or "").strip().splitlines()[-3:]
            raise RuntimeError(f"{argv[0]} exited {p.returncode}: {' | '.join(tail)}")
        for line in reversed(p.stdout.splitlines()):       # last JSON line for this run wins
            line = line.strip()
            if line.startswith("{"):
                doc = json.loads(line)
                if doc.get("run") == fill["run"]:
                    return doc
        raise RuntimeError(f"{argv[0]} printed no document for run {fill['run']}")

    # -- contract --------------------------------------------------------------------------
    def assess(self, ctx: RunContext) -> List[Finding]:
        doc = validate(self.fetch(ctx))
        if doc["run"] != ctx.run or doc["sid"] != ctx.sid:
            raise SchemaError(f"asked for sid {ctx.sid} run {ctx.run}, "
                              f"got sid {doc['sid']} run {doc['run']}")
        if not doc["n_scored"]:
            raise NotJudged(doc.get("error") or f"no data for run {ctx.run} (n_scored = 0)")
        return to_findings(doc, ctx.subsystem, self.card.name)
