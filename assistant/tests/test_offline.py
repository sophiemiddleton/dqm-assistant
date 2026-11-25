"""Offline checks: no network, no /pnfs, no model. Fake detectors stand in for KS/TranAD/vision."""

import asyncio
import textwrap
from pathlib import Path

import pytest

from dqm_assistant import assessor
from dqm_assistant.context import RunContext
from dqm_assistant.detectors.base import Detector, register
from dqm_assistant.findings import (BAD, EXPECTED, GOOD, UNSURE, METHOD_ARTEFACT, NEW, PERSISTENT,
                                 REFERENCE_ARTEFACT, Finding, MethodCard)
from dqm_assistant.histsource import mu2e_path
from dqm_assistant.references import Reference, Registry

REF = Reference(id="r", version=2, source_version="006-001", run_type="cosmics",
                valid_runs=[1, None], runs=[100], status="approved")


class Fake(Detector):
    """Returns the flags it was given: {item: flag}."""

    def __init__(self, name, flags, needs_ref=True, false_alarms=("high statistics",), calibrated=False):
        super().__init__()
        self.name, self.flags = name, flags
        self.card = MethodCard(name=name, compares="fake", granularity="histogram",
                               needs_reference=needs_ref, false_alarms=false_alarms, calibrated=calibrated)

    def assess(self, ctx):
        return [Finding(run=ctx.run, subsystem=ctx.subsystem, item=i, method=self.name,
                        method_version="0", flag=f, reference=ctx.reference_id)
                for i, f in self.flags.items()]


def ctx(run=200, run_type="cosmics", reference=REF):
    return RunContext(run=run, subsystem="CRV", sid=118, source_version="006-001",
                      items=["A", "B", "C"], hists=None, reference=reference, run_type=run_type)


def hist_bad(item, runs, ref="r@v2", method="ks"):
    return [(r, [Finding(run=r, subsystem="CRV", item=item, method=method, method_version="0",
                         flag=BAD, reference=ref)]) for r in runs]


def by_item(report):
    return {g.items[0]: g for g in report.groups}


def test_new_fault_two_methods_is_bad_high_confidence():
    dets = [Fake("ks", {"A": BAD}), Fake("tranad", {"A": BAD}, needs_ref=False)]
    rep, _ = assessor.assess(ctx(), dets, history=[])
    g = by_item(rep)["A"]
    assert g.cls == NEW and g.confidence == "high" and rep.verdict == "BAD"


def test_single_method_known_false_alarm_is_method_artefact():
    dets = [Fake("ks", {"B": BAD}), Fake("vision", {"B": GOOD}, false_alarms=())]
    rep, _ = assessor.assess(ctx(), dets, history=[])
    assert by_item(rep)["B"].cls == METHOD_ARTEFACT and rep.verdict == "GOOD"


def test_flagged_in_most_runs_vs_same_reference_is_reference_artefact():
    dets = [Fake("ks", {"C": BAD})]
    history = hist_bad("C", range(190, 196))          # 6/6 recent runs, same reference
    rep, _ = assessor.assess(ctx(), dets, history)
    assert by_item(rep)["C"].cls == REFERENCE_ARTEFACT and rep.verdict == "NEEDS-EXPERT"


def test_persistent_has_onset():
    dets = [Fake("ks", {"A": BAD}), Fake("tranad", {"A": BAD}, needs_ref=False)]
    history = [(190, []), (191, [])] + hist_bad("A", [192, 193]) + [(194, []), (195, [])] + hist_bad("A", [196, 197])
    rep, _ = assessor.assess(ctx(), dets, history)
    g = by_item(rep)["A"]
    assert g.cls == PERSISTENT and g.onset_run == 196


def test_led_run_is_expected():
    rep, _ = assessor.assess(ctx(run_type="led"), [Fake("ks", {"A": BAD})], history=[])
    assert by_item(rep)["A"].cls == EXPECTED and rep.verdict == "GOOD"


