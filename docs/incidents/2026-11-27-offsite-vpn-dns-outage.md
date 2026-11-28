# Incident 2026-11-24 → 2026-11-27: offsite WireGuard VPN — external/named sites hang

**Status:** RESOLVED 2026-11-27 (phone verified working off-site after the fix).
**Symptom:** with the offsite WireGuard VPN (wg-easy) on, named websites — external
*and* home (`gitea.jesseisageek.com`, `sonarr.jesseisageek.com`) — hang; direct-IP
LAN access keeps working. Started ~2 weeks before the 2026-11-27 session, i.e. right
after the 2026-11-24 Cilium rollback.

Companion doc: [`wireguard-offsite-vpn.md`](../wireguard-offsite-vpn.md) — topology,
client requirements, and all prior incidents. This file is the session-by-session
record of what was attempted, what it proved, and what actually fixed it.

## TL;DR — the actual solution

The **root cause** was Cilium's global BPF load-balancer mode: the 2026-11-24
rollback to Cilium 1.16.19 restored `loadBalancer.mode: dsr`, silently undoing the
2026-10-27 fix (commit `9711121f`) that set it to `snat`. In DSR mode the gateway
pod answers offsite-tunnel DNS with its own pod IP (`10.42.0.118:1053`) instead of
the `192.168.1.23` VIP; the wg-easy pod netns conntrack rejects the mismatched
reply (ICMP port-unreachable), so the phone never gets a DNS answer. Fix:
`loadBalancer.mode: snat` again (bootstrap var `bootstrap_cilium_loadbalancer_mode`
+ generated tree), agents re-rolled, phone verified.

