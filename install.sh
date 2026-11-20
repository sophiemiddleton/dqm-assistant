#!/usr/bin/env bash
# Build the Python environment for dqm-assistant from git sources only: no local checkouts of
# anyone's other code are needed.
#
#   ./install.sh [DEST] [--tranad] [--python VERSION]
#
#   DEST       the venv to create or update (default: .venv in this repository)
#   --tranad   also install TranAD: tranad-score, dqm_pipeline, anldq and torch (CPU)
#   --python   Python for the venv (default 3.12; uv downloads it if needed)
#
# What goes in, each a pip requirement you can override with a git URL at another ref, or a
# path to a local clone (for example DQM_PIPELINE_SPEC=/path/to/Mu2e-TranADDQM):
#
#   DQM_SPEC           DJ's Mu2e/DQM python package (dqm.reader, dqm.hist, dqm.evaluate)
#   DQM_PIPELINE_SPEC  dqm_pipeline (TranAD training/evaluation)                --tranad
#   ANLDQ_SPEC         anldq (the TranAD model dqm_pipeline imports)            --tranad
#
# The defaults pin the commits dqm-assistant was tested with. anldq is installed without its
# own dependency list (ray, deephyper, optuna, ... are not needed to load TranAD); what its
# imports do need is listed below. Its dataset registry imports the SPT-3G library at load
# time, so a no-op `spt3g` stand-in is added when the real one is absent.
#
# Needs: git with read access to the repositories, and network access (PyPI, GitHub).
# Writes only DEST, plus uv's cache in $UV_CACHE_DIR (default /tmp/$USER/uv-cache).

set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

dest="" tranad=0 python=3.12
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) sed -n '2,/^$/s/^# \{0,1\}//p' "${BASH_SOURCE[0]}"; exit 0 ;;
    --tranad) tranad=1; shift ;;
    --python) python="${2:?--python needs a version}"; shift 2 ;;
    -*) echo "unknown option $1" >&2; exit 2 ;;
    *) [[ -z "$dest" ]] || { echo "one DEST only" >&2; exit 2; }; dest="$1"; shift ;;
  esac
done
dest="${dest:-$here/.venv}"

DQM_SPEC="${DQM_SPEC:-mu2e-dqm[hist,evaluate] @ git+https://github.com/Mu2e/DQM@v2.1.3#subdirectory=python}"
DQM_PIPELINE_SPEC="${DQM_PIPELINE_SPEC:-dqm_pipeline @ git+https://github.com/sophiemiddleton/Mu2e-TranADDQM@1da23d3}"
ANLDQ_SPEC="${ANLDQ_SPEC:-anldq @ git+ssh://git@github.com/sophiemiddleton/AIDQM@a138e911}"   # private repo: ssh
# What importing anldq's TranAD (and dqm_pipeline's evaluator) needs beyond torch
TRANAD_DEPS=(pandas scipy scikit-learn matplotlib seaborn tensorboard bottleneck tqdm pyyaml)

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/$USER/uv-cache}"
export UV_LINK_MODE=copy
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$(dirname "$dest")/.uv-python}"   # not ~/.local

# uv: on PATH, or downloaded next to the venv
uv="$(command -v uv 2>/dev/null || true)"
if [[ -z "$uv" ]]; then
  uv="$(dirname "$dest")/.uv/uv"
  if [[ ! -x "$uv" ]]; then
    echo "Downloading uv into $(dirname "$uv")"
    mkdir -p "$(dirname "$uv")"
    curl -LsSf https://astral.sh/uv/install.sh \
      | env UV_UNMANAGED_INSTALL="$(dirname "$uv")" INSTALLER_NO_MODIFY_PATH=1 sh >/dev/null
  fi
fi

echo "[1/3] venv $dest (Python $python)"
"$uv" venv -q --allow-existing --python "$python" "$dest"
py="$dest/bin/python"

echo "[2/3] dqm-assistant + mu2e-dqm ($DQM_SPEC)"
"$uv" pip install -q --python "$py" "$DQM_SPEC" -e "$here/assistant[llm,test]"

if (( tranad )); then
  echo "[3/3] TranAD: tranad-score, dqm_pipeline ($DQM_PIPELINE_SPEC), anldq ($ANLDQ_SPEC), torch (CPU)"
  "$uv" pip install -q --python "$py" --torch-backend "${UV_TORCH_BACKEND:-cpu}" \
    "$DQM_SPEC" "$DQM_PIPELINE_SPEC" -e "$here/tranad-score" torch "${TRANAD_DEPS[@]}"
  "$uv" pip install -q --python "$py" --no-deps "$ANLDQ_SPEC"
  if ! "$py" -c "import spt3g" 2>/dev/null; then
    site="$("$py" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
    mkdir -p "$site/spt3g"
    cat > "$site/spt3g/__init__.py" <<'EOF'
"""No-op stand-in for the SPT-3G library, which anldq's dataset registry imports at load time.
Installed by dqm-assistant's install.sh; DQM never uses the SPT-3G loader."""
class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, n): return _Any()
def __getattr__(name): return _Any()
EOF
    printf 'from spt3g import _Any\ndef __getattr__(name): return _Any()\n' > "$site/spt3g/core.py"
    cp "$site/spt3g/core.py" "$site/spt3g/calibration.py"
  fi
  "$py" -c "import dqm_pipeline.tranad_model as t; assert t.TRANAD_ANL_AVAILABLE, 'anldq TranAD not importable'" \
    || { echo "ERROR: TranAD does not import; see the message above" >&2; exit 1; }
else
  echo "[3/3] TranAD skipped (--tranad to add it)"
fi

"$py" -c "import dqm_assistant.server, dqm.reader, dqm.hist.compare, dqm.evaluate.points" || { echo "ERROR: dqm-assistant does not import" >&2; exit 1; }
echo
echo "Done: $dest"
echo "  tests:  $py -m pytest -q $here/assistant/tests"
echo "  server: $here/assistant/start-stdio.sh   (uses this venv; DQM_ASSISTANT_VENV to point elsewhere)"