def test_no_reference_is_reported_not_silently_skipped():
    dets = [Fake("ks", {"A": BAD}), Fake("tranad", {}, needs_ref=False)]
    rep, _ = assessor.assess(ctx(reference=None), dets, history=[])
    assert any("no approved reference" in n for n in rep.not_checked) and rep.verdict == "NEEDS-EXPERT"


def test_broken_detector_does_not_sink_the_run():
    class Boom(Fake):
        def assess(self, ctx):
            raise RuntimeError("gateway down")
    dets = [Boom("vision", {}), Fake("tranad", {"A": BAD}, needs_ref=False, calibrated=True)]
    rep, _ = assessor.assess(ctx(), dets, history=[])
    assert rep.verdict == "BAD" and any("vision: failed" in n for n in rep.not_checked)


def test_llm_pass_merges_names_and_can_reclassify():
    class FakeLLM:
        model = "fake"
        def json(self, system, user):
            return {"groups": [{"keys": ["A", "B"], "name": "dead block, channels 1024-1535",
                                "cls": "new", "reason": "same channels"}],
                    "summary": "One dead block.", "next_step": "Check FEB 12 HV."}
    dets = [Fake("ks", {"A": BAD, "B": BAD}), Fake("tranad", {"A": BAD, "B": BAD}, needs_ref=False)]
    rep, _ = assessor.assess(ctx(), dets, history=[], llm=FakeLLM())
    assert len(rep.groups) == 1 and rep.groups[0].items == ["A", "B"]
    assert rep.summary == "One dead block." and rep.llm_model == "fake"


def test_registry_uses_only_approved_and_never_the_run_itself():
    reg = Registry([
        Reference(id="r", version=1, source_version="006-001", run_type="cosmics",
                  valid_runs=[1, None], runs=[50], status="retired"),
        Reference(id="r", version=3, source_version="006-001", run_type="cosmics",
                  valid_runs=[1, None], runs=[60], status="candidate"),
        REF,
    ])
    assert reg.select("006-001", 200, "cosmics").key == "r@v2"
    assert reg.select("006-001", 100, "cosmics") is None      # 100 is the reference run
    assert reg.select("005-001", 200, "cosmics") is None


def test_mu2e_path_matches_the_file_on_pnfs():
    name = "dqm.mu2e.cosmics_crv.crvreco-006-001-file.125895_000771-001.root"
    assert mu2e_path(name, Path("/d")) == Path("/d/root/cb/60") / name


def test_service_and_mcp_tools_end_to_end(tmp_path):
    register("fake_ks")(type("FakeKS", (Fake,), {
        "__init__": lambda self, **kw: Fake.__init__(self, "ks", {"A": BAD}),
    }))
    (tmp_path / "refs.yaml").write_text(textwrap.dedent("""
        - {id: r, version: 2, source_version: "006-001", run_type: cosmics,
           valid_runs: [1, null], runs: [100], status: approved}
    """))
    cfg = tmp_path / "c.yaml"
    cfg.write_text(textwrap.dedent(f"""
        store: {tmp_path}/store
        references: {tmp_path}/refs.yaml
        llm: false
        subsystems:
          CRV: {{sid: 118, source_version: "006-001", dataset_dir: /nonexistent,
                 items: [A], detectors: [{{type: fake_ks}}]}}
    """))
    from dqm_assistant import server
    from dqm_assistant.service import Service
    server._svc = Service(str(cfg), use_llm=False, reader=False)

    rep = server.assess_run(200)
    assert rep["verdict"] == "BAD" and rep["groups"][0]["cls"] == NEW
    assert server.get_findings(200)[0]["method"] == "ks"
    assert server.list_flagged()[0]["run"] == 200
    assert server.get_reference(200)["key"] == "r@v2"
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert {"assess_run", "get_findings", "compare", "history", "list_flagged",
            "list_methods", "get_reference"} <= names


