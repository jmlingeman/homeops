# Cluster health report — 2026-11-15

_Generated 2026-11-15T15:08:11 · read-only check · sources: kubernetes, local, nas, ninfer_

## Summary

- **4 critical**, **8 warnings**, 25 total findings

- 🔴 [CRIT] **Pod kube-system/coredns-54b4c7dc4-2hmfb is Failed**`k8s-pod:kube-system/coredns-54b4c7dc4-2hmfb:failed`
- 🔴 [CRIT] **Pod kube-system/coredns-54b4c7dc4-ffwgr is Failed**`k8s-pod:kube-system/coredns-54b4c7dc4-ffwgr:failed`
- 🔴 [CRIT] **Pod kube-system/npcli-m is Failed**`k8s-pod:kube-system/npcli-m:failed`
- 🔴 [CRIT] **NAS active alert: ZpoolCapacity / ZpoolCapacityCritical**`nas-alert:zpoolcapacitycritical`
- 🟠 [WARN] **/ at 80.0% full (/dev/sda2)**`disk:llm-server:/dev/sda2`
- 🟠 [WARN] **Kustomization flux-system/cluster-apps-longhorn-recurring-jobs is not ready**`flux-kustomization:flux-system/cluster-apps-longhorn-recurring-jobs`
- 🟠 [WARN] **GPU 0 NVIDIA GeForce RTX 3090 at 89.53°C (warm)**`gpu:llm-server:0:hot`
- 🟠 [WARN] **NAS active alert: SMBPath / SMBPath**`nas-alert:smbpath`
- 🟠 [WARN] **NAS active alert: VolumeStatus / VolumeStatus**`nas-alert:volumestatus`
- 🟠 [WARN] **NAS pool pool1 is DEGRADED**`nas-pool:pool1:degraded`
- 🟠 [WARN] **ninfer model repo has 37 new upstream commit(s)**`ninfer:updates-available`
- 🟠 [WARN] **Cannot read SMART on /dev/sda1 (permission denied)**`smart:llm-server:noaccess`
- ℹ️ [INFO] **Pod cert-manager/cert-manager-cainjector-7677cbf98f-gpnqp has 286 cumulative restarts**`k8s-pod-restarts:cert-manager/cert-manager-cainjector-7677cbf98f-gpnqp`
- ℹ️ [INFO] **Pod frontend/librarian-6c5d44f65d-km4mr has 273 cumulative restarts**`k8s-pod-restarts:frontend/librarian-6c5d44f65d-km4mr`
- ℹ️ [INFO] **Pod home/joplin-5cf65888ff-ljp9d has 241 cumulative restarts**`k8s-pod-restarts:home/joplin-5cf65888ff-ljp9d`
- ℹ️ [INFO] **Pod kube-system/hostcrictl-kube-controller has 66 cumulative restarts**`k8s-pod-restarts:kube-system/hostcrictl-kube-controller`
- ℹ️ [INFO] **Pod kube-system/hostcrictl-kube-worker has 67 cumulative restarts**`k8s-pod-restarts:kube-system/hostcrictl-kube-worker`
- ℹ️ [INFO] **Pod kube-system/hubble-relay-6dbfb5c76b-f42df has 336 cumulative restarts**`k8s-pod-restarts:kube-system/hubble-relay-6dbfb5c76b-f42df`
- ℹ️ [INFO] **Pod kube-system/kube-vip-kube-controller has 88 cumulative restarts**`k8s-pod-restarts:kube-system/kube-vip-kube-controller`
- ℹ️ [INFO] **Pod media/youtarr-b68c6cf79-q2nks has 402 cumulative restarts**`k8s-pod-restarts:media/youtarr-b68c6cf79-q2nks`
- ℹ️ [INFO] **Pod network/cloudflared-58b85b5d68-8dv8w has 260 cumulative restarts**`k8s-pod-restarts:network/cloudflared-58b85b5d68-8dv8w`
- ℹ️ [INFO] **Pod network/cloudflared-58b85b5d68-rvg79 has 648 cumulative restarts**`k8s-pod-restarts:network/cloudflared-58b85b5d68-rvg79`
- ℹ️ [INFO] **Pod observability/kube-prometheus-stack-prometheus-node-exporter-bztdn has 19 cumulative restarts**`k8s-pod-restarts:observability/kube-prometheus-stack-prometheus-node-exporter-bztdn`
- ℹ️ [INFO] **Pod storage/openebs-ndm-5vc9g has 28 cumulative restarts**`k8s-pod-restarts:storage/openebs-ndm-5vc9g`
- ℹ️ [INFO] **Pod tools/descheduler-5d46ffdb6-6pjxx has 262 cumulative restarts**`k8s-pod-restarts:tools/descheduler-5d46ffdb6-6pjxx`

## Kubernetes cluster

