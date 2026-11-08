#!/usr/bin/env bash
# Usage: destroy_cluster.sh [cluster-name ...]   (default: tcc-a tcc-b)
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CLUSTERS=("$@")
if [ ${#CLUSTERS[@]} -eq 0 ]; then
  CLUSTERS=(tcc-a tcc-b)
fi

docker compose -f "$DIR/docker-compose.yaml" down --remove-orphans 2>/dev/null || true
for name in "${CLUSTERS[@]}"; do
  CLUSTER="$name" docker compose -p "ksm-$name" -f "$DIR/docker-compose.ksm.yaml" down 2>/dev/null || true
  kwokctl delete cluster --name "$name" 2>/dev/null || true
done
rm -rf "$DIR/.generated"
echo "done"