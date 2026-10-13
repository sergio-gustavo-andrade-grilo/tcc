#!/usr/bin/env bash
set -euo pipefail

CLUSTER="tcc"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GEN="$DIR/.generated"

# ===== Cleanup =====
docker compose -f "$DIR/docker-compose.yaml" down 2>/dev/null || true
kwokctl delete cluster --name "$CLUSTER" 2>/dev/null || true

# ===== Cluster creation =====
kwokctl create cluster --name "$CLUSTER" --runtime docker --wait 120s \
  --enable metrics-server -c "$DIR/config/metrics-usage.yaml"

kubectl config use-context "kwok-$CLUSTER"
kubectl get --raw=/readyz && echo

kubectl apply -f "$DIR/config/nodes.yaml"
kubectl get nodes

# ===== Generated files =====
mkdir -p "$GEN/targets"

kubectl config view --raw --minify --flatten --context "kwok-$CLUSTER" > "$GEN/kubeconfig"

KWOK_IP=$(docker inspect "kwok-${CLUSTER}-kwok-controller" --format "{{(index .NetworkSettings.Networks \"kwok-${CLUSTER}\").IPAddress}}")
cat > "$GEN/targets/kwok.json" <<EOF
[{"targets": ["${KWOK_IP}:10247"],
  "labels": {"__metrics_path__": "/metrics/nodes/kwok-node-1/metrics/resource", "node": "kwok-node-1"}}]
EOF

# ===== Monitoring stack =====
docker compose -f "$DIR/docker-compose.yaml" up -d