- Node **kube-worker**: ✅ Ready (kubelet v1.29.0+k3s1)
- Node **kube-controller**: ✅ Ready (kubelet v1.29.0+k3s1)

**Flux (HelmReleases):**
- network/cloudflared: ✅ 2.4.0
- storage/openebs: ✅ 3.10.0
- wg-easy/wg-easy: ✅ 1.2.0
- frontend/priviblur: ✅ 2.4.0
- observability/headlamp: ✅ 0.45.0
- tools/reloader: ✅ 1.0.62
- frontend/quetre: ✅ 2.4.0
- observability/kubernetes-dashboard: ✅ 7.14.0
- default/homepage: ✅ 2.4.0
- network/k8s-gateway: ✅ 2.1.0
- frontend/librarian: ✅ 2.4.0
- observability/kube-prometheus-stack: ✅ 55.8.1
- frontend/libremdb: ✅ 2.4.0
- media/youtarr: ✅ 2.4.0
- network/nginx-internal: ✅ 4.7.1
- frontend/libreddit: ✅ 2.4.0
- home/gitea: ✅ 12.7.0
- kube-system/coredns: ✅ 1.29.0
- media/piped: ✅ 8.1.23
- security/vaultwarden: ✅ 2.4.0
- frontend/libmedium: ✅ 2.4.0
- media/seerr: ✅ 2.4.0
- home/actual: ✅ 2.4.0
- media/prowlarr: ✅ 2.4.0
- cert-manager/cert-manager: ✅ v1.16.4
- home/firefly-iii-importer-cba: ✅ 2.4.0
- media/radarr: ✅ 2.4.0
- media/sabnzbd: ✅ 2.4.0
- network/nginx-external: ✅ 4.7.1
- frontend/rimgo: ✅ 2.4.0
- kube-system/cilium: ✅ 1.16.19
- home/mealie: ✅ 2.4.0
- frontend/breezewiki: ✅ 2.4.0
- home/joplin: ✅ 2.4.0
- network/external-dns: ✅ 1.14.1
- media/lidarr: ✅ 2.4.0
- home/meshchatx: ✅ 2.4.0
- home/firefly-iii: ✅ 2.4.0
- kube-system/metrics-server: ✅ 3.11.0
- home/homarr: ✅ 5.7.0
- network/echo-server: ✅ 2.4.0
- home/firefly-iii-importer: ✅ 2.4.0
- observability/grafana: ✅ 7.0.19
- tools/descheduler: ✅ 0.29.0
- home/grocy: ✅ 8.5.2
- storage/longhorn: ✅ 1.12.1
- database/postgresql: ✅ 13.2.29
- media/overseerr: ✅ 2.4.0
- media/sonarr: ✅ 2.4.0
- home/affine: ✅ 2.4.0

**Pod phases:** Failed: 3, Running: 118, Succeeded: 15

## Local box (llm-server)

- Host: **llm-server**
- /dev/sda2 `/`: **80.0%** used (796G total, 165G free)
- efivarfs `/sys/firmware/efi/efivars`: **32.0%** used (0G total, 0G free)
- none `/run/credentials/systemd-journald.service`: **0.0%** used (0G total, 0G free)
- none `/run/credentials/systemd-resolved.service`: **0.0%** used (0G total, 0G free)
- /dev/sda1 `/boot`: **18.0%** used (4G total, 3G free)

