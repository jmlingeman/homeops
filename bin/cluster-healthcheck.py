#!/usr/bin/env python3
"""cluster-healthcheck — read-only weekly health gatherer for the home stack.

Covers three hosts and emits a dated Markdown report plus a machine-readable
findings JSON (consumed by bin/issue-sync.py to open de-duplicated Gitea issues):

  * Kubernetes cluster   (k3s, via KUBECONFIG)  — nodes, Flux HelmReleases /
                     Kustomizations, pods, chart/image versions.
  * This box (llm-server)— filesystem usage, SMART, GPU temperature / throttling
                     (nvidia-smi), CPU thermal zones, and the ninfer model repo.
  * TrueNAS SCALE NAS    (via REST API)          — system, pools, ZFS datasets,
                     scrub schedule, active alerts, disk SMART.

READ-ONLY: this script never mutates anything. It only runs GETs, `kubectl get`,
`smartctl -H`, `nvidia-smi -q`/`--query`, `df`, `git fetch`/`log`.

Zero dependencies: Python 3 standard library only (runs under the system
interpreter; no venv/uv required on the host).

Config: secrets/.env (NAS_API_URL, NAS_API_KEY, ...) plus environment overrides.
Output: reports/<YYYY-MM-DD>_cluster-health.md and ...json  (no secrets included).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import ssl
from pathlib import Path

# --------------------------------------------------------------------------- #
# Location & configuration                                                     #
# --------------------------------------------------------------------------- #
REPO = Path(__file__).resolve().parent.parent   # .../homeops
SECRETS = REPO / "secrets" / ".env"
REPORTS = REPO / "reports"
KUBECONFIG = REPO / "kubeconfig"
NINFER_DIR = Path(os.environ.get("NINFER_DIR", str(Path.home() / "llm" / "ninfer-3090")))

# Thresholds (override via env, e.g. DISK_WARN_PCT=85)
THRESH = {
    "disk_warn": float(os.environ.get("DISK_WARN_PCT", "80")),
    "disk_crit": float(os.environ.get("DISK_CRIT_PCT", "92")),
    "gpu_warn": float(os.environ.get("GPU_WARN_C", "83")),
    "gpu_crit": float(os.environ.get("GPU_CRIT_C", "90")),
    "dataset_warn": float(os.environ.get("DATASET_WARN_PCT", "90")),
    "restart_warn": int(os.environ.get("RESTART_WARN", "10")),
    "scrub_stale_days": int(os.environ.get("SCRUB_STALE_DAYS", "30")),
    "pool_used_warn": float(os.environ.get("POOL_USED_PCT", "90")),
}

# Alert classes that are informational, not actionable faults (skip for issues).
_BENIGN_ALERTS = {
    "scrubstarted", "scrubfinished", "resilverfinished", "resilverstarted",
    "poolimport", "bootenvactivation",
}

# Filesystems we ignore when scanning df output (pseudo / ephemeral / tiny boot).
IGNORE_FS = {"tmpfs", "devtmpfs", "squashfs", "overlay", "zram"}


def load_config() -> dict:
    cfg = dict(os.environ)
    if SECRETS.is_file():
        for line in SECRETS.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return cfg


# --------------------------------------------------------------------------- #
# Small helpers                                                                #
# --------------------------------------------------------------------------- #
def run(cmd: list[str], env: dict | None = None, timeout: int = 60) -> tuple[int, str, str]:
    """Run a command; return (rc, stdout, stderr). Never raises on failure."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except (OSError, FileNotFoundError) as e:
        return 127, "", str(e)


def http_json(url: str, cfg: dict, token: str | None = None, method: str = "GET",
              body: dict | None = None, verify: bool = False) -> tuple[int, object]:
    """Minimal JSON-over-HTTPS client (urllib). Returns (status_code, parsed|error-text)."""
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    data = None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
            code = r.status
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        code = e.code
        raw = e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 - network errors surfaced to the report
        return 0, f"request failed: {e}"
    try:
        return code, json.loads(raw)
    except json.JSONDecodeError:
        return code, raw[:500]


def _finding(key: str, severity: str, title: str, detail: str = "",
             source: str = "", actionable: bool = True) -> dict:
    return {"key": key, "severity": severity, "title": title,
            "detail": detail, "source": source, "actionable": actionable}


