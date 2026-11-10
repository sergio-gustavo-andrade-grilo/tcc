#!/usr/bin/env bash
# Creates fake KWOK nodes in an existing cluster.
# Usage: create-nodes.sh <cluster-name> <count> [cpu] [memory]
set -euo pipefail

cluster="${1:?usage: create-nodes.sh <cluster-name> <count> [cpu] [memory]}"
count="${2:?usage: create-nodes.sh <cluster-name> <count> [cpu] [memory]}"
cpu="${3:-64}"
memory="${4:-256Gi}"

for i in $(seq 1 "$count"); do
  kubectl --context "kwok-$cluster" apply -f - <<EOF
apiVersion: v1
kind: Node
metadata:
  name: kwok-node-$i
  annotations:
    node.alpha.kubernetes.io/ttl: "0"
    kwok.x-k8s.io/node: fake
  labels:
    type: kwok
    kubernetes.io/hostname: kwok-node-$i
status:
  allocatable:
    cpu: "$cpu"
    memory: $memory
    pods: "110"
  capacity:
    cpu: "$cpu"
    memory: $memory
    pods: "110"
EOF
done

echo "created $count nodes in cluster '$cluster'"