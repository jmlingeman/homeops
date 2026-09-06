# storage

## longhorn

Distributed block storage + the cluster's default StorageClass (chart `longhorn`
1.5.3, repo `longhorn`):

- **StorageClass `longhorn`** — RWO, `default: true`, `defaultReplicaCount: 2`
  (replicas spread over both nodes). This is what every app's
  `persistence.….storageClass: longhorn` uses.
- **Backup target**: NFS `nfs://nfs.local:/mnt/pool1/backup` (192.168.1.30).
- **Recurring jobs** (`recurring-jobs/`, one per job):
  - `snapshot-daily` — 05:00 daily snapshots
  - `volume-trim-daily` — 06:00 daily `fstrim` on volumes
  - `backup-weekly` — Sat 07:00 backups to the NFS target
- **UI**: ingress `longhorn.${SECRET_DOMAIN}` (no explicit class → default
  `internal`), port 9001.

## openebs

openEBS local-hostpath provisioner (chart `openebs`, repo openebs) — the *other*
local-storage option. Used by a few apps that explicitly set
`storageClassName: openebs-hostpath` (postgres, grafana, kube-prometheus-stack)
— effectively per-node single-replica hostpath volumes at
`/var/openebs/local` (`bootstrap_local_storage_path`). Not the default class.