def _pct(used: float, total: float) -> float:
    return round(100.0 * used / total, 1) if total else 0.0


# --------------------------------------------------------------------------- #
# Kubernetes                                                                   #
# --------------------------------------------------------------------------- #
def check_kubernetes(cfg: dict, findings: list) -> dict:
    env = dict(cfg)
    env["KUBECONFIG"] = str(KUBECONFIG)
    out: dict = {}

    # Nodes
    rc, o, e = run(["kubectl", "get", "nodes", "-o", "json"], env=env, timeout=90)
    nodes = []
    if rc == 0:
        d = json.loads(o)
        for n in d.get("items", []):
            name = n["metadata"]["name"]
            conds = {c["type"]: c["status"] for c in n.get("status", {}).get("conditions", [])}
            ready = conds.get("Ready") == "True"
            kver = n.get("status", {}).get("nodeInfo", {}).get("kubeletVersion", "")
            nodes.append({"name": name, "ready": ready, "kubelet": kver})
            if not ready:
                bad = [t for t, s in conds.items() if s != "True" and t != "Ready"]
                findings.append(_finding(
                    f"k8s-node:{name}:notready", "crit",
                    f"Kubernetes node {name} is NotReady",
                    f"bad conditions: {', '.join(bad) or 'Ready!=True'}", "kubernetes"))
    else:
        findings.append(_finding("k8s:api-unreachable", "crit",
                                 "Could not reach the Kubernetes API", e[:300] or o[:300],
                                 "kubernetes"))
        out["nodes"] = nodes
        return out

    # Flux HelmReleases
    rc, o, _ = run(["kubectl", "get", "helmrelease", "-A", "-o", "json"], env=env, timeout=90)
    releases = []
    if rc == 0:
        d = json.loads(o)
        for h in d.get("items", []):
            ns = h["metadata"]["namespace"]
            name = h["metadata"]["name"]
            st = h.get("status", {})
            conds = st.get("conditions", []) or []
            readyc = next((c for c in conds if c.get("type") == "Ready"), None)
            ready = bool(readyc and readyc.get("status") == "True")
            msg = (readyc or {}).get("message", "") or next(
                (c.get("message", "") for c in conds), "")
            chartspec = h.get("spec", {}).get("chart", {}).get("spec", {}) or {}
            chartname = chartspec.get("chart", "")
            chart = chartspec.get("version", "")
            releases.append({"ns": ns, "name": name, "ready": ready,
                             "status": (readyc or {}).get("reason", ""),
                             "chart": chart, "chartname": chartname, "msg": msg[:200]})
            if not ready:
                findings.append(_finding(
                    f"flux-helmrelease:{ns}/{name}", "warn",
                    f"HelmRelease {ns}/{name} is not ready",
                    f"{(readyc or {}).get('reason','')}: {msg[:200]}", "kubernetes"))
    else:
        findings.append(_finding("flux:helmrelease-error", "warn",
                                 "Could not read Flux HelmReleases", "flux not installed?",
                                 "kubernetes", actionable=False))

    # Flux Kustomizations
    rc, o, _ = run(["kubectl", "get", "kustomization", "-A", "-o", "json"], env=env, timeout=90)
    kustos = []
    if rc == 0:
        d = json.loads(o)
        for k in d.get("items", []):
            ns = k["metadata"]["namespace"]
            name = k["metadata"]["name"]
            st = k.get("status", {})
            conds = st.get("conditions", []) or []
            readyc = next((c for c in conds if c.get("type") == "Ready"), None)
            ready = bool(readyc and readyc.get("status") == "True")
            kustos.append({"ns": ns, "name": name, "ready": ready})
            if not ready:
                findings.append(_finding(
                    f"flux-kustomization:{ns}/{name}", "warn",
                    f"Kustomization {ns}/{name} is not ready",
                    ((readyc or {}).get("message", "") or next(
                        (c.get("message", "") for c in conds), ""))[:200], "kubernetes"))

    # Pods (all namespaces)
    rc, o, _ = run(["kubectl", "get", "pods", "-A", "-o", "json"], env=env, timeout=120)
    pods = []
    if rc == 0:
        d = json.loads(o)
        for p in d.get("items", []):
            ns = p["metadata"]["namespace"]
            name = p["metadata"]["name"]
            phase = p.get("status", {}).get("phase", "Unknown")
            restarts = 0
            waited = 0
            wait_reasons = []
            for cs in p.get("status", {}).get("containerStatuses", []) or []:
                restarts += cs.get("restartCount", 0)
                ws = cs.get("state", {})
                for k, v in (ws or {}).items():
                    if k == "waiting":
                        waited += 1
                        reason = (v or {}).get("reason", "")
                        if reason and reason not in ("ContainerCreating",):
                            wait_reasons.append(reason)
            if phase in ("Running", "Succeeded"):
                # Running but waiting containers (crashloop / imagepull) or high restarts
                if waited:
                    findings.append(_finding(
                        f"k8s-pod:{ns}/{name}:waiting", "warn",
                        f"Pod {ns}/{name} has waiting container(s)",
                        ", ".join(sorted(set(wait_reasons)))[:200], "kubernetes"))
                if restarts >= THRESH["restart_warn"]:
                    findings.append(_finding(
                        f"k8s-pod-restarts:{ns}/{name}", "info",
                        f"Pod {ns}/{name} has {restarts} cumulative restarts",
                        "cumulative count (not a current fault); current waiting/"
                        "crash-loop states are reported separately",
                        "kubernetes", actionable=False))
            elif phase in ("Failed", "ImagePullBackOff", "ErrImagePull", "CrashLoopBackOff"):
                findings.append(_finding(
                    f"k8s-pod:{ns}/{name}:{phase.lower()}", "crit" if phase == "Failed" else "warn",
                    f"Pod {ns}/{name} is {phase}", "", "kubernetes"))
            elif phase == "Pending":
                findings.append(_finding(
                    f"k8s-pod-pending:{ns}/{name}", "warn",
                    f"Pod {ns}/{name} stuck Pending",
                    "check scheduling / resources / PVC", "kubernetes"))
            pods.append({"ns": ns, "name": name, "phase": phase,
                         "restarts": restarts})

    out.update({
        "nodes": nodes,
        "helmreleases": releases,
        "kustomizations": kustos,
        "pods": {"total": len(pods),
                 "by_phase": _count_phases(pods)},
        "charts": [{"ns": r["ns"], "name": r["name"],
                    "chart": r["chartname"], "version": r["chart"]}
                   for r in releases if r["chart"]],
    })
    return out


