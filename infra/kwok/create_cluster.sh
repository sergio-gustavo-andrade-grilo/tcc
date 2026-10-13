#!/usr/bin/env bash
set -euo pipefail

CLUSTER="tcc"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ===== Cleanup =====
kwokctl delete cluster --name "$CLUSTER" 2>/dev/null || true
kwokctl create cluster --name "$CLUSTER" --runtime docker --wait 120s \
  --enable metrics-server -c "$DIR/metrics-usage.yaml"

docker compose -f "$DIR/docker-compose.yaml" down 2>/dev/null || true

# ===== Cluster creation =====
kubectl config use-context "kwok-$CLUSTER"
kubectl get --raw=/readyz && echo

kubectl apply -f "$DIR/nodes.yaml"
kubectl get nodes

kubectl config view --raw --minify --flatten --context "kwok-$CLUSTER" > "$DIR/.kubeconfig"     

mkdir -p "$DIR/targets"
KWOK_IP=$(docker inspect "kwok-${CLUSTER}-kwok-controller" --format "{{(index .NetworkSettings.Networks \"kwok-${CLUSTER}\").IPAddress}}")
cat > "$DIR/targets/kwok.json" <<EOF
[{"targets": ["${KWOK_IP}:10247"],
  "labels": {"__metrics_path__": "/metrics/nodes/kwok-node-1/metrics/resource", "node": "kwok-node-1"}}]
EOF

docker compose -f "$DIR/docker-compose.yaml" up -d