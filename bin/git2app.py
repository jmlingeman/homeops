#!/usr/bin/env python3
"""
git2app — add a Kubernetes app to this cluster's *template layer* from a
git repository URL (or local path).

It inspects the repo for a docker-compose file or Dockerfile, asks which
template namespace the app belongs in (or creates one), and generates the
persistent files under bootstrap/templates/kubernetes/apps/<ns>/<app>/:

    ks.yaml.j2                 → Flux Kustomization (cluster-apps-<app>)
    app/kustomization.yaml.j2  → kustomization (HR [+ secret])
    app/helmrelease.yaml.j2    → app-template HelmRelease
    app/secret.sops.yaml.j2    → sops-encrypted Secret (only if it has secrets)

…registers the app in the namespace kustomization template (creating the
namespace template pair if it's new), and adds any secret values as
bootstrap_<app>_<var> keys in bootstrap/vars/config.yaml (gitignored).

Then (unless --no-deploy): `task configure` → kubeconform (if available) →
shows the resulting git changes → asks before committing + pushing via
./deploy.sh.

Stdlib + PyYAML only.
"""

import argparse
import getpass
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("git2app needs PyYAML:  python3 -c 'import yaml'  (pip install pyyaml)")

REPO_ROOT = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True, check=True,
).stdout.strip()
T_APP = Path(REPO_ROOT) / "bootstrap/templates/kubernetes/apps"
CONFIG_YAML = Path(REPO_ROOT) / "bootstrap/vars/config.yaml"
DEPLOY_SH = Path(REPO_ROOT) / "deploy.sh"

K8S_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
SECRETISH_RE = re.compile(r"(?i)(passw|pwd|secret|token|key|auth|credential|api)")
APP_TEMPLATE_VERSION = "2.4.0"
SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", ".github"}


# ---------------------------------------------------------------- helpers

def die(msg):
    sys.exit(f"\ngit2app: {msg}")


def ask(prompt, default=None, secret=False, allow_empty=False):
    suffix = f" [{default}]" if default not in (None, "") else ""
    while True:
        try:
            raw = getpass.getpass(f"{prompt}{suffix}: ") if secret else input(f"{prompt}{suffix}: ")
        except EOFError:
            die("no answer on stdin — run me in a TTY")
        if raw.strip() == "":
            if default not in (None, ""):
                return default
            if allow_empty:
                return ""
            print("  (required)")
            continue
        return raw.strip()


def ask_int(prompt, default, lo=1, hi=999):
    msg = f"  enter a number between {lo} and {hi}"
    while True:
        raw = ask(prompt, default)
        try:
            n = int(raw)
        except ValueError:
            print(msg)
            continue
        if lo <= n <= hi:
            return n
        print(msg)


def ask_proto():
    while True:
        p = (ask("protocol?", "tcp") or "").lower()
        if p in ("tcp", "udp"):
            return p
        print("  tcp or udp")


def ask_pick(prompt, options, default=1):
    print(prompt)
    for i, o in enumerate(options, 1):
        print(f"  {i}. {o}")
    n = ask_int("pick", default, 1, len(options))
    return options[n - 1]


def ask_yn(prompt, default_yes=False):
    d = "Y/n" if default_yes else "y/N"
    while True:
        raw = (ask(prompt, d) or "").lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False


def k8s_name(raw, fallback):
    name = re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-")[:30].strip("-") or fallback
    if not K8S_NAME_RE.match(name):
        die(f"'{name}' is not a valid k8s name")
    return name


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=REPO_ROOT, **kw)


# ---------------------------------------------------------------- discovery

def clone(url):
    dest = tempfile.mkdtemp(prefix="git2app-")
    print(f"→ cloning {url} (shallow)…")
    r = subprocess.run(["git", "clone", "--depth", "1", "--quiet", url, dest])
    if r.returncode != 0:
        die("git clone failed (is the URL reachable? private repos need git auth configured)")
    return Path(dest)


def find_files(root, names, maxdepth=2):
    names = set(names)
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if depth >= maxdepth:
            continue
        for f in filenames:
            if f in names:
                hits.append(Path(dirpath) / f)
    return sorted(hits)


def find_dockerfiles(root, maxdepth=2):
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if depth >= maxdepth:
            continue
        for f in filenames:
            if f.lower().startswith("dockerfile"):
                hits.append(Path(dirpath) / f)
    return sorted(hits)


