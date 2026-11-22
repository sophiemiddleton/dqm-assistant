<!--
Section for a hep-genesis context file (HEP_CONTEXT_FILE), appended after Mu2e's
site/context.md: see "With agentlog" in assistant/README.md for how it is built.
The [agentlog] tag keeps it only in chats where agentlog is connected. The full
procedure is the workspace skill logging-dqm-assessments; this section makes sure
the model loads it, because a model does not reliably pick a skill on its own.
-->

## Run assessments and agentlog [agentlog]

agentlog is the one place you may write: it is the log of agent investigations, not the
shift logbook (ECL), which stays read-only. Its reports are permanent and readable by
everyone; nothing can edit or delete one.

- For any question about a run's data quality, or whether anyone has looked at a run:
  first call `load_skill("logging-dqm-assessments")` and follow it.
- Check `list_reports(run=...)` before `assess_run`, and tell the user what was already
  concluded, by whom and when. A human correction there outranks a fresh assessment.
  An earlier agentlog report is context, never a substitute: still call `assess_run`.
- "Make a report", "write a report" or "summarise" mean an answer or the session report,
  **not** agentlog. File in agentlog only when the user names agentlog (or "the log").
- Before `file_report` or `comment_on_report` in a chat, show the user the title, severity,
  subjects and a short summary of the body, and ask "File this permanently in agentlog?".
  Call it only after an explicit yes to that question. A chat started by an automation
  files without asking. If the user says not to file, don't.
