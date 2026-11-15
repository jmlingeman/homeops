# 95 — Working the NAS (TrueNAS) via the truenas MCP server

The **truenas** MCP server gives read-only access to the TrueNAS SCALE box
(`nas.local`). It lives in its own repo — **`jesse/truenas-mcp`** on the
self-hosted Gitea (local: `~/workspace/truenas-mcp`) — with the canonical
guideline, endpoint reference, and a self-test.

- Guideline (canonical): `~/workspace/truenas-mcp/SKILL.md`
- Endpoint reference: `~/workspace/truenas-mcp/references/api-endpoints.md`
- Active agent skill: `truenas` (auto-loaded; mirrors the rules below)
- Server + wiring: `~/workspace/truenas-mcp/server.py`, registered in
  `~/.omp/agent/mcp.json`

## When to use

Diagnosing or monitoring storage: pool status/capacity, dataset usage, disk
health/SMART, active alerts, scrub freshness, failover state — including any
NAS finding raised by the weekly health check (see `94`).

## Rules

1. **Read-only.** The MCP exposes GETs only. Never mutate the NAS from here; if a
   fix is required, file a Gitea issue and apply it via the TrueNAS UI or a
   deliberate, rollback-able change — not through these tools.
2. **No secrets.** The API key is sourced from `secrets/.env`
   (`NAS_API_URL` / `NAS_API_KEY`). Never print, commit, or paste it.
3. **This NAS is a QEMU VM**: its disks are virtual, so SMART/`health` are
   commonly `null` — expected, not a fault. Real SMART data comes from the
   *host* hypervisor.
4. **Capacity**: read it from `truenas_pools` (allocated/free + the
   `ZpoolCapacity*` alerts); per-dataset used/available isn't exposed on this
   TrueNAS build.
5. **Alerts**: ignore informational classes (`*Started`, `*Finished`); act on the
   rest (e.g. `ZpoolCapacityCritical`, `VolumeStatus`/degraded pool, `SMBPath`).

## Quick recipes

- "Is a pool degraded?" → `truenas_pools` (status) then `truenas_pool_status(name)` +
  `truenas_disks` to find the `FAULTED` vdev.
- "Is storage near full?" → `truenas_pools` free/size + `truenas_alerts` for
  `ZpoolCapacity*`.
- "Is it scrubbing / overdue?" → `truenas_scrub` (check `last_scrub_date` age).
- Anything else → `truenas_api("/<v2.0 path>")`.