def load_compose(path):
    docs = [d for d in yaml.safe_load_all(path.read_text()) if d]
    if not docs:
        die(f"{path} is not a valid compose file")
    svc = docs[0].get("services") or {}
    if not svc:
        die(f"{path} has no services")
    return svc


def parse_ports(ports):
    """compose `ports` list → [(container_port, protocol), …]."""
    out = []
    for p in ports or []:
        s = str(p)
        proto = s.rsplit("/", 1)[1] if "/" in s else "tcp"
        parts = s.split("/")[0].split(":")
        if len(parts) >= 3:          # [ip:]host:container
            container = parts[-1]
        elif len(parts) == 2:        # host:container
            container = parts[-1]
        else:                         # bare container (or host-only)
            container = parts[0]
        if re.match(r"^\d+$", container):
            out.append((int(container), proto))
    return out


def parse_env(service, clone_root):
    """service `environment` (map or list) + `env_file` → {NAME: value}."""
    env = {}
    for f in service.get("env_file") or []:
        p = Path(f) if Path(f).is_absolute() else clone_root / f
        if p.is_file():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env.setdefault(k, v.strip().strip('"'))
        else:
            print(f"  ! env_file {f!r} not found in repo — skipped")
    e = service.get("environment") or {}
    if isinstance(e, list):
        for item in e:
            k, _, v = str(item).partition("=")
            env[k] = v
    elif isinstance(e, dict):
        env.update({k: ("" if v is None else str(v)) for k, v in e.items()})
    return env


def parse_volumes(vols):
    """compose `volumes` → (named: [(vol, mount)], binds: [raw])."""
    named, binds = [], []
    for v in vols or []:
        parts = str(v).split(":")
        if len(parts) == 3:
            parts = parts[:2]            # drop :ro / :rw
        if len(parts) != 2:
            print(f"  ! volume {v!r} unrecognized — skipped")
            continue
        src, dst = parts
        if src.startswith((".", "/", "~")) or "\\" in src:
            binds.append(str(v))
        else:
            named.append((src, dst))
    return named, binds


def normalize_image(image):
    """'nginx' → ('docker.io/library/nginx','latest'); keeps digests verbatim."""
    if not image:
        return "", "latest"
    if "@" in image:
        return image, "pinned"
    first, _, rest = image.partition("/")
    if not ("." in first or ":" in first or first == "localhost"):
        image = "docker.io/" + image
        if "/" not in image[len("docker.io/"):]:
            image = "docker.io/library/" + image[len("docker.io/"):]
    if ":" not in image.rsplit("/", 1)[-1]:
        image += ":latest"
    repo, _, tag = image.rpartition(":")
    return repo, tag


# ---------------------------------------------------------------- generation

def var_name(app, env_key):
    return re.sub(r"[^a-z0-9_]", "_", f"bootstrap_{app}_{env_key}".lower())


def gen_ks(app, ns):
    return f"""---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app cluster-apps-{app}
  namespace: flux-system
spec:
  targetNamespace: {ns}
  path: ./kubernetes/apps/{ns}/{app}/app
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  prune: true
  sourceRef:
    kind: GitRepository
    name: home-kubernetes
  wait: true
  interval: 30m
  retryInterval: 1m
  timeout: 5m
"""


def gen_kustomization(has_secrets):
    lines = [
        "---",
        "apiVersion: kustomize.config.k8s.io/v1beta1",
        "kind: Kustomization",
        "resources:",
        "  - ./helmrelease.yaml",
    ]
    if has_secrets:
        lines.append("  - ./secret.sops.yaml")
    return "\n".join(lines) + "\n"


