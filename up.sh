#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
export KUBECONFIG="$PWD/.kubeconfig"
if ! kind get clusters | grep -qx novatec-lab; then
  kind create cluster --name novatec-lab --image kindest/node:v1.32.2 \
    --config kind.yaml --kubeconfig "$KUBECONFIG" --wait 180s
else
  docker start novatec-lab-control-plane >/dev/null
  kind export kubeconfig --name novatec-lab --kubeconfig "$KUBECONFIG"
  kubectl wait --for=condition=Ready node/novatec-lab-control-plane --timeout=180s
fi
docker build -q -t novatec-lab-app:v1 apps
docker build -q -t novatec-lab-grafana:v1 grafana
kind load docker-image novatec-lab-app:v1 novatec-lab-grafana:v1 --name novatec-lab
python3 build_dashboard.py
for namespace in demo observability; do
  kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl apply -f -
done
if ! kubectl -n observability get secret grafana-admin >/dev/null 2>&1; then
  python3 -c 'import secrets; print(secrets.token_hex(32), end="")' |
    kubectl -n observability create secret generic grafana-admin --from-file=password=/dev/stdin
fi
kubectl -n observability create configmap prometheus --from-file=config/prometheus.yaml --dry-run=client -o yaml | kubectl apply -f -
kubectl -n observability create configmap grafana-datasources --from-file=config/datasources.yaml --dry-run=client -o yaml | kubectl apply -f -
kubectl -n observability create configmap grafana-providers --from-file=config/dashboards.yaml --dry-run=client -o yaml | kubectl apply -f -
kubectl -n observability create configmap grafana-dashboards --from-file=generated/journeys.json --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f k8s/
kubectl -n demo rollout restart deployment/app-a deployment/app-b deployment/load-generator
kubectl -n observability rollout restart deployment/grafana deployment/prometheus
for deployment in redis app-b app-a load-generator; do
  kubectl -n demo rollout status "deployment/$deployment" --timeout=240s
done
kubectl -n observability rollout status deployment/prometheus --timeout=240s
kubectl -n observability rollout status deployment/grafana --timeout=240s
curl --fail --silent --show-error http://127.0.0.1:3000/api/health
echo
echo "Grafana: http://localhost:3000/d/novatec-journeys"
echo "Apps: http://localhost:8082/whatsapp e /notify"
