#!/usr/bin/env bash
# Start dqm-assistant as a stdio MCP server, for hep-genesis (or any MCP client).
#
#   start-stdio.sh [CONFIG]       CONFIG defaults to $DQM_ASSISTANT_CONFIG,
#                                 then /exp/mu2e/data/users/$USER/dqm-assistant/config.yaml
#
# Python: the venv that ../install.sh built, $DQM_ASSISTANT_VENV (default: .venv at the
# repository root). Alternatively set DQM_ASSISTANT_ENV to a script that sets up an
# environment where `python3` has dqm_assistant's dependencies; it is sourced instead.
#
# On stdio, standard output carries the MCP messages and nothing else: anything an
# environment script prints goes to stderr, and the server's own log to $DQM_ASSISTANT_LOG
# (default: server.log next to the config).
#
# hep-genesis servers.json entry:
#   {"name": "dqm-assistant", "transport": "stdio",
#    "command": "/abs/path/dqm-assistant/assistant/start-stdio.sh"}

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
config="${1:-${DQM_ASSISTANT_CONFIG:-/exp/mu2e/data/users/$USER/dqm-assistant/config.yaml}}"
log="${DQM_ASSISTANT_LOG:-$(dirname "$config")/server.log}"

[[ -r "$config" ]] || { echo "dqm-assistant: no config at $config" >&2; exit 2; }

if [[ -n "${DQM_ASSISTANT_ENV:-}" ]]; then
  source "$DQM_ASSISTANT_ENV" >&2 2>&1 || { echo "dqm-assistant: env setup failed ($DQM_ASSISTANT_ENV)" >&2; exit 2; }
  export PYTHONPATH="$here:$here/../tranad-score:${PYTHONPATH:-}"
  py=python3
else
  venv="${DQM_ASSISTANT_VENV:-$here/../.venv}"
  py="$venv/bin/python"
  [[ -x "$py" ]] || { echo "dqm-assistant: no venv at $venv (run install.sh, or set DQM_ASSISTANT_VENV)" >&2; exit 2; }
fi
export TF_CPP_MIN_LOG_LEVEL=3

exec "$py" -m dqm_assistant.server --config "$config" 2>>"$log"