def _count_phases(pods: list) -> dict:
    c: dict = {}
    for p in pods:
        c[p["phase"]] = c.get(p["phase"], 0) + 1
    return c


# --------------------------------------------------------------------------- #
# Local box (this host)                                                        #
# --------------------------------------------------------------------------- #
def _local_name(cfg: dict) -> str:
    return os.environ.get("HEALTHBOX_NAME", cfg.get("HEALTHBOX_NAME",
             subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip() or "this-host"))


def check_local_box(cfg: dict, findings: list) -> dict:
    out: dict = {"hostname": _local_name(cfg)}

    # --- filesystem usage ---
    fs = []
    _, o, _ = run(["df", "-P", "-k"], timeout=30)
    seen = set()
    for line in o.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        dev, sizek, usedk, availk, usep, mount = parts[0], parts[1], parts[2], parts[3], parts[4].rstrip("%"), parts[5]
        if dev in IGNORE_FS or (dev.startswith("/dev/zram") and dev not in seen):
            continue
        # only the primary mount for a device (skip bind mounts of the same fs)
        if dev in seen and dev.startswith("/dev/"):
            continue
        if dev.startswith("/dev/"):
            seen.add(dev)
        try:
            size, used = int(sizek) * 1024, int(usedk) * 1024
            pct = float(usep)
        except ValueError:
            continue
        fs.append({"dev": dev, "mount": mount, "size": size,
                   "used_pct": pct, "avail": (int(sizek) - int(usedk)) * 1024})
        sev = None
        if pct >= THRESH["disk_crit"]:
            sev = "crit"
        elif pct >= THRESH["disk_warn"]:
            sev = "warn"
        if sev:
            findings.append(_finding(
                f"disk:{_local_name(cfg)}:{dev}", sev,
                f"{mount} at {pct}% full ({dev})",
                f"{_gb(used)} used / {_gb(size)} ({pct}%); {_gb(fs[-1]['avail'])} free",
                "local-disk"))
    out["filesystems"] = fs

    # --- SMART ---
    smart = []
    for dev in sorted({f["dev"] for f in fs if f["dev"].startswith("/dev/") and not f["dev"].endswith("boot")}):
        rc, o, e = run(["smartctl", "-H", dev], timeout=20)
        entry = {"dev": dev}
        if rc == 0:
            ok = "ok" in o.lower() and "failed" not in o.lower()
            model = re.search(r"SATA Version is:\s*(.+)", o) or re.search(r"Model Number:\s*(.+)", o)
            entry.update({"health": "passed" if ok else "FAILED",
                          "model": model.group(1).strip() if model else None,
                          "raw": o[:400]})
            if not ok:
                findings.append(_finding(
                    f"smart:{_local_name(cfg)}:{dev}", "crit",
                    f"SMART health check FAILED on {dev}", o[:300], "local-smart"))
        else:
            entry.update({"health": "unavailable", "err": e.strip()[:160] or o.strip()[:160]})
            # Permission-denied on a virtualized disk is a config gap, not hardware failure.
            if "permission denied" in (e + o).lower():
                findings.append(_finding(
                    f"smart:{_local_name(cfg)}:noaccess", "warn",
                    f"Cannot read SMART on {dev} (permission denied)",
                    "run smartctl as a user with device access, or add the service user to the appropriate group",
                    "local-smart"))
                break  # report the access gap once
        smart.append(entry)
    out["smart"] = smart

    # --- GPU (NVIDIA) ---
    gpu = {"present": shutil.which("nvidia-smi") is not None}
    if gpu["present"]:
        rc, o, _ = run(["nvidia-smi",
                        "--query-gpu=index,name,temperature.gpu,power.draw,"
                        "power.limit,clocks_throttle_reasons.active,"
                        "clocks_throttle_reasons.hw_thermal_slowdown,"
                        "clocks_throttle_reasons.sw_thermal_slowdown",
                        "--format=csv,noheader,nounits"], timeout=20)
        if rc == 0:
            gpus = []
            for line in o.strip().splitlines():
                f = [x.strip() for x in line.split(",")]
                if len(f) < 8:
                    continue
                idx, name, temp, pwr, plimit = f[0], f[1], _num(f[2]), _num(f[3]), _num(f[4])
                active = int(f[5] or 0, 16)
                hw_thermal = f[6].strip() == "1"
                sw_thermal = f[7].strip() == "1"
                throttling = bool(active) or hw_thermal or sw_thermal
                gpus.append({"index": idx, "name": name, "temp_c": temp,
                             "power_w": pwr, "throttling": throttling,
                             "active_reasons_hex": f[5].strip()})
                if temp is not None:
                    if temp >= THRESH["gpu_crit"]:
                        findings.append(_finding(
                            f"gpu:{_local_name(cfg)}:{idx}:hot", "crit",
                            f"GPU {idx} {name} at {temp}°C (critical)",
                            f"power {pwr}W; throttle={throttling}", "local-gpu"))
                    elif temp >= THRESH["gpu_warn"]:
                        findings.append(_finding(
                            f"gpu:{_local_name(cfg)}:{idx}:hot", "warn",
                            f"GPU {idx} {name} at {temp}°C (warm)",
                            f"power {pwr}W; throttle={throttling}", "local-gpu"))
                if throttling and (temp is None or temp < THRESH["gpu_warn"]):
                    findings.append(_finding(
                        f"gpu:{_local_name(cfg)}:{idx}:throttle", "warn",
                        f"GPU {idx} {name} is clock-throttled",
                        f"active reasons=0x{f[5].strip()}; hw_thermal={hw_thermal} sw_thermal={sw_thermal}"
                        + (f" (temp {temp}°C)" if temp is not None else ""),
                        "local-gpu"))
            gpu["cards"] = gpus
        else:
            gpu["error"] = o[:200] or "nvidia-smi failed"
    out["gpu"] = gpu

    # --- CPU thermal zones (may be absent on a VM) ---
    thermals = []
    tz_dir = Path("/sys/class/thermal")
    if tz_dir.is_dir():
        for z in sorted(tz_dir.glob("thermal_zone*")):
            try:
                t = int((z / "temp").read_text()) / 1000.0
            except Exception:  # noqa: BLE001
                continue
            typ = (z / "type").read_text().strip() if (z / "type").exists() else z.name
            maxf = z / "max_temp"
            maxc = int(maxf.read_text()) / 1000.0 if maxf.exists() else None
            thermals.append({"zone": z.name, "type": typ, "temp_c": t, "max_c": maxc})
            if maxc and t >= maxc * 0.9:
                findings.append(_finding(
                    f"cpu:{_local_name(cfg)}:{z.name}:hot", "warn",
                    f"CPU {typ} at {t:.0f}°C (near max {maxc:.0f}°C)", "", "local-cpu"))
    out["thermal_zones"] = thermals
    return out


