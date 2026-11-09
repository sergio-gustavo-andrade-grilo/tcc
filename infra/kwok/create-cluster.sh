#!/usr/bin/env bash
set -euo pipefail


usage() {
  cat <<EOF
Usage: create-cluster.sh <cluster-name>

Creates a KWOK cluster with the given name.
The kubectl context will be named kwok-<cluster-name>.

Options:
  -h, --help    show this message and exit
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  "")        usage >&2; exit 1 ;;
esac


name="$1"

kwokctl create cluster --name "$name" --runtime docker --wait 120s

echo "cluster '$name' created. kubectl context: kwok-$name"