"""Score runs from the command line; prints one JSON object per run.

    python -m tranad_score --model crv_tranad_006-001.pkl --sid 118 125846 122834
"""

from __future__ import annotations

import argparse
import json

from tranad_score.score import Scorer


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="tranad_score")
    ap.add_argument("--model", required=True, help="bundle from run_pipeline.py --save-model")
    ap.add_argument("--sid", type=int, required=True, help="DQM source id the model was trained on")
    ap.add_argument("--detectors", default="tranad,drift", help="comma list from tranad,pca,drift")
    ap.add_argument("--threshold-scale", type=float, default=1.0)
    ap.add_argument("runs", type=int, nargs="+")
    a = ap.parse_args(argv)

    from dqm.reader import DqmReader

    reader = DqmReader()
    s = Scorer(a.model, a.sid, detectors=a.detectors.split(","), threshold_scale=a.threshold_scale)
    for run in a.runs:
        print(json.dumps(s.score_run(reader, run), default=str))


if __name__ == "__main__":
    main()
