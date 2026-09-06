# tools

## descheduler

Kubernetes descheduler (chart `descheduler` 0.29.0, kubernetes-sigs repo):
continuously rebalances pods — evicts on topology-spread violations,
inter-pod anti-affinity violations, node-affinity violations, and taint
mismatches. ServiceMonitor enabled. With 2 nodes it keeps spread constraints
honest; watch `kubectl -n kube-system get events` for eviction churn if an
app is flapping.

## reloader

Stakater Reloader (chart `reloader` 1.0.62, stakater repo): watches
ConfigMaps/Secrets in every namespace and **restarts pods whose Deployment
carries `reloader.stakater.com/auto: "true"`** when the referenced
config/secret changes. This is why most app-template controllers carry that
annotation — it's the mechanism that makes "edit the ConfigMap/Secret and the
app picks it up" work. Watch `reloader.stakater.com/reload` label annotations
in pod events when an app seems to restart on config push.
