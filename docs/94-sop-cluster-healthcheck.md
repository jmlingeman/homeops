# 94 — Weekly cluster health check & reports

A **read-only** job that inspects all three systems, writes a report, and keeps
the self-hosted Gitea tracker current with one issue per ongoing problem.

## What it checks

| System | Signals |
| --- | --- |
| k3s cluster (`kubeconfig` in repo) | not-Running pods (CrashLoop/Pending/ImagePull/Evicted), `Failed`/`Unknown` pods, restart counts, Flux `Kustomization`/`HelmRelease` `ready` status, pending chart upgrades (installed ≠ app_version), HelmRelease errors |
| llm-server box (this machine) | disk usage (`df`), GPU temp + clock/power throttle reasons (`nvidia-smi`), SMART (`smartctl`, root for real disks) |
| TrueNAS NAS (`nas.local`) | pool status + capacity, ZFS datasets, active alerts, scrub schedule (staleness), failover — via the NAS API key |
| ninfer model repo (`~/llm/ninfer-3090`) | local vs upstream `origin` commit delta + whether the bump is beneficial for our workflows |

## How it runs

Scheduled by an **OMP schedule trigger at Monday 02:00**. The prompt makes the
agent, in order:

1. `python3 bin/cluster-healthcheck.py` → `reports/<date>_cluster-health.{md,json}`
   (read-only; writes **no secrets**).
2. `python3 bin/issue-sync.py reports/<date>_cluster-health.json` → for each
   *actionable* finding, ensures exactly **one open issue** on the self-hosted
   Gitea `homeops` repo (deduplicated by a stable fingerprint key; never closes
   anything automatically).
3. Commit `reports/` and push to the Gitea `homeops` remote.
4. If a finding needs a *fix*, open a follow-up that applies the change through
   the appropriate skill in a **rollback-able** way (e.g. the `truenas` skill for
   the NAS, Flux/GitOps for the cluster), recording the before/after state.

Run it manually any time with steps 1–2 from `~/workspace/homeops`:

```sh
python3 bin/cluster-healthcheck.py
python3 bin/issue-sync.py reports/$(date +%F)_cluster-health.json   # --dry-run to preview
```

## Credentials

Live in `secrets/.env` (git-ignored, see `secrets/.env.example`): `NAS_API_URL`,
`NAS_API_KEY`, `GITEA_URL`, `GITEA_USER`, `GITEA_TOKEN`, `GITEA_REPO`,
`HEALTHCHECK_NAME`, optional `KUBECONFIG`. Both `cluster-healthcheck.py` and
`issue-sync.py` source this file. **Never** copy these values into a report,
commit, or chat message.

## Interpreting findings

- `severity`: `crit` (data/availability risk), `warn` (degradation / capacity),
  `info` (report-only awareness). Only `actionable` findings become issues.
- Recurring issues that keep reappearing mean the underlying fix hasn't landed —
  the issue stays open (it is not re-created) until a human closes it after
  verifying the fix. Use that as the backlog for building safe-fix skills.

## Related

- `95-sop-truenas-nas.md` — working the NAS via the truenas MCP server.
- `bin/cluster-healthcheck.py`, `bin/issue-sync.py` — the tooling.