def check_ninfer(cfg: dict, findings: list) -> dict:
    """Read-only check of the ninfer model repo for upstream updates."""
    out: dict = {"path": str(NINFER_DIR), "present": NINFER_DIR.is_dir()}
    if not out["present"]:
        findings.append(_finding("ninfer:missing", "warn",
                                 f"ninfer dir not found at {NINFER_DIR}", "", "ninfer"))
        return out
    env = dict(cfg)
    rc, o, e = run(["git", "-C", str(NINFER_DIR), "fetch", "--quiet", "--prune"],
                   env=env, timeout=120)
    if rc != 0:
        out["fetch_error"] = (e or o)[:200]
        findings.append(_finding("ninfer:fetch-failed", "warn",
                                 f"Could not fetch ninfer upstream", out["fetch_error"][:200], "ninfer"))
        return out
    rc, head, _ = run(["git", "-C", str(NINFER_DIR), "rev-parse", "--abbrev-ref", "HEAD"])
    branch = head.strip() or "main"
    rc, o, _ = run(["git", "-C", str(NINFER_DIR), "rev-list", f"--left-right",
                    "--count", f"HEAD...origin/{branch}"])
    ahead = behind = 0
    if rc == 0:
        c = o.split()
        ahead, behind = int(c[0]), int(c[1])
    out.update({"branch": branch, "ahead": ahead, "behind": behind})
    commits = []
    if behind > 0:
        rc, o, _ = run(["git", "-C", str(NINFER_DIR), "log", f"--oneline",
                        f"--no-merges", f"HEAD..origin/{branch}"], timeout=30)
        commits = [l.strip() for l in o.strip().splitlines() if l.strip()]
        out["upstream_commits"] = commits[:40]
        sev = "warn"
        detail = f"{behind} upstream commit(s) since local HEAD on {branch}\n" + \
                 "\n".join(f"  {c}" for c in commits[:15])
        if len(commits) > 15:
            detail += f"  … +{len(commits)-15} more"
        findings.append(_finding(
            "ninfer:updates-available", sev,
            f"ninfer model repo has {behind} new upstream commit(s)",
            detail, "ninfer"))
    return out


