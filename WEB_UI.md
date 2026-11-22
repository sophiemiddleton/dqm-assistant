# Using dqm-assistant from the hep-genesis web UI

hep-genesis is the agent harness from [Mu2e/aitools](https://github.com/Mu2e/aitools)
(`harness/hep-genesis`). Its web UI runs on a gpvm, and you reach it from your laptop's browser
through an ssh tunnel. These steps assume the default locations; replace `mu2egpvm05` with
whichever gpvm you use.

## Every time

**1. On the gpvm**: start the UI in tmux, so it keeps running when you log out.

```bash
ssh mu2egpvm05.fnal.gov                 # by name: the mu2egpvm alias can land on another machine
tmux new -s genesis                     # or, if it exists already: tmux attach -t genesis
. /exp/mu2e/app/users/$USER/hep-genesis/current/env.sh
hep-genesis-web
```

It prints:

```
hep-genesis-web v0.5.0
  data:   /exp/mu2e/data/users/<you>/hep-genesis-data/projects
  UI:     .../src/desktop/out/web
  tunnel: ssh -L 8765:localhost:8765 mu2egpvm05.fnal.gov
  open:   http://localhost:8765/?token=<token>
```

Detach from tmux with `Ctrl-b` then `d`; the UI keeps running.

**2. On your laptop**: open the tunnel and keep that terminal open.

```bash
kinit <you>@FNAL.GOV                    # if you have no Kerberos ticket
ssh -L 8765:localhost:8765 mu2egpvm05.fnal.gov
```

**3. In your laptop's browser**: open the `open:` URL, **including** `?token=...`.

The token is new at every start of `hep-genesis-web`. After a restart, use the new URL.

**To stop:** `tmux attach -t genesis`, then `Ctrl-c`, then `exit`.

## In the UI

- **Servers:** `dqm-assistant` appears next to the Mu2e servers (dqm, runs, ecl, kb, ...).
  *Connect* on its row lists its tools, or says why it could not start.
- **Chats:** use the `dqm-assistant` project and ask, for example, *"What is going on with run
  125846?"*. Expand *"Worked through N steps"* above an answer to see which tools it called;
  `assess_run` is dqm-assistant.
- **Models:** the default is `gpt-oss:120b` on vllm.fnal.gov (no key). It can misread numbers
  and add details that are not in the tool results. For a stronger model, add **Fermilab
  LiteLLM** under Models with a key from https://llm-keys.fnal.gov, then make it active.

## One-time setup

Skip what you already have.

1. **Node >= 20**, needed only to build the UI. The gpvm system node is too old, so install it
   under `/exp`:
   ```bash
   V=v22.11.0; D=/exp/mu2e/app/users/$USER/node; mkdir -p $D; cd /tmp
   curl -fsSLO https://nodejs.org/dist/$V/node-$V-linux-x64.tar.xz
   curl -fsSLO https://nodejs.org/dist/$V/SHASUMS256.txt
   grep " node-$V-linux-x64.tar.xz$" SHASUMS256.txt | sha256sum -c -
   tar -xJf node-$V-linux-x64.tar.xz -C $D --strip-components=1
   ```
2. **hep-genesis with the UI**, from an aitools clone:
   ```bash
   export PATH=/exp/mu2e/app/users/$USER/node/bin:$PATH npm_config_cache=/tmp/$USER/npm-cache
   bash <aitools>/harness/hep-genesis/install.sh /exp/mu2e/app/users/$USER/hep-genesis
   . <aitools>/harness/hep-genesis/setup.sh     # first time only: creates your data folder
   ```
3. **dqm-assistant**: `./install.sh --tranad` in this repository, and a config in
   `/exp/mu2e/data/users/$USER/dqm-assistant/config.yaml` (see the [README](README.md)).
4. **Register dqm-assistant**: add it to
   `/exp/mu2e/data/users/$USER/hep-genesis-data/servers.json`, or in the UI under
   *Servers -> Add server* (transport *stdio*):
   ```json
   {"name": "dqm-assistant", "transport": "stdio",
    "command": "/abs/path/to/dqm-assistant/assistant/start-stdio.sh"}
   ```
5. **Optional, agentlog** (to keep conclusions): turn on the `agentlog` registry server under
   *Servers*, and link the skill into the hep-genesis workspace. See
   [assistant/README.md](assistant/README.md#with-agentlog-keeping-the-conclusions).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Browser shows `401` | The URL is missing its `?token=...`, or is from an earlier start. Copy the current `open:` line. |
| Browser cannot connect | The tunnel isn't open, or points at a different gpvm than the one running the UI. |
| `Port 8765 ... is unavailable` | Someone else is using it on that gpvm: `hep-genesis-web --port 8766`, and use 8766 in the tunnel too. |
| Page is blank / no UI | hep-genesis was installed with `--no-ui`. Redo one-time step 2. |
| dqm-assistant won't connect | Read `/exp/mu2e/data/users/$USER/dqm-assistant/server.log`, then run `start-stdio.sh` by hand to see its error. |
| Every issue is classed `new` | The store has no history yet. Replay some earlier runs first (see [assistant/README.md](assistant/README.md#run)). |

## Which machine

Use a regular gpvm for your own sessions. mu2eaigpvm01 is the shared service host: the MCP
registry, the Mu2e MCP servers, and the `mu2eai` automations account. dqm-assistant would move
there only as a shared HTTP server listed in the registry.
