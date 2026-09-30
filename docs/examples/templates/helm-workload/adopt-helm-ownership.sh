#!/usr/bin/env bash
# Mark objects that were deployed with `helm template | kubectl apply` as owned by a Helm release, so the first
# managed (helm_release) apply adopts them in place instead of failing on ownership metadata.
#
# Dry run by default: prints the objects and the kubectl commands. Pass --apply to change the cluster.
#
#   adopt-helm-ownership.sh --release checkout --namespace checkout [--selector app.kubernetes.io/instance=checkout]
#                           [--kinds deployment,service,...] [--context my-cluster] [--apply]
set -euo pipefail

release=""
namespace=""
selector=""
context=""
apply=false
kinds="deployment,statefulset,daemonset,service,configmap,serviceaccount,ingress,horizontalpodautoscaler,poddisruptionbudget,cronjob,role,rolebinding,networkpolicy,secretproviderclass"

usage() {
  sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release) release="$2"; shift 2 ;;
    --namespace) namespace="$2"; shift 2 ;;
    --selector) selector="$2"; shift 2 ;;
    --kinds) kinds="$2"; shift 2 ;;
    --context) context="$2"; shift 2 ;;
    --apply) apply=true; shift ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown argument: $1" >&2; usage 1 ;;
  esac
done

[[ -n "$release" && -n "$namespace" ]] || { echo "--release and --namespace are required" >&2; usage 1; }
name_re='^[a-z0-9]([-a-z0-9]*[a-z0-9])?$'
[[ "$release" =~ $name_re && "$namespace" =~ $name_re ]] || { echo "release and namespace must be DNS labels" >&2; exit 1; }
selector="${selector:-app.kubernetes.io/instance=$release}"

kubectl_args=(--namespace "$namespace")
[[ -n "$context" ]] && kubectl_args+=(--context "$context")

objects=()
IFS=',' read -r -a kind_list <<< "$kinds"
for kind in "${kind_list[@]}"; do
  # Kinds whose CRD is not installed are skipped.
  while IFS= read -r object; do
    [[ -n "$object" ]] && objects+=("$object")
  done < <(kubectl get "$kind" "${kubectl_args[@]}" --selector "$selector" --output name 2>/dev/null || true)
done

if [[ ${#objects[@]} -eq 0 ]]; then
  echo "No objects match '$selector' in namespace $namespace; nothing to adopt."
  exit 0
fi

echo "Objects to mark as owned by Helm release '$release' in namespace '$namespace':"
printf '  %s\n' "${objects[@]}"

run() {
  if [[ "$apply" == true ]]; then
    kubectl "$@"
  else
    printf 'would run: kubectl'
    printf ' %q' "$@"
    printf '\n'
  fi
}

for object in "${objects[@]}"; do
  run label "$object" "${kubectl_args[@]}" --overwrite "app.kubernetes.io/managed-by=Helm"
  run annotate "$object" "${kubectl_args[@]}" --overwrite \
    "meta.helm.sh/release-name=$release" "meta.helm.sh/release-namespace=$namespace"
done

if [[ "$apply" != true ]]; then
  echo "Dry run only. Re-run with --apply to change the cluster."
fi