def _num(s: str):
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _gb(n: float) -> str:
    return f"{n / (1024**3):.0f}G"


# --------------------------------------------------------------------------- #
# TrueNAS SCALE NAS                                                            #
# --------------------------------------------------------------------------- #
def check_nas(cfg: dict, findings: list) -> dict:
    base = cfg.get("NAS_API_URL", "https://nas.local").rstrip("/")
    key = cfg.get("NAS_API_KEY", "")
    api = f"{base}/api/v2.0"

    def get(path: str):
        code, data = http_json(f"{api}{path}", cfg, token=key or None, verify=False)
        return code, data

    out: dict = {"url": base, "reachable": False}
    if not key:
        findings.append(_finding("nas:no-key", "warn", "NAS_API_KEY not configured",
                                 "set NAS_API_KEY in secrets/.env", "nas", actionable=False))
        return out

    # System info
    code, info = get("/system/info")
    if code != 200 or not isinstance(info, dict):
        out["error"] = f"system/info HTTP {code}: {str(info)[:200]}"
        findings.append(_finding("nas:unreachable", "crit",
                                 "NAS API unreachable", str(info)[:200], "nas"))
        return out
    out.update({
        "reachable": True,
        "version": info.get("version"),
        "hostname": info.get("hostname"),
        "uptime": info.get("uptime"),
        "loadavg": info.get("loadavg"),
        "cores": info.get("physical_cores"),
    })

    # Pools (status + capacity from the pool object)
    code, pools = get("/pool")
    pool_list = pools if isinstance(pools, list) else []
    out["pools"] = []
    for p in pool_list:
        name = p.get("name", "?")
        status = (p.get("status") or "").upper()
        size = p.get("size") or 0
        alloc = p.get("allocated") or 0
        free = p.get("free") or 0
        usedp = _pct(alloc, size)
        out["pools"].append({"name": name, "status": status, "size": size,
                             "allocated": alloc, "free": free, "used_pct": usedp,
                             "status_detail": p.get("status_detail"),
                             "warning": p.get("warning")})
        if status in ("DEGRADED", "FAULTED", "OFFLINE"):
            sev = "crit" if status in ("FAULTED", "OFFLINE") else "warn"
            detail = f"size={_gb(size)} allocated={_gb(alloc)} ({usedp}%)"
            if p.get("status_detail"):
                detail += f"; {p['status_detail']}"
            if p.get("warning"):
                detail += f"; WARNING: {p['warning']}"
            findings.append(_finding(
                f"nas-pool:{name}:{status.lower()}", sev,
                f"NAS pool {name} is {status}", detail, "nas"))
        elif status == "ONLINE" and size and usedp >= THRESH["pool_used_warn"]:
            findings.append(_finding(
                f"nas-pool:{name}:full", "warn",
                f"NAS pool {name} at {usedp}% capacity",
                f"{_gb(alloc)} / {_gb(size)} ({_gb(free)} free)", "nas"))

    # Datasets (context list; per-dataset space isn't exposed on this SCALE build,
    # so capacity is tracked at the pool level + via capacity alerts)
    code, dss = get("/pool/dataset")
    names, seen = [], set()

    def walk(nodes):
        for n in nodes:
            nm = n.get("name")
            if nm and nm not in seen:
                seen.add(nm)
                names.append(nm)
            walk(n.get("children") or [])

    if isinstance(dss, list):
        walk(dss)
    out["datasets"] = sorted(names)[:60]
    out["dataset_count"] = len(names)

    # Scrub schedule freshness
    code, scrubs = get("/pool/scrub")
    if isinstance(scrubs, list):
        now = _dt.datetime.now(_dt.timezone.utc).timestamp()
        for s in scrubs:
            pool = s.get("pool_name", "?")
            last = s.get("last_scrub_date")
            if last:
                try:
                    last_ts = last.timestamp()
                    days = (now - last_ts) / 86400
                    if days > THRESH["scrub_stale_days"]:
                        findings.append(_finding(
                            f"nas-pool-scrub:{pool}:stale", "warn",
                            f"NAS pool {pool} last scrub {days:.0f} days ago",
                            "schedule a scrub to catch latent sector errors", "nas"))
                except (AttributeError, ValueError):
                    pass

    # Active alerts
    code, alerts = get("/alert/list")
    actives = []
    if isinstance(alerts, list):
        for a in alerts:
            if not isinstance(a, dict):
                continue
            args = a.get("args")
            actives.append({"klass": a.get("klass"), "source": a.get("source"),
                            "args": args, "node": a.get("node"),
                            "created": (a.get("datetime") or {}).get("$date")})
    out["alerts"] = actives
    for a in actives:
        klass = (a.get("klass") or "").lower()
        # Skip purely informational alerts (e.g. scrub/scrub lifecycle, info notices)
        # so the report/issues only carry actionable conditions.
        if klass.endswith(("started", "finished")) or klass in _BENIGN_ALERTS:
            continue
        args_txt = json.dumps(a.get("args")) if a.get("args") is not None else ""
        if isinstance(a.get("args"), (dict, list)):
            args_txt = ", ".join(f"{k}={v}" for k, v in a["args"].items())
        title = f"{a.get('source','alert')} / {a.get('klass','')}"
        cls = a.get("klass") or a.get("source") or "alert"
        findings.append(_finding(
            f"nas-alert:{cls.lower()}", "crit" if "critical" in cls.lower() else "warn",
            f"NAS active alert: {title}",
            f"node={a.get('node')} {args_txt}".strip(), "nas"))

    # Disk SMART (best-effort; often N/A on a VM with virtual disks)
    code, disks = get("/disk")
    if isinstance(disks, list):
        out["disks"] = [{"dev": d.get("name"), "model": d.get("model"),
                         "size": d.get("size"), "health": d.get("health"),
                         "smart_ok": d.get("smart_ok")} for d in disks[:20]]
        for d in disks:
            if d.get("health") and d["health"].lower() not in ("passed", "ok", "good"):
                findings.append(_finding(
                    f"nas-disk:{d.get('name')}:smart", "crit",
                    f"NAS disk {d.get('name')} SMART health: {d.get('health')}", "", "nas"))
    return out


