"""Wiring: config -> detectors, histogram source, references, store. Used by the MCP server and CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml

from dqm_assistant import assessor
from dqm_assistant.context import RunContext, period_for
from dqm_assistant.detectors import build
from dqm_assistant.histsource import HistSource
from dqm_assistant.llm import maybe_llm
from dqm_assistant.references import Registry
from dqm_assistant.store import Store


@dataclass
class Subsystem:
    name: str
    sid: int
    source_version: str
    dataset_dir: str
    items: List[str]
    mean: List[str]
    detectors: List[Any]                 # run by assess_run
    on_demand: List[Any]                 # `on_demand: true`: only through compare()
    periods: Optional[str] = None
    default_run_type: str = "cosmics"


class Service:
    def __init__(self, config_path: str, use_llm: bool = True, reader=None):
        cfg = yaml.safe_load(open(config_path))
        self.store = Store(cfg["store"])
        self.registry = Registry.load(cfg["references"])
        self.history_runs = cfg.get("history_runs", 10)
        self.cache_dir = cfg.get("cache")
        self.llm = maybe_llm(use_llm and cfg.get("llm", True))
        self.reader = reader if reader is not None else self._reader()
        self.subsystems: Dict[str, Subsystem] = {}
        for name, s in cfg["subsystems"].items():
            routine, on_demand = [], []
            for spec in s["detectors"]:
                spec = dict(spec)
                (on_demand if spec.pop("on_demand", False) else routine).append(build(spec))
            self.subsystems[name] = Subsystem(
                name=name, sid=s["sid"], source_version=s["source_version"],
                dataset_dir=s["dataset_dir"], items=s["items"], mean=s.get("mean", []),
                detectors=routine, on_demand=on_demand, periods=s.get("periods"),
                default_run_type=s.get("default_run_type", "cosmics"))
        self._hists: Dict[str, HistSource] = {}

    @staticmethod
    def _reader():
        try:
            from dqm.reader import DqmReader
            return DqmReader()
        except Exception:
            return None

    def hists(self, sub: Subsystem) -> HistSource:
        if sub.name not in self._hists:
            self._hists[sub.name] = HistSource(sub.sid, sub.dataset_dir, sub.items, sub.mean,
                                               reader=self.reader, cache_dir=self.cache_dir)
        return self._hists[sub.name]

    def run_type(self, run: int, sub: Subsystem) -> str:
        # TODO: ask the runs MCP (get_run) once we have its token; until then the default
        return sub.default_run_type

    def context(self, run: int, subsystem: str, items: Optional[List[str]] = None) -> RunContext:
        sub = self.subsystems[subsystem]
        rt, period = self.run_type(run, sub), period_for(run, sub.periods)
        return RunContext(run=run, subsystem=subsystem, sid=sub.sid, source_version=sub.source_version,
                          items=items or sub.items, hists=self.hists(sub), run_type=rt, period=period,
                          reference=self.registry.select(sub.source_version, run, rt, period),
                          reader=self.reader)

    # ---------------------------------------------------------------- the tool bodies
    def assess_run(self, run: int, subsystem: str, refresh: bool = False) -> dict:
        if not refresh and (cached := self.store.report(subsystem, run)):
            return cached
        sub = self.subsystems[subsystem]
        ctx = self.context(run, subsystem)
        history = self.store.previous(subsystem, run, self.history_runs)
        report, findings = assessor.assess(ctx, sub.detectors, history, self.llm)
        self.store.save_findings(subsystem, run, findings)
        d = report.to_dict()
        self.store.save_report(subsystem, run, d)
        return d

    def get_findings(self, run: int, subsystem: str, method: Optional[str] = None) -> List[dict]:
        fs = self.store.findings(subsystem, run)
        if fs is None:
            self.assess_run(run, subsystem)
            fs = self.store.findings(subsystem, run) or []
        return [f.to_dict() for f in fs if method in (None, f.method)]

    def compare(self, run: int, item: str, subsystem: str, method: str = "ks") -> List[dict]:
        sub = self.subsystems[subsystem]
        ctx = self.context(run, subsystem, items=[item])
        dets = [d for d in sub.detectors + sub.on_demand if d.method_id == method]
        if not dets:
            raise ValueError(f"method {method!r} not enabled for {subsystem}")
        return [f.to_dict() for f in dets[0].assess(ctx)]

    def history(self, item: str, subsystem: str, run_min: int, run_max: int,
                method: Optional[str] = None) -> List[dict]:
        rows = []
        for r in self.store.runs(subsystem):
            if run_min <= r <= run_max:
                for f in self.store.findings(subsystem, r) or []:
                    if f.item == item and method in (None, f.method):
                        rows.append({"run": r, "method": f.method, "flag": f.flag, "score": f.score,
                                     "reference": f.reference})
        return rows

    def list_flagged(self, subsystem: str, since_run: int = 0, cls: Optional[str] = None) -> List[dict]:
        out = []
        for r in self.store.runs(subsystem, "reports"):
            rep = self.store.report(subsystem, r)
            if r < since_run or rep["verdict"] == "GOOD":
                continue
            gs = [g for g in rep["groups"] if cls in (None, g["cls"])]
            if gs:
                out.append({"run": r, "verdict": rep["verdict"],
                            "groups": [{"name": g["name"] or g["key"], "cls": g["cls"]} for g in gs]})
        return out

    def list_methods(self, subsystem: str) -> List[dict]:
        sub = self.subsystems[subsystem]
        return ([{**d.card.to_dict(), "on_demand": False} for d in sub.detectors]
                + [{**d.card.to_dict(), "on_demand": True} for d in sub.on_demand])

    def get_reference(self, run: int, subsystem: str) -> Optional[dict]:
        ref = self.context(run, subsystem).reference
        return ref.to_dict() if ref else None
