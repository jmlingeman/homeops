# reports/

Read-only **cluster health reports** written by `bin/cluster-healthcheck.py`, one
per run, named `YYYY-MM-DD_cluster-health.md` (+ a machine-readable
`YYYY-MM-DD_cluster-health.json` of the findings). The weekly job (OMP schedule
trigger, Monday 02:00) regenerates today's file, feeds it to `bin/issue-sync.py`
to reconcile Gitea issues, and commits the result.

## Contents

- `*.md` — human-readable report: summary + per-system sections (k3s cluster,
  the llm box, the TrueNAS NAS) + findings tables. Safe to commit: **no
  credentials or keys are ever written here.**
- `*.json` — the raw findings list. Each finding has a stable `key` used as the
  issue fingerprint, a `severity` (`crit`/`warn`/`info`), a `source`
  (`kubernetes`/`local`/`nas`/`ninfer`), a `title`, a `detail`, and an
  `actionable` flag. Only `actionable` findings become Gitea issues.

## Conventions

- Reports are append-a-new-file per date; a second run on the same day overwrites
  that day's files.
- Findings map 1:1 to Gitea issues on the self-hosted tracker, deduplicated by
  `key` (see `bin/issue-sync.py`). An issue is created only if no open issue
  already carries the same fingerprint; nothing is ever closed automatically.
- Keep this directory report-only. If a report looks like it contains a secret,
  treat it as a bug in `cluster-healthcheck.py` and fix the redaction at the
  source before committing.