# --------------------------------------------------------------------------- #
# Report rendering                                                             #
# --------------------------------------------------------------------------- #
SEV_ICON = {"crit": "🔴", "warn": "🟠", "info": "ℹ️"}


def render_markdown(stamp: str, data: dict, findings: list) -> str:
    lines = [f"# Cluster health report — {stamp}", "",
             f"_Generated {data['generated']} · read-only check · sources: kubernetes, local, nas, ninfer_", ""]

    # Findings summary
    crit = [f for f in findings if f["severity"] == "crit"]
    warn = [f for f in findings if f["severity"] == "warn"]
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **{len(crit)} critical**, **{len(warn)} warnings**, "
                 f"{len(findings)} total findings")
    lines.append("")
    if findings:
        for f in sorted(findings, key=lambda x: ({"crit": 0, "warn": 1, "info": 2}[x["severity"]], x["key"])):
            lines.append(f"- {SEV_ICON.get(f['severity'],'•')} [{f['severity'].upper()}] "
                         f"**{f['title']}**`{f['key']}`")
        lines.append("")
    else:
        lines.append("No findings — everything checked reported healthy.")
        lines.append("")

    def section(title, body):
        lines.extend([f"## {title}", ""] + body + [""])

    # Kubernetes
    k = data.get("kubernetes", {})
    kbody = []
    nodes = k.get("nodes", [])
    kbody += [f"- Node **{n['name']}**: {'✅ Ready' if n['ready'] else '❌ NotReady'} "
              f"(kubelet {n.get('kubelet','?')})" for n in nodes] or ["- (no nodes)"]
    kbody += ["", "**Flux (HelmReleases):**"]
    rel = k.get("helmreleases", [])
    kbody += [f"- {r['ns']}/{r['name']}: {'✅' if r['ready'] else '⚠️ not ready'} "
              f"{r['chart']}" + (f" — {r['status']}" if not r['ready'] else "") for r in rel]
    kbody += ["", "**Pod phases:** " + ", ".join(f"{p}: {c}" for p, c in
                                                sorted(k.get('pods', {}).get('by_phase', {}).items()))]
    section("Kubernetes cluster", kbody)

    # Local box
    lb = data.get("local", {})
    lbody = [f"- Host: **{lb.get('hostname','?')}**"]
    lbody += [f"- {f['dev']} `{f['mount']}`: **{f['used_pct']}%** used "
              f"({_gb(f['size'])} total, {_gb(f['avail'])} free)" for f in lb.get("filesystems", [])]
    sm = lb.get("smart", [])
    if sm:
        lbody += ["", "**SMART:**"] + [f"- {s['dev']} {s.get('model','')}: {s.get('health','?')}"
                                        + (f" — {s.get('err','')}" if s.get('err') else "") for s in sm]
    gpu = lb.get("gpu", {})
    if gpu.get("present"):
        lbody += ["", "**GPU:**"]
        for g in gpu.get("cards", []):
            lbody.append(f"- {g['name']} (#{g['index']}): {g['temp_c']}°C, "
                         f"{g['power_w']}W, throttle={'yes' if g['throttling'] else 'no'}")
        if gpu.get("error"):
            lbody.append(f"- nvidia-smi error: {gpu['error']}")
    if lb.get("thermal_zones"):
        lbody += ["", "**CPU thermal:**"] + [f"- {t['type']}: {t['temp_c']}°C" for t in lb["thermal_zones"]]
    section(f"Local box ({lb.get('hostname','this-host')})", lbody)

    # Ninfer
    ni = data.get("ninfer", {})
    if ni.get("present"):
        istory = [f"- path: `{ni.get('path')}`",
                  f"- branch `{ni.get('branch')}`: ahead={ni.get('ahead',0)} behind={ni.get('behind',0)}"]
        for c in ni.get("upstream_commits", [])[:15]:
            istory.append(f"  - {c}")
        section("ninfer model repo", istory)

    # NAS
    nas = data.get("nas", {})
    if nas.get("reachable"):
        nbody = [f"- {nas.get('version')} on **{nas.get('hostname')}** "
                 f"(up {nas.get('uptime')}, load {nas.get('loadavg')})"]
        nbody += ["", "**Pools:**"] + [
            f"- {p['name']}: **{p['status']}** — {p['used_pct']}% of {_gb(p['size'])} "
            f"({_gb(p['allocated'])} allocated, {_gb(p['free'])} free)"
            + (f" — `{p['status_detail']}`" if p.get('status_detail') else "")
            + (f" ⚠️ {p['warning']}" if p.get('warning') else "")
            for p in nas.get("pools", [])] or ["- (none)"]
        ds = nas.get("datasets", [])
        if ds:
            preview = ", ".join(ds[:16]) + (f" … (+{len(ds)-16} more)" if len(ds) > 16 else "")
            nbody += ["", f"**Datasets ({nas.get('dataset_count', len(ds))}):** {preview}"]
        if nas.get("alerts"):
            nbody += ["", "**Active alerts:**"] + [
                f"- {a.get('source','alert')} / {a.get('klass','')}"
                + (f" — {a['args']}" if isinstance(a.get('args'), dict) else "")
                for a in nas["alerts"]]
        elif "alerts" in nas:
            nbody += ["", "**Active alerts:** none"]
        section(f"NAS ({nas.get('hostname','nas')})", nbody)
    else:
        section("NAS", [f"- ⚠️ unreachable — {nas.get('error','')}"])

    # Versions / chart inventory (for update awareness; Renovate tracks upgrades)
    charts = k.get("charts", [])
    if charts:
        vbody = ["> Image & chart upgrades are tracked by Renovate (GitHub PRs). "
                 "This is a snapshot of what is currently deployed.", ""]
        vbody += [f"| namespace | app | chart | version |", "|---|---|---|---|"] + \
                 [f"| {c['ns']} | {c['name']} | {c['chart']} | {c['version']} |" for c in charts]
        section("Deployed chart versions", vbody)

    lines += ["---", f"_findings file: reports/{stamp}_cluster-health.json — feed to "
                      f"`python3 bin/issue-sync.py` to reconcile Gitea issues_"]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# main                                                                         #