def test_nothing_checked_is_never_good():
    class Boom(Fake):
        def assess(self, ctx):
            raise RuntimeError("no files")
    rep, _ = assessor.assess(ctx(), [Boom("ks", {}), Boom("tranad", {}, needs_ref=False)], history=[])
    assert rep.verdict == "NEEDS-EXPERT" and "could judge" in rep.summary
    from dqm_assistant.findings import UNSURE
    rep, _ = assessor.assess(ctx(), [Fake("ks", {"A": UNSURE})], history=[])
    assert rep.verdict == "NEEDS-EXPERT"


def test_onset_at_start_of_history_is_a_lower_bound():
    dets = [Fake("ks", {"A": BAD}), Fake("tranad", {"A": BAD}, needs_ref=False)]
    rep, _ = assessor.assess(ctx(), dets, hist_bad("A", [190, 191]))
    g = by_item(rep)["A"]
    assert g.onset_run == 190 and g.onset_is_lower_bound and "at least" in g.reason
    rep, _ = assessor.assess(ctx(), dets, [(189, [])] + hist_bad("A", [190, 191]))
    assert by_item(rep)["A"].onset_is_lower_bound            # 189 judged nothing: still unknown


def test_unassessed_run_does_not_end_the_streak_as_good():
    dets = [Fake("ks", {"A": BAD}), Fake("tranad", {"A": BAD}, needs_ref=False)]
    unassessed = [(189, [Finding(run=189, subsystem="CRV", item="other", method="tranad",
                                 method_version="0", flag=BAD)])]      # A not judged in 189
    rep, _ = assessor.assess(ctx(), dets, unassessed + hist_bad("A", [190, 191]))
    g = by_item(rep)["A"]
    assert g.onset_run == 190 and g.onset_is_lower_bound and "2/2" in g.reason
    judged_good = [(189, [Finding(run=189, subsystem="CRV", item="A", method="ks",
                                  method_version="0", flag=GOOD)])]
    rep, _ = assessor.assess(ctx(), dets, judged_good + hist_bad("A", [190, 191]))
    g = by_item(rep)["A"]
    assert g.onset_run == 190 and not g.onset_is_lower_bound


def _scores(**kw):
    doc = {"schema": "dqm-method-scores/1", "method": "m", "method_version": "m.pkl", "sid": 118,
           "run": 7, "granularity": "subrun", "n_scored": 3, "items": ["a", "b"], "results": []}
    doc.update(kw)
    return doc


