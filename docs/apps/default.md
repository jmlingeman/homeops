# default

## homepage

[GetHomepage](https://gethomepage.dev) — the main portal/dashboard
(image `ghcr.io/gethomepage/homepage:v0.8.4`, Kustomization named `homepage`).

- **Ingress**: `home.${SECRET_DOMAIN}` (internal).
- **Config**: all of it in the `homepage-config` ConfigMap, mounted per-file with
  subPaths at `/app/config/`:
  - `settings.yaml` — dark/slate theme
  - `services.yaml` — the Cloudflared service entry + its dashboard widget
  - `widgets.yaml` — k8s resources, duckduckgo search, greeting, datetime widgets
  - `kubernetes.yaml` — mode `cluster` (in-cluster k8s widgets)
  - `bookmarks.yaml`, `docker.yaml` — present but empty
- **Secret**: `homepage-secret` (sops) with 5 keys injected as `envFrom`:
  `HOMEPAGE_VAR_CLOUDFLARED_{ACCOUNTID,API_TOKEN,TUNNELID}` and
  `HOMEPAGE_VAR_GRAFANA_{USERNAME,PASSWORD}` (feed the Cloudflared/Grafana widgets).
- **Discovery**: other apps surface themselves via `gethomepage.com`/hajimari
  annotations on their ingresses (icon, group, description) — e.g. the *arr
  apps (`television-box`), kubernetes-dashboard, echo-server.
- **Reloader**: auto-restarts when the ConfigMap/Secret change.
