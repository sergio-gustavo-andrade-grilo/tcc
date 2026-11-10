#!/usr/bin/env bash
# Writes the kubeconfig and Prometheus targets for a KWOK cluster.
# Run it after creating the cluster and its nodes, and again if the cluster
# is recreated (the controller IP changes) or nodes are added.
# Usage: write-targets.sh <cluster-name>
set -euo pipefail

cluster="${1:?usage: write-targets.sh <cluster-name>}"
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.generated"
ctx="kwok-$cluster"

mkdir -p "$dir/$cluster" "$dir/targets"

# Kubeconfig for kube-state-metrics (self-contained, only this cluster)
kubectl config view --raw --minify --flatten --context "$ctx" > "$dir/$cluster/kubeconfig"

# kube-state-metrics target (host network, port 8081 by default)
ksm_port="${KSM_PORT:-8081}"

echo "[{\"targets\": [\"localhost:${ksm_port}\"], \"labels\": {\"cluster\": \"$cluster\"}}]" \
  > "$dir/targets/ksm-$cluster.json"

# One usage target per node, pointing at the KWOK controller
ip=$(docker inspect "kwok-${cluster}-kwok-controller" \
  --format "{{(index .NetworkSettings.Networks \"kwok-${cluster}\").IPAddress}}")

entries=()
for node in $(kubectl --context "$ctx" get nodes -o jsonpath='{.items[*].metadata.name}'); do
  entries+=("{\"targets\": [\"${ip}:10247\"], \"labels\": {\"cluster\": \"$cluster\", \"node\": \"$node\", \"__metrics_path__\": \"/metrics/nodes/$node/metrics/resource\"}}")
done
echo "[$(IFS=,; echo "${entries[*]}")]" > "$dir/targets/usage-$cluster.json"

echo "wrote targets for '$cluster' (controller $ip, ${#entries[@]} nodes)"