On top of that, two *real but secondary* host-NAT defects found and durably fixed
along the way (kept as defense-in-depth): the node's `CILIUM_POST_nat` chain
re-masquerading pod-sourced tunnel traffic (now excluded by `ip daddr != {VIPs}`,
self-healed by the `cilium-nat-skip-guard` DaemonSet), and an earlier `accept`-rule
ordering bug (mark-based skip — which itself proved unreliable because Cilium BPF
rewrites `skb->mark` before the host's nft tables see it).

## Timeline of what was attempted

### Phase 0 — prior history (context)
- **2026-09-10/14:** Cilium upgraded to 1.16.19; LBIPAM pinning of the LAN VIPs
  (`.23`–`.26`) added.
- **2026-10-08:** pod-egress kernel-routing + masquerade fixes for phone DNS
  (`2d1c17cf`, `4616b1ad`).
- **2026-10-27:** **`9711121f` — `bpf-lb-mode` dsr → snat**: off-network clients
  source as a pod IP via the wg-easy netns; DSR direct-returns were not delivered
  back into the netns. Offsite worked after this.
- **2026-11-24:** 1.17.18 experiment (per-service modes, `dsrDispatch`, global
  snat/dsr flip-flops — "1.17.x unusable for this stack") ended in rollback to
  1.16.19 (`28ccee30`), which **restored `mode: dsr`** in the generated tree and
  bootstrap sample. Outage begins.
- **2026-11-25/26:** first round of "fixes" chasing the symptom at the nft layer:
  exclude LBIPAM VIPs from `bpfMasqueradeRange` (`dd2d8cea`), honor the plural
  `lbipam.cilium.io/ips` pin + reserve pool edge IPs (`f88e9e60`), mark-return
  ordering in `CILIUM_POST_nat` (`af1e4f08`). These addressed a real host-NAT
  re-masquerade (pcap-proven: phone queries left the egress node as
  `src 192.168.1.20 dst .23:53`, zero replies) but **did not end the outage**,
  because DSR mode still broke the reply path.

### Phase 1 — 2026-11-26/27 session: proving the host-NAT layer
1. Live wire capture on the worker (`ens18`) + the wg-easy pod netns: every phone
   query crossed the wire, but responses never returned to the pod IP.
2. Suspect #1: Cilium BPF LB `bpfMasqueradeRange` list that had been re-added to
   the node masquerade path. Reverted to `bpf.masquerade: false` +
   `hostLegacyRouting: true` (all node masquerade in nftables
   `CILIUM_POST_nat`).
3. Suspect #2: `CILIUM_POST_nat` `saddr <podCIDR> masquerade` re-SNATing
   pod-sourced traffic to the node IP. **Fix:** exclude the VIPs by destination —
   `oifname != "cilium_*" ip saddr <podCIDR> ip daddr != 10.42.0.0/16
   ip daddr != {192.168.1.23,.24,.25,.26} masquerade` — applied live on both
   nodes. Wire then showed the correct pod source (`10.42.0.94 → .23:53`).
4. The earlier **fwmark approach failed** (important lesson): stamping
   `skb->mark = 0x00000a00` in the pod netns + a `return` rule in
   `CILIUM_POST_nat` silently no-ops — Cilium's BPF rewrites the mark between the
   veth handoff and the host's nft tables (probe counters proved zero hits).
   Avoid mark-based skips on this stack; use stateless rule matching.
5. Local pod-netns DNS tests were **misleading**: when the gateway pod and the
   wg-easy pod share a node, local lookups shortcut through the local BPF LB and
   never exercise the real cross-node phone path. Verify from the wire.
6. Persistence: `cilium-nat-skip-guard` DaemonSet (kube-system) rebuilds
   `CILIUM_POST_nat` with the VIP exclusion within ~5s whenever ip-masq-agent
   recreates the chain without it (agent restarts / config changes).
   Commit `4eee98a8` + DaemonSet `7611c4dd`.
   → Outage **continued**: the remaining break was one layer deeper.

### Phase 2 — 2026-11-27 session: capturing the phone's real traffic
1. Two coordinated capture windows (worker `ens18` wire + wg-easy netns all-traffic
   + peer handshake polling). First windows: tunnel "up" but **zero phone
   traffic** — iOS had wedged the client socket (no keepalives for minutes);
   server data path verified healthy; advised VPN toggle off/on.
2. After the user re-toggled and loaded `bbc.com` / `somethingawful.com`, the
   third window captured the decisive exchange:
   - phone `10.8.0.7` → `192.168.1.23:53` queries enter the netns, are
     masqueraded to `10.42.0.94`, cross the wire to the worker, reach the
     gateway pod (correctly!);
   - the gateway pod's reply arrives at the netns as
     **`src 10.42.0.118:1053`** (the pod's own IP, not the `.23` VIP);
   - the netns conntrack emits **ICMP "udp port unreachable"** and drops it →
     the phone gets no DNS answer → page hangs.
3. That reply shape is the signature of **Cilium DSR mode**: backends return
   directly without the LB rewriting the source back to the VIP. Cross-referenced
   with git history: `9711121f` (2026-10-27) had set `mode: snat` for exactly
   this failure, and `28ccee30` (2026-11-24) had reverted to `mode: dsr`.

### Phase 3 — the fix and verification
1. Set `bootstrap_cilium_loadbalancer_mode: snat` in
   `bootstrap/vars/config.sample.yaml` **and** `loadBalancer.mode: snat` in the
   generated `kubernetes/apps/kube-system/cilium/app/helmvalues.yaml` (the live
   tree had drifted to `dsr` while the real `bootstrap/vars/config.yaml` already
   said `snat` — the generated tree is what Flux applies).
2. **Flux quirk encountered:** the HelmRelease did not auto-upgrade on the
   values-ConfigMap change (last upgrade was still the 11-24 release). Resolved
   with `kubectl -n kube-system annotate hr cilium
   reconcile.fluxcd.io/requestedAt=<now>`; upgrade to `cilium.v14` succeeded and
   the rendered `cilium-config` now carries `bpf-lb-mode: snat`.
3. Both agents rolled; end-to-end test through the tunnel path:
   `nslookup example.com 192.168.1.23` and `gitea.jesseisageek.com` from the
   wg-easy netns both resolve.
4. **Phone (off-site, cellular) confirmed: external sites load.**

## Final solution (what to remember)

| Layer | State | Durable? |
|---|---|---|
| Cilium `loadBalancer.mode: snat` (1.16.19) | **THE fix for the 2-week outage** | GitOps: `helmvalues.yaml` + bootstrap var; rendered into `cilium-config`; agents roll on change |
| Node `CILIUM_POST_nat` masquerade excludes the VIPs by `ip daddr !=` | host-NAT re-masquerade protection | `cilium-nat-skip-guard` DaemonSet re-applies within ~5s after any ip-masq-agent chain rebuild |
| `bpf.masquerade: false` + `hostLegacyRouting: true` | BPF NAT disabled on this stack (1.16.19 BPF NAT corrupts UDP checksums here) | GitOps helmvalues |
| wg-easy pod netns routes + `masq_post` (`saddr 10.8.0.0/24 oifname eth0 masquerade`) | tunnel forwarding/masquerade | in-repo StatefulSet `postStart` loop self-heals |

## Known gotchas / lessons
- **Never trust local pod-netns probes** for offsite-path verification — use wire
  captures (worker `ens18` + netns `eth0`) or the phone itself.
- **Mark-based NAT skips don't survive Cilium BPF** on this stack; match stateless
  fields instead.
- **Reverting Cilium versions** must also restore the *mode* settings that were
  changed alongside the version (the 1.16↔1.17 flips muddled dsr/snat choices).
  Keep the mode pinned in the bootstrap var with a comment (now done).
- A **HelmRelease may not auto-upgrade** when only its `valuesFrom` ConfigMap
  changes after a long quiescence; force it with
  `reconcile.fluxcd.io/requestedAt` if the rendered config lags the tree.
- iOS can **wedge its WireGuard socket** (connected badge, zero traffic, no
  keepalives): toggle the VPN off/on. With keepalive=25, peer "latest handshake"
  on the server is the cheapest liveness check for the client.
- Stale DNS failures can sit in browser/iOS caches for a long time; test with a
  never-visited URL and a fresh private tab.

## Commits
- `9711121f` (10-27) original dsr→snat fix (undone by the rollback)
- `dd2d8cea`, `f88e9e60`, `af1e4f08` (11-24/25) nft-layer fixes + mark approach
- `7611c4dd` `cilium-nat-skip-guard` DaemonSet (v1, mark-return based)
- `4eee98a8` daddr-exclusion masquerade rule + guard health-check update + docs
- `25d5ffa1` **`loadBalancer.mode: snat` restored — the root-cause fix** + incident docs
