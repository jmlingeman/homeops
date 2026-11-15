#!/usr/bin/env python3
"""issue-sync — reconcile the health-check findings with the homeops Gitea tracker.

Reads a findings JSON (from bin/cluster-healthcheck.py) and, for every *actionable*
finding, ensures exactly one **open** issue exists on the self-hosted Gitea
homeops repo:

  * key already has an open issue  -> leave it (never create a duplicate).
  * key has no open issue          -> open one (labels auto-created).
  * key recovered (flag --close-resolved) -> close the matching auto-filed issue.

Every issue body carries a stable fingerprint line  `<!-- hk:<key> -->`  so the
next run can match it regardless of title wording. De-duplication is therefore
exact and idempotent: re-running against the same state opens nothing new.

Zero dependencies (Python 3 stdlib). Credentials come from secrets/.env
(GITEA_URL, GITEA_USER, GITEA_TOKEN, GITEA_REPO) or environment overrides.

Usage:
  python3 bin/issue-sync.py [path/to/findings.json] [--close-resolved] [--dry-run]
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
import ssl
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SECRETS = REPO / "secrets" / ".env"
DEFAULT_PREFIX = os.environ.get("HEALTHCHECK_ISSUE_PREFIX", "cluster: ")


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


class Gitea:
    def __init__(self, url: str, user: str, token: str, repo: str, verify: bool = True):
        self.base = f"{url.rstrip('/')}/api/v1"
        self.repo = f"/repos/{user}/{repo}"
        self.token = token
        ctx = ssl.create_default_context()
        if not verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self.ctx = ctx

    def _req(self, method: str, path: str, body=None, expect_json: bool = True):
        headers = {"Authorization": f"token {self.token}", "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        r = urllib.request.Request(f"{self.base}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(r, context=self.ctx, timeout=30) as resp:
                raw = resp.read().decode("utf-8", "replace")
                code = resp.status
        except urllib.error.HTTPError as e:
            code, raw = e.code, e.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            return 0, f"request failed: {e}"
        if not expect_json:
            return code, raw
        try:
            return code, json.loads(raw)
        except json.JSONDecodeError:
            return code, raw[:400]

    def open_issue_count(self) -> int:
        code, data = self._req("GET", self.repo)
        if code == 200 and isinstance(data, dict):
            return int(data.get("open_issues_count", 0) or 0)
        return 0

    def list_open_issues(self, max_retries: int = 4, pause: float = 1.5) -> list:
        """List open issues, re-reading to ride out this instance's post-write
        consistency window (it can briefly report a stale/empty issue set)."""
        import time
        out = self._list_page()
        expected = self.open_issue_count()
        attempt = 0
        while len(out) < expected and attempt < max_retries:
            time.sleep(pause)
            attempt += 1
            out = self._list_page()
        return out

    def _list_page(self) -> list:
        out, page = [], 1
        while True:
            code, data = self._req("GET", f"{self.repo}/issues?state=open&limit=50&page={page}")
            if code != 200 or not isinstance(data, list):
                break
            out.extend(data)
            if len(data) < 50:
                break
            page += 1
        return out

    def label_ids(self, names: list[str]) -> list[int]:
        names = sorted(set(names))
        have = {}
        code, data = self._req("GET", f"{self.repo}/labels?limit=50")
        if code == 200 and isinstance(data, list):
            have = {l.get("name"): l.get("id") for l in data}
        ids = []
        for n in names:
            if n in have:
                ids.append(have[n])
                continue
            code, data = self._req("POST", f"{self.repo}/labels",
                                   {"name": n, "color": "#4c8bf5",
                                    "description": "cluster health check"})
            if code in (200, 201) and isinstance(data, dict) and data.get("id"):
                ids.append(data["id"])
            # label already existed via a race -> re-resolve
            else:
                code2, data2 = self._req("GET", f"{self.repo}/labels?limit=50")
                if code2 == 200 and isinstance(data2, list):
                    match = next((l.get("id") for l in data2 if l.get("name") == n), None)
                    if match:
                        ids.append(match)
        return ids

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict | None:
        ids = self.label_ids(labels) if labels else []
        payload = {"title": title, "body": body, "labels": ids}
        code, data = self._req("POST", f"{self.repo}/issues", payload)
        if code in (200, 201) and isinstance(data, dict) and data.get("number"):
            return data
        return {"error": f"HTTP {code}: {data}"}

    def close_issue(self, number: int, comment: str) -> bool:
        code, _ = self._req("PATCH", f"{self.repo}/issues/{number}", {"state": "closed"})
        if code == 200:
            self._req("POST", f"{self.repo}/issues/{number}/comments", {"body": comment})
            return True
        return False


HK = lambda key: f"<!-- hk:{key} -->"


def fingerprint_of(issue: dict) -> str | None:
    for line in (issue.get("body") or "").splitlines():
        line = line.strip()
        if line.startswith("<!-- hk:") and line.endswith("-->"):
            return line[len("<!-- hk:"):-len("-->")]
    return None


def build_body(finding: dict, report: str, prefix: str) -> str:
    detail = (finding.get("detail") or "").strip()
    head = f"Automated **cluster-health** finding."
    if prefix.strip().rstrip(":").strip():
        head += f" ({prefix.strip().rstrip(':').strip().lower()})"
    return (
        f"{head}\n"
        f"\n"
        f"- **Severity:** {finding['severity']}\n"
        f"- **Source:** {finding.get('source','?')}\n"
        f"- **Key:** `{finding['key']}`\n"
        f"- **First report:** `{report}`\n"
    ) + (f"\n## Detail\n\n{detail}\n\n" if detail else "\n") + (
        f"---\n"
        f"_Auto-filed by `bin/issue-sync.py` from the weekly read-only cluster health check. "
        f"Do not edit the fingerprint below; matching is done on it._\n"
        f"{HK(finding['key'])}"
    )


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    close_resolved = "--close-resolved" in flags
    dry = "--dry-run" in flags

    cfg = load_config()
    findings_path = args[0] if args else None
    if not findings_path:
        # most recent report JSON
        reports = sorted((REPO / "reports").glob("*_cluster-health.json"))
        if not reports:
            print("no findings JSON found (run bin/cluster-healthcheck.py first)", file=sys.stderr)
            return 1
        findings_path = str(reports[-1])
    data = json.loads(Path(findings_path).read_text())
    findings = [f for f in data.get("findings", []) if f.get("actionable")]
    report = Path(findings_path).name

    gitea = Gitea(cfg.get("GITEA_URL", "https://gitea.jesseisageek.com"),
                  cfg.get("GITEA_USER", "jesse"),
                  cfg.get("GITEA_TOKEN", ""),
                  cfg.get("GITEA_REPO", "homeops"))
    if not gitea.token:
        print("GITEA_TOKEN not set in secrets/.env", file=sys.stderr)
        return 1

    open_issues = gitea.list_open_issues()
    existing: dict[str, dict] = {}
    by_title: dict[str, dict] = {}
    for i in open_issues:
        k = fingerprint_of(i)
        if k:
            existing[k] = i
        if i.get("title"):
            by_title[i["title"].strip()] = i

    by_key = {f["key"]: f for f in findings}
    created, skipped = [], []
    for key, f in by_key.items():
        title = f"{DEFAULT_PREFIX}{f['title']}".strip()
        if key in existing or title in by_title:
            skipped.append(key)
            continue
        if dry:
            print(f"[dry] would create: {title}  (key={key})")
            continue
        res = gitea.create_issue(title, build_body(f, report, DEFAULT_PREFIX),
                                 ["cluster-health", f"area/{f.get('source','general')}"])
        if isinstance(res, dict) and res.get("number"):
            print(f"created #{res['number']}: {title}")
            created.append(key)
        else:
            print(f"FAILED to create {key}: {res}", file=sys.stderr)

    closed = []
    if close_resolved:
        for key, i in existing.items():
            if key not in by_key:
                if dry:
                    print(f"[dry] would close #{i['number']}: {i['title']} (recovered)")
                    continue
                if gitea.close_issue(i["number"],
                                     f"Resolved — no longer reported as of `{report}`. "
                                     "Auto-closed by issue-sync; reopen if it recurs."):
                    print(f"closed #{i['number']}: {i['title']} (recovered)")
                    closed.append(key)

    print(f"\nissue-sync: {len(created)} created, {len(skipped)} already open"
          + (f", {len(closed)} closed" if close_resolved else "")
          + f"  (findings: {len(findings)})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
