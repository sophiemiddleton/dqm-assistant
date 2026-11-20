#!/usr/bin/env bash
# Start dqm-assistant as a stdio MCP server, for hep-genesis (or any MCP client).
#
#   start-stdio.sh [CONFIG]       CONFIG defaults to $DQM_ASSISTANT_CONFIG,
#                                 then /exp/mu2e/data/users/$USER/dqm-assistant/config.yaml
#
# The Python environment (ana env, anldq/torch for TranAD, Mu2e/DQM python, dqm_pipeline)
# comes from $DQM_ASSISTANT_ENV, a script to source; default: CrossExperimentalAIDQM's
# envs/setup_ana_env.sh.
#
# On stdio, standard output carries the MCP messages and nothing else: everything the
# environment setup prints goes to stderr, and the server's own log to $DQM_ASSISTANT_LOG
# (default: server.log next to the config).
#
# hep-genesis servers.json entry:
#   {"name": "dqm-assistant", "transport": "stdio",
#    "command": "/abs/path/dqm-assistant/assistant/start-stdio.sh"}

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
envsetup="${DQM_ASSISTANT_ENV:-/exp/mu2e/app/users/$USER/CrossExperimentalAIDQM/envs/setup_ana_env.sh}"
config="${1:-${DQM_ASSISTANT_CONFIG:-/exp/mu2e/data/users/$USER/dqm-assistant/config.yaml}}"
log="${DQM_ASSISTANT_LOG:-$(dirname "$config")/server.log}"

[[ -r "$config" ]] || { echo "dqm-assistant: no config at $config" >&2; exit 2; }

[[ -r "$envsetup" ]] || { echo "dqm-assistant: no environment script at $envsetup (set DQM_ASSISTANT_ENV)" >&2; exit 2; }
source "$envsetup" >&2 2>&1 || { echo "dqm-assistant: env setup failed ($envsetup)" >&2; exit 2; }
export PYTHONPATH="$here:$PYTHONPATH"
export TF_CPP_MIN_LOG_LEVEL=3

exec python3 -m dqm_assistant.server --config "$config" 2>>"$log"