# --------------------------------------------------------------------------- #
def main() -> int:
    cfg = load_config()
    findings: list = []
    stamp = os.environ.get("HEALTHCHECK_STAMP", _dt.date.today().isoformat())
    data: dict = {
        "generated": _dt.datetime.now().isoformat(timespec="seconds"),
        "stamp": stamp,
        "kubernetes": check_kubernetes(cfg, findings),
        "local": check_local_box(cfg, findings),
        "ninfer": check_ninfer(cfg, findings),
        "nas": check_nas(cfg, findings),
    }
    data["findings"] = findings
    REPORTS.mkdir(parents=True, exist_ok=True)
    md_path = REPORTS / f"{stamp}_cluster-health.md"
    json_path = REPORTS / f"{stamp}_cluster-health.json"
    md_path.write_text(render_markdown(stamp, data, findings))
    json_path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")

    crit = sum(1 for f in findings if f["severity"] == "crit")
    warn = sum(1 for f in findings if f["severity"] == "warn")
    act = sum(1 for f in findings if f["actionable"])
    print(f"healthcheck done: {len(findings)} findings ({crit} crit, {warn} warn, {act} actionable)")
    print(f"  report: {md_path.relative_to(REPO)}")
    print(f"  json:   {json_path.relative_to(REPO)}")
    for f in sorted(findings, key=lambda x: ({"crit":0,"warn":1,"info":2}[x["severity"]], x["key"])):
        flag = "ACTION" if f["actionable"] else "note"
        print(f"   [{f['severity']:4}] {flag:5} {f['key']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
