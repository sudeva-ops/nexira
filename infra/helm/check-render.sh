#!/bin/sh
# Assertions on a rendered chart that schema validation cannot make (`make helm-check`).
# Usage: check-render.sh <rendered.yaml> <pilot|openshift>
set -eu
file="$1"
values="$2"
fail() { echo "check-render ($values): $1" >&2; exit 1; }

pods=$(grep -cE '^kind: (Deployment|StatefulSet|Job|CronJob)$' "$file" || true)
nonroot=$(grep -c 'runAsNonRoot: true' "$file" || true)
[ "$pods" -eq "$nonroot" ] || fail "$pods workloads but $nonroot set runAsNonRoot"

if [ "$values" = openshift ]; then
  # OpenShift assigns UIDs; and no default selector may survive a values override.
  ! grep -q 'runAsUser' "$file" || fail "runAsUser set on OpenShift"
  ! grep -qE 'kube-dns|ingress-nginx' "$file" || fail "Kubernetes default selectors leaked into OpenShift"
else
  uids=$(grep -c 'runAsUser: 10001' "$file" || true)
  [ "$pods" -eq "$uids" ] || fail "$pods workloads but $uids set a numeric runAsUser"
fi

# The pre-install migrate Job must not need the release's ServiceAccount, and it
# must get only the owner Secret.
migrate=$(awk 'BEGIN{RS="\n---\n"} /kind: Job\n/ && /component: migrate/' "$file")
[ -n "$migrate" ] || fail "no migrate Job rendered"
! echo "$migrate" | grep -q 'serviceAccountName' || fail "migrate Job names a ServiceAccount"
secrets=$(echo "$migrate" | grep -c 'secretRef' || true)
[ "$secrets" -eq 1 ] || fail "migrate Job mounts $secrets Secrets"
echo "check-render ($values): ok ($pods workloads)"
