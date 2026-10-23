---
name: kubernetes
description: Set up and manage local Kubernetes clusters using KIND (Kubernetes IN Docker). Use when testing Kubernetes applications locally, validating manifests, or developing cloud-native workloads.
triggers:
  - kubernetes
  - k8s
  - kube
  - kubectl
  - kind
  - helm
category: DEVOPS
source: OpenHands/extensions
license: MIT
---

# Kubernetes Local Development & Cluster Management

## 1. Overview
KIND (Kubernetes IN Docker) enables local multi-node Kubernetes clusters within container sandboxes for deployment validation, controller testing, and Helm chart assertions.

## 2. Core Operational Runbook

### Cluster Provisioning
```bash
# Create local cluster with KIND
kind create cluster --name local-dev --wait 60s
kubectl cluster-info --context kind-local-dev
```

### Manifest Deployment & Validation
```bash
# Dry-run validation
kubectl apply -f manifest.yaml --dry-run=client

# Apply manifests
kubectl apply -f manifest.yaml

# Rollout status inspection
kubectl rollout status deployment/<deployment-name> -n default
```

### Debugging & Telemetry
```bash
# Inspect pod logs
kubectl logs -l app=<app-name> --tail=100

# Describe pod events
kubectl describe pod <pod-name>
```

## 3. Sandboxing Invariants
- Execution strictly bounded inside KIND / local cluster; no modification of host networking.
- Secrets must use Kubernetes Secret objects mounted as volumes, never plaintext environment variables.
