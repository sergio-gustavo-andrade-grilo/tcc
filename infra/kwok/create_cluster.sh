#!/usr/bin/env bash
# Usage: create_cluster.sh [cluster-name ...]   (default: tcc-a tcc-b)
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GEN="$DIR/.generated"
KSM_BASE_PORT=8080

CLUSTERS=("$@")
if [ ${#CLUSTERS[@]} -eq 0 ]; then
  CLUSTERS=(tcc-a tcc-b)
fi

# ===== Cleanup =====
docker compose -f "$DIR/docker-compose.yaml" down --remove-orphans 2>/dev/null || true
for name in "${CLUSTERS[@]}"; do
  CLUSTER="$name" docker compose -p "ksm-$name" -f "$DIR/docker-compose.ksm.yaml" down 2>/dev/null || true
  kwokctl delete cluster --name "$name" 2>/dev/null || true
done
rm -rf "$GEN"
mkdir -p "$GEN/targets"

# ===== Clusters =====
index=0
for name in "${CLUSTERS[@]}"; do
  ctx="kwok-$name"
  ksm_port=$((KSM_BASE_PORT + 10 * index))

  echo ">> creating cluster $name"
  kwokctl create cluster --name "$name" --runtime docker --wait 120s \
    --enable metrics-server -c "$DIR/config/metrics-usage.yaml"

  kubectl --context "$ctx" get --raw=/readyz && echo
  kubectl --context "$ctx" apply -f "$DIR/config/nodes.yaml"

  mkdir -p "$GEN/$name"
  kubectl config view --raw --minify --flatten --context "$ctx" > "$GEN/$name/kubeconfig"

  # kube-state-metrics for this cluster
  CLUSTER="$name" KSM_PORT="$ksm_port" KSM_TELEMETRY_PORT=$((ksm_port + 1)) \
    docker compose -p "ksm-$name" -f "$DIR/docker-compose.ksm.yaml" up -d

  # Prometheus targets for this cluster
  echo "[{\"targets\": [\"localhost:${ksm_port}\"], \"labels\": {\"cluster\": \"$name\"}}]" \
    > "$GEN/targets/ksm-$name.json"

  kwok_ip=$(docker inspect "kwok-${name}-kwok-controller" \
    --format "{{(index .NetworkSettings.Networks \"kwok-${name}\").IPAddress}}")
  entries=()
  for node in $(kubectl --context "$ctx" get nodes -o jsonpath='{.items[*].metadata.name}'); do
    entries+=("{\"targets\": [\"${kwok_ip}:10247\"], \"labels\": {\"cluster\": \"$name\", \"node\": \"$node\", \"__metrics_path__\": \"/metrics/nodes/$node/metrics/resource\"}}")
  done
  echo "[$(IFS=,; echo "${entries[*]}")]" > "$GEN/targets/usage-$name.json"

  index=$((index + 1))
done

# ===== Monitoring =====
docker compose -f "$DIR/docker-compose.yaml" up -d