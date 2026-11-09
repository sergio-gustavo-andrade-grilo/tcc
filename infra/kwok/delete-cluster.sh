#!/usr/bin/env bash
set -euo pipefail


usage() {
  cat <<EOF
Usage: delete-cluster.sh <cluster-name>

Deletes a KWOK cluster with the given name.

Options:
  -h, --help    show this message and exit
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  "")        usage >&2; exit 1 ;;
esac


name="$1"

kwokctl delete cluster --name "$name"

echo "cluster '$name' deleted."