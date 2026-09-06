# 07 — Storage

Three storage layers, chosen per app:

| Layer | Provisioner | Replication | Used for |
|-------|-------------|-------------|----------|
| **Longhorn** (`storage/longhorn`) | default StorageClass `longhorn` | 2 replicas (one per node) | app config/state PVCs — the default choice |
| **openEBS local-hostpath** (`storage/openebs`) | StorageClass `openebs-hostpath` | none (single node, `/var/openebs/local`) | a few big data stores (postgres, prometheus, grafana) |
| **NFS** (192.168.1.30 / `nfs.local`) | not a provisioner — apps mount shares via `volumeSpec.nfs` | whatever the NAS does | media pools (TV, movies, music, downloads, backups) |

## Longhorn

Chart `longhorn` in `storage/longhorn` (Kustomization `longhorn`, plus one
Kustomization per recurring job):

- StorageClass `longhorn`: RWO/RWX, **`default: true`**, `defaultReplicaCount: 2`
  (replicas spread across both nodes — a node loss doesn't lose data).
- **Recurring jobs**:
  | Job | Schedule | What |
  |-----|----------|------|
  | `snapshot-daily` | 05:00 daily | snapshots of Longhorn volumes |
  | `volume-trim-daily` | 06:00 daily | `fstrim` on volumes |
  | `backup-weekly` | Sat 07:00 | backups to `nfs://nfs.local:/mnt/pool1/backup` |
- **UI**: `longhorn.${SECRET_DOMAIN}` (internal ingress, port 9001) —
  volumes, replicas, snapshots, backups, restore.

Apps using Longhorn (all `persistence…storageClass: longhorn`, `retain: true` —
**PVCs survive app deletion**):

| App (ns) | Volume | Size | Mount |
|----------|--------|------|-------|
| sonarr (media) | `config` | 16Gi | `/config` |
| overseerr (media) | `config` | 16Gi | `/config` |
| lidarr (media) | `config` | 8Gi | `/config` |
| youtarr (media) | `config` | 2Gi | `/config` |
| radarr (media) | `config` | 1Gi | `/config` |
| sabnzbd (media) | `config` | 1Gi | `/config` |
| ultrasonics (media) ⚠️ not deployed | `config` | 8Gi | `/config` |
| actual (home) | `data` | 4Gi | `/data` |
| joplin (home) | `data` | 4Gi | `/app/data` |
| mealie (home) | `data` | 4Gi | `/app/data` |
| firefly-iii (home) | `fireflyiii-config-v1` (pre-created PVC, referenced as `existingClaim`) | 1Gi | `/var/www/html/firefly-iii/storage/upload` |
| grocy (home) | `config` | 1Gi | `/config` |
| gitea (home) | chart-default (bundled Postgres data) | chart default | — (default SC ⇒ Longhorn) |
| homarr (home) | chart-default (bundled Postgres data) | chart default | — (default SC ⇒ Longhorn) |
| vaultwarden (security) ⚠️ not deployed | `data` | 3Gi | `/data` |

## openEBS local-hostpath

`storage/openebs` (openebs `localpv` chart): single-node hostpath volumes under
`/var/openebs/local` (from `bootstrap_local_storage_path`). No replication — a
disk failure loses it. Used where the data is rebuildable or the default SC is
undesirable:

| App (ns) | Volume | Size | Notes |
|----------|--------|------|-------|
| postgresql (database) | `postgres` (pre-created PVC, `existingClaim`) | 10Gi | the shared cluster database |
| kube-prometheus-stack (observability) | Prometheus `volumeClaimTemplate` | 10Gi (retentionSize 8Gi) | |
| grafana (observability) | `grafana` persistence | unset (SC default) | |

## NFS (192.168.1.30, `nfs.local`)

The NAS holds the media pools. Pools (from `bootstrap/vars/config.yaml`
`media_nfs_*_path`; the same values are in `cluster-secrets` as `NFS_TV`,
`NFS_TV2`, `NFS_MOVIES`, `NFS_MUSIC`, `NFS_BACKUP` — though the app manifests
**mostly hardcode** `192.168.1.30` + the raw path rather than the `${NFS_*}`
substitution vars):

| Share | Path | Mounted by (all `persistence.<name>.type: custom` → `volumeSpec.nfs`) |
|-------|------|----------------------------------------------------------------------|
| downloads | `/mnt/pool1/downloads` | sonarr, radarr, lidarr, sabnzbd, youtarr (⚠ ultrasonics if enabled) |
| tv (pool1) | `/mnt/pool1/tv` | sonarr (`/tv`) |
| tv (pool2) | `/mnt/pool2/tv` | sonarr (`/tv2`) |
| movies | `/mnt/pool2/movies` | radarr (mounted as `/movies` — the volume is misnamed `tv`) |
| music | `/mnt/pool2/music` | lidarr (`/music`); ⚠ ultrasonics |
| temp | `/mnt/pool2/temp` | youtarr (mounted as `/tv2` — name/path mismatch quirk) |
| backup | `/mnt/pool1/backup` | Longhorn backup target (not an app mount) |
| audiobooks | `/mnt/pool2/audiobooks` | (declared; no current app mounts it) |
| vaultwarden | `/mnt/pool1/vaultwarden` | (declared; vaultwarden app isn't deployed) |

NFS mount details used by the media apps: `nfsvers: 4` (ultrasonics 4.1),
read-write, mount at the app's data dir; the *arr apps get their config on
Longhorn but **all media data on NFS** — so the media library lives on the NAS,
not on cluster disks.

## Choosing a storage layer (for new apps)

- **Small config/state** (MBs–GBs, must survive): Longhorn PVC (`storageClass: longhorn`,
  `retain: true`). The default — use it unless there's a reason not to.
- **Large scratch/rebuildable data** (Prometheus TSDB, logs): openebs-hostpath
  (cheaper on the network, but single-node — fine for rebuildable data).
- **Shared media/content** (things multiple apps or outside tools read): NFS on
  192.168.1.30 — add the share to `media_nfs_*_path` in `bootstrap/vars/config.yaml`
  if it's new, and use a `custom` volumeSpec (see sonarr).
- **Pre-created PVC** (`existingClaim` pattern, e.g. postgres, firefly): use when
  the PVC must exist before the HelmRelease installs (some charts can't create
  it themselves) — add a `pvc.yaml` to the app dir like `database/postgresql` does.

## Debugging

```sh
kubectl -n <ns> get pvc                          # Bound? which SC?
kubectl -n longhorn-system get longvolumes      # replicas, status
kubectl -n longhorn-system get longvolumereplicas
# Longhorn UI: http://longhorn.jesseisageek.com (or port-forward 9001)
mount | grep nfs                                  # on the k3s node(s)
df -h /mnt/pool1 /mnt/pool2                        # on 192.168.1.30
```