def gen_helmrelease(app, ns, repo, tag, port, proto, exposure, env_plain, secrets, persistence):
    values = {
        "controllers": {
            "main": {
                "annotations": {"reloader.stakater.com/auto": "true"},
                "containers": {
                    "main": {
                        "image": {"repository": repo, "tag": tag, "imagePullPolicy": "IfNotPresent"},
                        "imagePullPolicy": "IfNotPresent",
                        "env": {},
                    }
                },
            }
        },
        "service": {"main": {"ports": {proto: {"port": port}}}},
    }
    env = values["controllers"]["main"]["containers"]["main"]["env"]
    env["TZ"] = "${TIMEZONE}"
    for k, v in sorted(env_plain.items()):
        env[k] = v
    for k in sorted(secrets):
        env[k] = {"valueFrom": {"secretKeyRef": {"name": f"{app}-secret", "key": k}}}

    if exposure != "none":
        ingress = {
            "enabled": True,
            "className": exposure,
            "hosts": [{
                "host": app + ".${SECRET_DOMAIN}",
                "paths": [{"path": "/", "pathType": "Prefix",
                           "service": {"name": "main", "port": proto}}],
            }],
            "tls": [{"hosts": [app + ".${SECRET_DOMAIN}"]}],
        }
        if exposure == "internal":
            ingress["annotations"] = {"hajimari.io/enable": "true"}
        else:
            # external-dns (--ingress-class=external, sources: crd+ingress)
            # creates <app>.* → external.* → the Cloudflare tunnel
            ingress["annotations"] = {
                "external-dns.alpha.kubernetes.io/target": "external.${SECRET_DOMAIN}"}
        values["ingress"] = {"main": ingress}

    if persistence:
        values["persistence"] = persistence

    doc = {
        "apiVersion": "helm.toolkit.fluxcd.io/v2beta2",
        "kind": "HelmRelease",
        "metadata": {"name": app, "namespace": ns},
        "spec": {
            "interval": "30m",
            "chart": {"spec": {
                "chart": "app-template",
                "version": APP_TEMPLATE_VERSION,
                "sourceRef": {"kind": "HelmRepository", "name": "bjw-s",
                              "namespace": "flux-system"},
            }},
            "maxHistory": 2,
            "install": {"createNamespace": True, "remediation": {"retries": 3}},
            "upgrade": {"cleanupOnFail": True, "remediation": {"retries": 3}},
            "uninstall": {"keepHistory": False},
            "values": values,
        },
    }
    return yaml.safe_dump(doc, sort_keys=False, default_flow_style=False, width=100)


def gen_secret(app, ns, secrets):
    out = [
        "#jinja2: trim_blocks: True, lstrip_blocks: True",
        "---",
        "apiVersion: v1",
        "kind: Secret",
        "metadata:",
        f"  name: {app}-secret",
        f"  namespace: {ns}",
        "type: Opaque",
        "stringData:",
    ]
    for k in sorted(secrets):
        out.append("  " + k + ': "{{ ' + var_name(app, k) + ' }}"')
    return "\n".join(out) + "\n"


def gen_namespace(ns):
    return f"""---
apiVersion: v1
kind: Namespace
metadata:
  name: {ns}
  labels:
    kustomize.toolkit.fluxcd.io/prune: disabled
"""


def gen_ns_kustomization(ns, app):
    return f"""---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./namespace.yaml
  - ./{app}/ks.yaml
"""


def register_in_ns_kustomization(ns, app):
    ns_dir = T_APP / ns
    if not ns_dir.is_dir() or not (ns_dir / "kustomization.yaml.j2").exists():
        (ns_dir / app).mkdir(parents=True, exist_ok=True)
        (ns_dir / "namespace.yaml.j2").write_text(gen_namespace(ns))
        (ns_dir / "kustomization.yaml.j2").write_text(gen_ns_kustomization(ns, app))
        print(f"  + NEW namespace template: {ns_dir.relative_to(REPO_ROOT)}")
        return
    line = f"  - ./{app}/ks.yaml\n"
    kust = ns_dir / "kustomization.yaml.j2"
    text = kust.read_text()
    if line in text:
        print(f"  = already registered in {kust.name}")
        return
    if not text.endswith("\n"):
        text += "\n"
    kust.write_text(text + line)
    print(f"  + registered in {kust.relative_to(REPO_ROOT)}")