**GPU:**
- NVIDIA GeForce RTX 3090 (#0): 89.53°C, 234.47W, throttle=yes

## ninfer model repo

- path: `/home/jesse/llm/ninfer-3090`
- branch `master`: ahead=0 behind=37
  - a90ad3c2 docs(release): correct the partial-copy note to match the synchronous scripts
  - 7b11c2a0 docs: record the GPU results for the Basalt options in the Flash-Next plan
  - b4f5252f docs: release-process lessons from v0.18.0
  - 2dc8bd90 docs: fill in v0.18.0 verification
  - a10f7524 fix(serve): split the serve option chain so MSVC can compile it (C1061)
  - 42faedb8 docs: release notes for v0.18.0
  - 10ff94f8 chore: bump VERSION to 0.18.0-rtx3090
  - 85b051e7 fix(frontend): correct the drop test and the extent memo wording
  - 2502056b fix(frontend): probe media for the Vision plan under the preparation gate
  - 45cdd7d2 perf(frontend): probe each image once when planning the Vision budget
  - 8dfb7d70 fix(program): dispatch the batched MTP fold through fold_stream_ when the whole round continues
  - 85aa40bb fix(frontend): measure the omission note with the tokenizer
  - b6c91055 fix(frontend): address review of the Vision budget plan
  - ad46a2e3 fix(program): size the expert route log for batched rows, fix test batchability gate
  - eb4e20a4 fix(program): download batched routes, clear deferred_, count released rows, size shared-expert scratch

## NAS (nas)

- TrueNAS-SCALE-23.10.1 on **nas** (up 106 days, 6:07:49.735033, load [3.45068359375, 3.6181640625, 3.15380859375])

**Pools:**
- pool1: **DEGRADED** — 95.9% of 67040G (64292G allocated, 2748G free) — `One or more devices has experienced an error resulting in data corruption. Applications may be affected.`
- pool2: **ONLINE** — 44.2% of 55872G (24693G allocated, 31179G free)

**Datasets (24):** pool1, pool1/backup, pool1/backup, pool1/downloads, pool1/downloads, pool1/ix-applications, pool1/ix-applications, pool1/tv, pool1/tv, pool1/users, pool1/users, pool1/vaultwarden, pool1/vaultwarden, pool2, pool2/audiobooks, pool2/audiobooks … (+8 more)

**Active alerts:**
- ZpoolCapacity / ZpoolCapacityCritical — {'volume': 'pool1', 'capacity': 95}
- VolumeStatus / VolumeStatus — {'volume': 'pool1', 'state': 'DEGRADED', 'status': 'One or more devices has experienced an error resulting in data corruption. Applications may be affected.', 'devices': '<br>The following devices are not healthy:<ul><li>Disk QEMU_HARDDISK drive-scsi10 is FAULTED</li></ul>'}
- SMBPath / SMBPath — {'err': 'pool1: SMB shares containing the apps dataset are not permitted'}
-  / ScrubFinished
-  / ScrubFinished
-  / ScrubFinished
-  / ScrubStarted

## Deployed chart versions

> Image & chart upgrades are tracked by Renovate (GitHub PRs). This is a snapshot of what is currently deployed.

| namespace | app | chart | version |
|---|---|---|---|
| network | cloudflared | app-template | 2.4.0 |
| storage | openebs | openebs | 3.10.0 |
| wg-easy | wg-easy | wg-easy | 1.2.0 |
| frontend | priviblur | app-template | 2.4.0 |
| observability | headlamp | headlamp | 0.45.0 |
| tools | reloader | reloader | 1.0.62 |
| frontend | quetre | app-template | 2.4.0 |
| observability | kubernetes-dashboard | charts/kubernetes-dashboard | 7.14.0 |
| default | homepage | app-template | 2.4.0 |
| network | k8s-gateway | k8s-gateway | 2.1.0 |
| frontend | librarian | app-template | 2.4.0 |
| observability | kube-prometheus-stack | kube-prometheus-stack | 55.8.1 |
| frontend | libremdb | app-template | 2.4.0 |
| media | youtarr | app-template | 2.4.0 |
| network | nginx-internal | ingress-nginx | 4.7.1 |
| frontend | libreddit | app-template | 2.4.0 |
| home | gitea | gitea | 12.7.0 |
| kube-system | coredns | coredns | 1.29.0 |
| media | piped | piped | 8.1.23 |
| security | vaultwarden | app-template | 2.4.0 |
| frontend | libmedium | app-template | 2.4.0 |
| media | seerr | app-template | 2.4.0 |
| home | actual | app-template | 2.4.0 |
| media | prowlarr | app-template | 2.4.0 |
| cert-manager | cert-manager | cert-manager | v1.16.4 |
| home | firefly-iii-importer-cba | app-template | 2.4.0 |
| media | radarr | app-template | 2.4.0 |
| media | sabnzbd | app-template | 2.4.0 |
| network | nginx-external | ingress-nginx | 4.7.1 |
| frontend | rimgo | app-template | 2.4.0 |
| kube-system | cilium | cilium | 1.16.19 |
| home | mealie | app-template | 2.4.0 |
| frontend | breezewiki | app-template | 2.4.0 |
| home | joplin | app-template | 2.4.0 |
| network | external-dns | external-dns | 1.14.1 |
| media | lidarr | app-template | 2.4.0 |
| home | meshchatx | app-template | 2.4.0 |
| home | firefly-iii | app-template | 2.4.0 |
| kube-system | metrics-server | metrics-server | 3.11.0 |
| home | homarr | homarr | 5.7.0 |
| network | echo-server | app-template | 2.4.0 |
| home | firefly-iii-importer | app-template | 2.4.0 |
| observability | grafana | grafana | 7.0.19 |
| tools | descheduler | descheduler | 0.29.0 |
| home | grocy | grocy | 8.5.2 |
| storage | longhorn | longhorn | 1.12.1 |
| database | postgresql | postgresql | 13.2.29 |
| media | overseerr | app-template | 2.4.0 |
| media | sonarr | app-template | 2.4.0 |
| home | affine | app-template | 2.4.0 |

---
_findings file: reports/2026-11-15_cluster-health.json — feed to `python3 bin/issue-sync.py` to reconcile Gitea issues_
