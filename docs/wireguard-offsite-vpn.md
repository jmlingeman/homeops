# Off-site WireGuard VPN (wg-easy) — how it works and what was fixed

Status: **working** (verified off-site from a phone on cellular, September 2026).

Clients connect from anywhere to the home k3s cluster's WireGuard server
(`wg-easy`, v15.4.0, Node-based image) and can reach the home LAN
(`192.168.1.0/24`) through the tunnel: pings, SSH, and internal domains
(`*.jesseisageek.com`, `plex.local`).

## Topology

```
phone (10.8.0.x)                    home
   |  UDP 30200
   v
vpn.jesseisageek.com  (DDNS A -> home WAN IP; DNS-only / unproxied, NOT Cloudflare-proxied)
   |  router port-forward 30200/UDP -> 192.168.1.20:30200   (+ 30201/TCP for the UI)
   v
k3s node (NodePort) -> BPF LB -> wg-easy pod netns (worker)
   |  kernel WireGuard on wg0 (10.8.0.0/24)
   |  phone -> LAN packets: FORWARD (policy ACCEPT) -> MASQUERADE (src -> pod k8s IP)
   v
node -> home router
   |  static routes (LAN side):
   |     10.42.0.0/24 -> 192.168.1.20
   |     10.42.1.0/24 -> 192.168.1.21
   v
LAN machines (plex, sonarr via nginx-internal .25, ...)
   |  replies to the pod's k8s IP
   v  (same static routes, back through the node into the pod netns)
   conntrack un-masquerades -> 10.8.0.x -> wg0 -> phone
```

DNS for internal names: client configs carry `DNS = 192.168.1.23`, which is
the **k8s-gateway split-DNS** service (Cilium LB IP). k8s-gateway is
authoritative for `jesseisageek.com` (internal apps answer with
`192.168.1.25`, the nginx-internal LB) and forwards every other name
upstream. Queries traverse the tunnel. Pi-hole (`192.168.1.10`) is *not*
the right server for `*.jesseisageek.com` names — k8s-gateway is.

## The root causes, in the order they were found

1. **Stale client config on the phone.** The installed config was missing
   `192.168.1.0/24` in `AllowedIPs` (and the `DNS = 192.168.1.23` line).
   WireGuard client routing is defined by the *client-side* config, not the
   server-side peer entry, so the phone sent all `192.168.1.x` traffic out
   its cellular default route (a private subnet — black hole) while the
   tunnel itself looked healthy. **Fix:** re-scan the current QR from the
   UI. Symptom signature: tunnel pings (`10.8.0.1`) fine, LAN pings dead,
   and *zero* packets from the client arriving at the server netns.

2. **Endpoint was a LAN address.** The app's global host was
   `192.168.1.20:30200`. A phone on cellular cannot reach that at all, so
   off-site the tunnel never even establishes (and with no persistent
   keepalive, cellular NAT reaps idle tunnels within minutes).
   **Fix:** router port-forward `30200/UDP -> 192.168.1.20` (and
   `30201/TCP` for the UI), app global **Host = `vpn.jesseisageek.com`**,
   per-client **Persistent Keepalive = 25s**, re-scan. The DDNS record must
   be **DNS-only (grey cloud)** — Cloudflare-proxied would send UDP to
   Cloudflare's edge, and Cloudflare Tunnel doesn't carry UDP, so the
   existing `external.*` tunnel is useless for WireGuard.

3. **Router had no return routes to the k8s pod subnets.** With the
   masquerade, phone traffic leaves the pod with the pod's k8s IP
   (`10.42.x.y`). LAN machines reply to that address, which their default
   gateway (the consumer router) had no route for. **Fix:** two static
   routes on the router, **LAN side** (the router form is
   destination / subnet mask / gateway):
   `10.42.0.0 / 255.255.255.0 / 192.168.1.20` and
   `10.42.1.0 / 255.255.255.0 / 192.168.1.21`.
   **Do not** add a route for `10.8.0.0/24` — the nodes have no
   root-netns route for it, so replies sent there would loop.

4. **NodePort bug (earlier in the same saga).** The kernel WireGuard module
   installs the server-side peer `AllowedIPs` (`10.8.0.0/24` **and
   `192.168.1.0/24`**) as routes in the pod netns' main table. The
   `192.168.1.0/24 dev wg0` route then made *every* pod reply to a LAN
   address — including NodePort SYN-ACKs for `:30200`/`:30201` — go into
   the tunnel toward the phones, killing all LAN->pod traffic
   (`192.168.1.21:30201` 100% timeout; other pods unaffected).
   **Fix:** the wg-easy pod's `postStart` hook runs a 5s loop that deletes
   that one route (it reappears on every client-config change, so a loop,
   not a one-shot). The `10.8.0.0/24 dev wg0` route is left alone — it is
   required for the tunnel.

