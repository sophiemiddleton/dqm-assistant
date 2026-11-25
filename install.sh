#!/usr/bin/env bash
# Build the Python environment for dqm-assistant from git sources only: no local checkouts of
# anyone's other code are needed.
#
#   ./install.sh [DEST] [--tranad] [--python VERSION]
#
#   DEST       the venv to create or update (default: .venv in this repository)
#   --tranad   also install TranAD: tranad-score, mu2e_tranad and torch (CPU)
#   --python   Python for the venv (default 3.12; uv downloads it if needed)
#
# What goes in, each a pip requirement you can override with a git URL at another ref, or a
# path to a local clone (for example MU2E_TRANAD_SPEC=/path/to/mu2e-tranad):
#
#   DQM_SPEC           DJ's Mu2e/DQM python package (dqm.reader, dqm.hist, dqm.evaluate)
#   MU2E_TRANAD_SPEC   mu2e_tranad (TranAD training/evaluation; carries its own copy
#                      of the ANL TranAD model, so anldq is not needed)          --tranad
#
# The defaults pin the commits dqm-assistant was tested with.
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
MU2E_TRANAD_SPEC="${MU2E_TRANAD_SPEC:-mu2e-tranad @ git+https://github.com/Mu2e/mu2e-tranad@961d4ab}"
# Beyond torch and mu2e_tranad's own requirements
TRANAD_DEPS=(pyyaml)

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
  echo "[3/3] TranAD: tranad-score, mu2e_tranad ($MU2E_TRANAD_SPEC), torch (CPU)"
  "$uv" pip install -q --python "$py" --torch-backend "${UV_TORCH_BACKEND:-cpu}" \
    "$DQM_SPEC" "$MU2E_TRANAD_SPEC" -e "$here/tranad-score" torch "${TRANAD_DEPS[@]}"
  "$py" -c "import mu2e_tranad.training.tranad_model as t; assert t.TRANAD_ANL_AVAILABLE, 'TranAD not importable'" \
    || { echo "ERROR: TranAD does not import; see the message above" >&2; exit 1; }
else
  echo "[3/3] TranAD skipped (--tranad to add it)"
fi

"$py" -c "import dqm_assistant.server, dqm.reader, dqm.hist.compare, dqm.evaluate.points" || { echo "ERROR: dqm-assistant does not import" >&2; exit 1; }
echo
echo "Done: $dest"
echo "  tests:  $py -m pytest -q $here/assistant/tests"
echo "  server: $here/assistant/start-stdio.sh   (uses this venv; DQM_ASSISTANT_VENV to point elsewhere)"