def test_tranad_score_output_reads_as_schema():
    """tranad-score's TranADEvaluator notes -> schema doc -> one Finding per item; no model or DB."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tranad-score"))
    from tranad_score.score import _result
    from dqm_assistant.detectors.remote import to_findings, validate
    results = [_result("tranad_outlier", 1, {"score": 2.0, "threshold": 1.0, "model": {},
                                             "top": [{"metric": "g/crv/PEs"}]}),
               _result("tranad_outlier", 2, {"score": 6.0, "threshold": 2.0,
                                             "top": [{"metric": "g/crv/rate"}, {"metric": "g/crv/PEs"}]}),
               _result("training_drift", 2, {"drifted": 2, "sigma": 3.0, "window": 20,
                                             "top": [{"metric": "g/crv/x", "shift": -4.5}]})]
    doc = validate(_scores(method="tranad", items=["tranad_outlier", "training_drift", "pca_outlier"],
                           results=results))
    fs = {f.item: f for f in to_findings(doc, "CRV")}
    assert fs["pca_outlier"].flag == GOOD
    bad = fs["tranad_outlier"]
    assert (bad.flag, bad.subrun, bad.score, bad.locus) == (BAD, 2, 6.0, "crv/rate, crv/PEs")
    assert bad.evidence["subruns_bad"] == 2 and bad.evidence["subruns_scored"] == 3
    assert bad.method_version == "m.pkl" and "model" not in bad.evidence
    drift = fs["training_drift"]
    assert (drift.score, drift.threshold, drift.evidence["drifted"]) == (4.5, 3.0, 2)


def test_schema_rules_no_data_unsure_and_direction():
    from dqm_assistant.detectors.remote import to_findings, validate
    assert to_findings(validate(_scores(n_scored=0)), "CRV") == []          # not checked, not GOOD
    doc = validate(_scores(granularity="run", direction="lower_is_worse", results=[
        {"item": "a", "flag": "BAD", "score": 0.01, "threshold": 0.05},
        {"item": "a", "flag": "BAD", "score": 0.0001, "threshold": 0.05, "locus": "FEB 12"},
        {"item": "b", "flag": "UNSURE", "evidence": {"why": "too few entries"}}]))
    fs = {f.item: f for f in to_findings(doc, "CRV")}
    assert (fs["a"].flag, fs["a"].score, fs["a"].locus) == (BAD, 0.0001, "FEB 12")
    assert fs["b"].flag == UNSURE and fs["b"].evidence["why"] == "too few entries"


@pytest.mark.parametrize("bad, msg", [
    ({"schema": "x/1"}, "schema"), ({"n_scored": -1}, "n_scored"),
    ({"results": [{"item": "zzz", "flag": "BAD"}]}, "not listed"),
    ({"results": [{"item": "a", "flag": "WEIRD"}]}, "flag"),
    ({"granularity": "event"}, "granularity")])
def test_schema_violations_are_named(bad, msg):
    from dqm_assistant.detectors.remote import SchemaError, validate
    with pytest.raises(SchemaError, match=msg):
        validate(_scores(**bad))


def test_remote_detector_file_and_command_transports(tmp_path):
    import json, sys
    from dqm_assistant.detectors import build
    doc = _scores(run=200, results=[{"item": "a", "flag": "BAD", "score": 3, "threshold": 1}])
    (tmp_path / "118").mkdir()
    (tmp_path / "118" / "200.json").write_text(json.dumps(doc))
    card = {"compares": "test", "false_alarms": ["x"]}
    by_file = build({"type": "remote", "method": "m", "card": card,
                     "path": str(tmp_path / "{sid}" / "{run}.json")})
    script = tmp_path / "emit.py"
    script.write_text("import json,sys\nprint('log noise')\n"
                      f"print(json.dumps(json.load(open({str(tmp_path / '118' / '200.json')!r}))))\n")
    by_cmd = build({"type": "remote", "method": "m", "card": card,
                    "command": [sys.executable, str(script), "{run}"]})
    for det in (by_file, by_cmd):
        fs = {f.item: f.flag for f in det.assess(ctx())}
        assert fs == {"a": BAD, "b": GOOD} and det.method_id == "m"
    assert by_file.card.false_alarms == ("x",)
    with pytest.raises(ValueError):
        build({"type": "remote", "method": "m"})                     # no transport
    wrong = build({"type": "remote", "method": "m", "path": str(tmp_path / "118" / "200.json")})
    with pytest.raises(Exception, match="run 201"):
        wrong.assess(ctx(run=201))                                   # document for another run


class _Boom(Fake):
    def assess(self, ctx):
        raise RuntimeError("no module named hist")


def test_failed_method_means_needs_expert_not_good():
    """The case that bit in practice: KS failed, TranAD passed -> was GOOD, must not be."""
    rep, _ = assessor.assess(ctx(), [_Boom("ks", {}), Fake("tranad", {"A": GOOD}, needs_ref=False)],
                             history=[])
    assert rep.verdict == "NEEDS-EXPERT"
    assert "ks did not judge the run" in rep.summary and "refresh=True" in rep.next_step
    assert (rep.methods_judged, rep.methods_not_judged) == (["tranad"], ["ks"])
    rep, _ = assessor.assess(ctx(), [Fake("ks", {"A": GOOD}), Fake("tranad", {"A": GOOD}, needs_ref=False)],
                             history=[])
    assert rep.verdict == "GOOD"                                  # everyone judged, nothing found


def test_failed_method_does_not_hide_a_real_problem():
    dets = [_Boom("ks", {}), Fake("tranad", {"A": BAD}, needs_ref=False, calibrated=True)]
    rep, _ = assessor.assess(ctx(), dets, history=[])
    assert rep.verdict == "BAD" and "Not judged by ks" in rep.summary


def test_remote_method_with_no_data_is_not_judged(tmp_path):
    import json
    from dqm_assistant.detectors import build
    (tmp_path / "200.json").write_text(json.dumps(_scores(run=200, n_scored=0)))
    remote = build({"type": "remote", "method": "m", "path": str(tmp_path / "{run}.json")})
    rep, _ = assessor.assess(ctx(), [Fake("ks", {"A": GOOD}), remote], history=[])
    assert rep.verdict == "NEEDS-EXPERT"
    assert any(n.startswith("m: not judged (no data") for n in rep.not_checked)


def test_llm_summary_failure_is_not_a_method_failure():
    class BadLLM:
        model = "x"
        def json(self, *a, **k):
            raise RuntimeError("gateway down")
    dets = [Fake("ks", {"A": BAD}), Fake("tranad", {"A": GOOD}, needs_ref=False)]   # method_artefact
    rep, _ = assessor.assess(ctx(), dets, history=[], llm=BadLLM())
    assert rep.verdict == "GOOD" and any("LLM summary failed" in n for n in rep.not_checked)


# --- histogram detectors on real mu2e_histcompare code (toy histograms, no model call) ------

class _ToyHists:
    """HistSource stand-in: run -> {item: hist.Hist}."""

    def __init__(self, by_run):
        self.by_run = by_run

    def hist(self, run, item):
        return self.by_run.get(run, {}).get(item)

    def summed(self, runs, item):
        return self.hist(runs[0], item)


def _toy(mu, seed=0, bins=50):
    hist = pytest.importorskip("hist")
    import numpy as np
    h = hist.Hist(hist.axis.Regular(bins, 0, 100))
    h.fill(np.random.default_rng(seed).normal(mu, 10, 20000))
    return h


def _hist_ctx(run_hists, ref_hists, items, reference=REF):
    return RunContext(run=200, subsystem="CRV", sid=118, source_version="006-001", items=items,
                      hists=_ToyHists({200: run_hists, 100: ref_hists}), reference=reference,
                      run_type="cosmics")


def test_ks_detector_uses_mu2e_histcompare_thresholds():
    pytest.importorskip("mu2e_histcompare")
    from dqm_assistant.detectors import build
    c = _hist_ctx({"d/PEr": _toy(50, 1), "d/logchi2": _toy(60), "d/rebinned": _toy(50, 1, bins=25)},
                  {"d/PEr": _toy(50, 2), "d/logchi2": _toy(50, 2), "d/rebinned": _toy(50, 2)},
                  ["d/PEr", "d/logchi2", "d/rebinned", "d/missing"])
    f = {x.item: x for x in build({"type": "ks"}).assess(c)}
    assert f["d/PEr"].flag == GOOD and f["d/PEr"].threshold == 0.01
    assert f["d/logchi2"].flag == BAD and f["d/logchi2"].evidence["status"] == "fail"
    assert "BAD below 0.01" in f["d/logchi2"].evidence["reading"]
    assert f["d/rebinned"].flag == UNSURE            # cantCompare: no verdict, not BAD
    assert f["d/missing"].flag == UNSURE and f["d/missing"].evidence["note"] == "histogram missing"


def test_vision_detector_bundled_instructions_and_reviewer(monkeypatch):
    pytest.importorskip("mu2e_histcompare")
    from mu2e_histcompare import vision as hc_vision
    from dqm_assistant.detectors import build

    class Stub:
        def review(self, content):
            return "Observations: shifted peak.\nVerdict: BAD", "BAD"

    monkeypatch.setattr(hc_vision, "make_reviewer", lambda *a, **k: Stub())
    monkeypatch.setenv("LITELLM_API_KEY", "test-not-a-key")    # never the real ~/.litellm_key
    det = build({"type": "vision", "instructions": "crv_real_draft"})
    c = _hist_ctx({"crvRecoDQM/PEr": _toy(60), "x/notaplot": _toy(50)},
                  {"crvRecoDQM/PEr": _toy(50, 2), "x/notaplot": _toy(50)}, ["crvRecoDQM/PEr", "x/notaplot"])
    f = {x.item: x for x in det.assess(c)}
    assert f["crvRecoDQM/PEr"].flag == BAD and "shifted peak" in f["crvRecoDQM/PEr"].evidence["text"]
    assert f["x/notaplot"].flag == UNSURE and "instructions" in f["x/notaplot"].evidence["note"]


def test_hydra_detector_scores_without_reference(tmp_path):
    pytest.importorskip("mu2e_histcompare")
    torch = pytest.importorskip("torch")
    from hydra_mu2e.model import PlotCNN
    from dqm_assistant.detectors import build

    torch.save(PlotCNN().state_dict(), tmp_path / "PEr.pt")     # untrained: plumbing only
    det = build({"type": "hydra", "models": str(tmp_path)})
    assert det.card.needs_reference is False
    c = _hist_ctx({"crvRecoDQM/PEr": _toy(50), "crvRecoDQM/logchi2": _toy(50)}, {},
                  ["crvRecoDQM/PEr", "crvRecoDQM/logchi2"], reference=None)
    f = {x.item: x for x in det.assess(c)}
    pe = f["crvRecoDQM/PEr"]
    assert pe.flag in (GOOD, BAD) and 0.0 <= pe.score <= 1.0 and pe.threshold == 0.5
    assert pe.reference is None and pe.evidence["model"].endswith("PEr.pt")
    assert f["crvRecoDQM/logchi2"].flag == UNSURE and "no model" in f["crvRecoDQM/logchi2"].evidence["note"]
    with pytest.raises(FileNotFoundError):
        build({"type": "hydra", "models": str(tmp_path / "nope")})


def test_on_demand_method_only_runs_through_compare(tmp_path):
    register("fake_ks2")(type("FakeKS2", (Fake,), {
        "__init__": lambda self, **kw: Fake.__init__(self, "ks", {"A": GOOD}),
    }))
    register("fake_vision")(type("FakeVision", (Fake,), {
        "__init__": lambda self, **kw: Fake.__init__(self, "vision", {"A": BAD}, false_alarms=()),
    }))
    (tmp_path / "refs.yaml").write_text(textwrap.dedent("""
        - {id: r, version: 2, source_version: "006-001", run_type: cosmics,
           valid_runs: [1, null], runs: [100], status: approved}
    """))
    cfg = tmp_path / "c.yaml"
    cfg.write_text(textwrap.dedent(f"""
        store: {tmp_path}/store
        references: {tmp_path}/refs.yaml
        llm: false
        subsystems:
          CRV: {{sid: 118, source_version: "006-001", dataset_dir: /nonexistent, items: [A],
                 detectors: [{{type: fake_ks2}}, {{type: fake_vision, on_demand: true}}]}}
    """))
    from dqm_assistant.service import Service
    s = Service(str(cfg), use_llm=False, reader=False)

    rep = s.assess_run(200, "CRV")
    assert rep["verdict"] == "GOOD"                              # vision's BAD is not in it
    assert rep["methods_judged"] == ["ks"] and rep["methods_not_judged"] == []
    assert {f["method"] for f in s.get_findings(200, "CRV")} == {"ks"}
    assert [f["flag"] for f in s.compare(200, "A", "CRV", method="vision")] == [BAD]
    assert {(m["name"], m["on_demand"]) for m in s.list_methods("CRV")} == {("ks", False), ("vision", True)}