def add_config_vars(app, secrets, values):
    """Update/append bootstrap_<app>_<var> keys in bootstrap/vars/config.yaml.

    Text-level on purpose: the file carries comments a YAML round-trip would
    destroy. Returns the list of secret names left with empty values.
    """
    lines = CONFIG_YAML.read_text().splitlines(keepends=True)
    out, touched = [], set()
    for line in lines:
        # ^ anchor on the raw line matches only top-level "key:" lines,
        # never indented/nested ones
        if re.match(r"^[\w-]+:", line):
            key = line.split(":", 1)[0].strip()
            match = [sk for sk, vn in secrets.items() if vn == key]
            if match:
                val = values.get(match[0], "")
                line = f'{key}: "{val}"\n'
                touched.add(match[0])
        out.append(line)
    if len(touched) < len(secrets):
        out.append(f"\n# {app} (added by git2app)\n")
        for sk in sorted(set(secrets) - touched):
            out.append(f'{secrets[sk]}: "{values.get(sk, "")}"\n')
    CONFIG_YAML.write_text("".join(out))
    unfilled = sorted(sk for sk in secrets if not values.get(sk))
    print(f"  + config vars in {CONFIG_YAML.name}: {', '.join(sorted(secrets.values()))}")
    if unfilled:
        print(f"  ! fill these before deploying: {', '.join(unfilled)}")
    return unfilled


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", help="git URL (or local path) containing a Dockerfile / docker-compose")
    ap.add_argument("--no-deploy", action="store_true",
                    help="stop after generating the templates (no task configure / commit / push)")
    ap.add_argument("--name", help="app name (default: derived from repo name)")
    ap.add_argument("--namespace", help="target template namespace (default: ask)")
    args = ap.parse_args()

    clone_root = clone(args.repo)
    repo_name = re.sub(r"\.git$", "", args.repo.rstrip("/").rsplit("/", 1)[-1]) or "app"

    compose_files = find_files(clone_root, {"docker-compose.yml", "docker-compose.yaml",
                                            "compose.yml", "compose.yaml"})
    dockerfiles = find_dockerfiles(clone_root)
    if not compose_files and not dockerfiles:
        die("no docker-compose file or Dockerfile found (searched 2 levels deep)")

    # ---- pick compose service / image
    if compose_files:
        compose_path = (ask_pick("compose files found:",
                                 [f.relative_to(clone_root) for f in compose_files])
                        if len(compose_files) > 1 else compose_files[0])
        print(f"→ using {compose_path}")
        services = load_compose(compose_path)
        svc_name = (ask_pick("services:", list(services))
                    if len(services) > 1 else next(iter(services)))
        svc = services[svc_name]
        image = svc.get("image")
        ports = parse_ports(svc.get("ports"))
        env = parse_env(svc, clone_root)
        vols = parse_volumes(svc.get("volumes"))
        print(f"→ service '{svc_name}': image={image or '<none>'} ports={ports} "
              f"env={list(env)} volumes={vols}")
        if not image:
            image = ask("no `image:` in compose — full image (repo[:tag])?",
                        f"docker.io/{repo_name}")
    else:
        print(f"→ no compose; Dockerfile(s): {[f.name for f in dockerfiles]}")
        image = ask("full image (repo[:tag])?", f"docker.io/{repo_name}:latest")
        ports, env, vols = [], {}, ([], [])

    app = k8s_name(args.name or ask("app name?", repo_name), repo_name)

    # ---- namespace
    ns = (args.namespace or "").lower()
    if not ns:
        existing = sorted(d.name for d in T_APP.iterdir() if d.is_dir())
        pick = ask_pick("template namespaces:", existing + ["<new>"], 1)
        ns = k8s_name(ask("new namespace name?", "custom"), "custom") if pick == "<new>" else pick
    if not K8S_NAME_RE.match(ns):
        die(f"'{ns}' is not a valid k8s namespace name")
    if (T_APP / ns / app).exists():
        die(f"{T_APP / ns / app} already exists — this would overwrite it")

    # ---- port / protocol
    if ports:
        port, proto = ports[0]
        if len(ports) > 1:
            print(f"  multiple ports {ports} — using the first; tell me if that's wrong")
    else:
        port = ask_int("container port?", 80, hi=65535)
        proto = ask_proto()

    # ---- exposure
    exposure = ask_pick("exposure:", ["internal (LAN, shows on the homepage)",
                                      "external (public via Cloudflare)",
                                      "none (cluster-internal only)"], 1)
    exposure = {"internal (LAN, shows on the homepage)": "internal",
                "external (public via Cloudflare)": "external",
                "none (cluster-internal only)": "none"}[exposure]
    if exposure == "external":
        print("  ! this is publicly reachable at https://"
              f"{app}.jesseisageek.com with NO auth in front — only for intentionally public apps")
        if not ask_yn("  really make it external?"):
            exposure = "internal"

    # ---- env / secrets
    env_plain, secrets, values = {}, {}, {}
    if env:
        print("\nenv vars — y = secret (sops-encrypted Secret), n = plain (inline):")
        for k, v in sorted(env.items()):
            if ask_yn(f"  {k} = {v}  secret?", SECRETISH_RE.search(k) is not None):
                secrets[k] = var_name(app, k)
                values[k] = ask(f"    value for {k}:", secret=True)
            else:
                env_plain[k] = v
    elif ask_yn("\nadd any secrets for this app anyway?"):
        while True:
            k = ask("env var name (empty to finish)", allow_empty=True)
            if not k:
                break
            secrets[k] = var_name(app, k)
            values[k] = ask(f"  value for {k}:", secret=True)

    # ---- persistence
    persistence = {}
    if vols[0]:
        print("\nnamed volumes → Longhorn PVCs:")
        for vol, mount in vols[0]:
            size = ask(f"  {vol} @ {mount} — size?", "10Gi")
            persistence[vol] = {"enabled": True, "mountPath": mount,
                                "storageClass": "longhorn", "size": size,
                                "retain": True, "accessMode": "ReadWriteOnce"}
    elif ask_yn("\nadd a Longhorn persistence mount?"):
        p = (ask("  mount path?", "/app/config") or "").strip()
        size = ask(f"  {p} — size?", "10Gi")
        persistence["data"] = {"enabled": True, "mountPath": p,
                               "storageClass": "longhorn", "size": size,
                               "retain": True, "accessMode": "ReadWriteOnce"}
    for b in vols[1]:
        print(f"  ! bind mount {b!r} skipped (host paths don't map to k8s; "
              f"use NFS/Longhorn manually later if needed)")

    # ---- write the files
    print(f"\ngenerating templates for {ns}/{app} …")
    app_dir = T_APP / ns / app / "app"
    app_dir.mkdir(parents=True)
    (T_APP / ns / app / "ks.yaml.j2").write_text(gen_ks(app, ns))
    (app_dir / "kustomization.yaml.j2").write_text(gen_kustomization(bool(secrets)))
    image_repo, image_tag = normalize_image(image)
    (app_dir / "helmrelease.yaml.j2").write_text(
        gen_helmrelease(app, ns, image_repo, image_tag, port, proto,
                        exposure, env_plain, secrets, persistence or None))
    if secrets:
        (app_dir / "secret.sops.yaml.j2").write_text(gen_secret(app, ns, secrets))
    register_in_ns_kustomization(ns, app)
    add_config_vars(app, secrets, values) if secrets else None

    print("\ncreated/changed:")
    for p in sorted((T_APP / ns / app).rglob("*.j2")):
        print(f"  {p.relative_to(REPO_ROOT)}")
    if secrets:
        print(f"  {CONFIG_YAML.relative_to(REPO_ROOT)}  (config vars)")

    if args.no_deploy:
        print(f"\n--no-deploy: stopping here. To finish:  task configure && "
              f"./deploy.sh \"add {app}\"")
        return

    # ---- deploy
    if not shutil.which("task"):
        die("`task` not on PATH — activate the repo env (direnv allow), "
            "or run `task configure && ./deploy.sh \"add " + app + "\"` yourself")
    print("\n→ task configure …")
    if run(["task", "configure"]).returncode != 0:
        die("task configure failed (see above) — fix it, then re-run git2app or finish by hand")

    if shutil.which("kubeconform") and shutil.which("kustomize"):
        print("\n→ kubeconform …")
        if run(["bash", "scripts/kubeconform.sh", "kubernetes"]).returncode != 0:
            print("  kubeconform reported problems (see above) — review before committing")
    else:
        print("\n→ kubeconform/kustomize not installed — schema validation skipped")

    print("\nresulting repo changes:")
    print(run(["git", "status", "--short"], capture_output=True, text=True).stdout
          or "  (none — something went wrong)")
    print(run(["git", "diff", "--stat"], capture_output=True, text=True).stdout)
    print("note: ./deploy.sh commits ALL changes in the repo, not just this app\n")
    if not ask_yn("commit + push now?"):
        print(f"not committing. To finish later:  ./deploy.sh \"add {app}\"")
        return
    if run(["bash", str(DEPLOY_SH), f"add {app} app"]).returncode != 0:
        die("deploy.sh failed — check the error above")
    print(f"\n✅ {ns}/{app} is on its way — Flux picks up the push (webhook, or 30m interval). "
          f"Watch:  kubectl -n {ns} get pods")


if __name__ == "__main__":
    main()