5. **MASQUARDE ownership changed in v15.** The older image configured the
   interface from `wg0.conf` with `PostUp` iptables hooks; the v15
   (Node-based) app configures WireGuard through the API and manages NAT
   itself — it installs a MASQUARDE rule (`10.8.0.0/24 -> eth0`) in the
   *legacy* iptables table at pod start, observed live. If that rule ever
   disappears, phone->LAN packets leave with the client's real `10.8.0.x`
   source and replies get dropped at the router (no `10.8.0.0/24` route,
   by design). **Fix:** the same `postStart` loop also maintains an
   nftables MASQUARDE rule (`ip nat masq_post`) as a safety net. Note the
   in-container `iptables` (nft backend) cannot add a `MASQUARDE` target
   ("Chain 'MASQUARADE' does not exist"), and the legacy backend can't
   load the target `.so` — so `nft` is the only usable tool for it
   (chain spec needs double quotes; `priority 100`, displayed as
   `srcnat`).

## Repo changes

`bootstrap/templates/addons/wg-easy/app/statefulset.yaml.j2` (rendered to
`kubernetes/apps/wg-easy/wg-easy/app/statefulset.yaml`): full-spec
strategic-merge patch of the HelmRelease-owned StatefulSet (Helm leaves no
`last-applied-configuration` baseline, so the patch must carry the complete
spec — selector, template, `podManagementPolicy`, etc. — or the empty-base
merge drops `spec.selector`). The only functional delta is the `postStart`
hook:

```sh
nohup sh -c 'while :; do
  ip route del 192.168.1.0/24 dev wg0 2>/dev/null
  nft add table ip nat 2>/dev/null
  nft list chain ip nat masq_post 2>/dev/null | grep -q masquerade || {
    nft delete chain ip nat masq_post 2>/dev/null
    nft add chain ip nat masq_post "{ type nat hook postrouting priority 100; policy accept; }" 2>/dev/null
    nft add rule ip nat masq_post ip saddr 10.8.0.0/24 oifname eth0 masquerade 2>/dev/null
  }
  sleep 5
done' >/dev/null 2>&1 &
```

App-level config (lives in the PVC `wg-easy`, not the repo): global
`host = vpn.jesseisageek.com`, port 30200; per-client `DNS =
192.168.1.23`, `AllowedIPs = 10.8.0.0/24, 192.168.1.0/24`, persistent
keepalive 25s.

## Verifying

From the worker host, enter the pod netns (PID via
`/proc/<pid>/cgroup` containing `pod<UID>` — note cgroup v2 renders the UID
with underscores):

```sh
nsenter -t <PID> -n ip route                      # no 192.168.1.0/24 dev wg0
nsenter -t <PID> -n nft list table ip nat         # masq_post rule present
nsenter -t <PID> -n iptables-legacy -t nat -L POSTROUTING -v -n   # app's rule + counters
nsenter -t <PID> -n ping -c 2 10.8.0.2            # tunnel to a client
```

From a client (cellular, VPN on):

```
ping -c 5 10.8.0.1         # tunnel itself
ping -c 5 192.168.1.21     # node reply path
ping -c 5 <plex IP>        # third-party LAN reply path (needs router routes)
ssh <user>@<plex IP>
nslookup sonarr.jesseisageek.com    # must answer 192.168.1.25
```

## Gotchas

- **Client config changes require re-scanning** — the server-side DB change
  does not update installed clients. The v15 app stores clients in
  `/etc/wireguard/wg-easy.db` (SQLite, on the `wg-easy` PVC).
- **DDNS must track router reboots**, or the endpoint goes stale and the
  tunnel can't form until it updates.
- `plex.local` (mDNS) only resolves through k8s-gateway's mDNS reflection;
  it can never resolve via normal upstream DNS or on a phone that isn't
  using `192.168.1.23` as its tunnel DNS.
- The nft `masq_post` chain and the app's legacy rule can coexist
  harmlessly: after either one masquerades a packet, its source no longer
  matches `10.8.0.0/24`, so the other can't double-masquerade.
- The loop's `nft list ... | grep -q` guard makes the nft recreation
  no-churn: the chain is only rebuilt when the rule is absent.
- Diagnostic pattern for "which leg is dead": cumulative `iptables`/`nft`
  counters in the pod netns (arrivals per client IP via a throwaway
  `mangle` PREROUTING counter table) read before/after the client pings —
  arrivals prove the forward leg; the MASQUARDE counter proves the pod
  forwarded; node-side veth/ens18 stats prove node egress.
