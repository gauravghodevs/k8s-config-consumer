#!/bin/bash
import subprocess
import time
import sys
import os
import json

def run_cmd(cmd):
    res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if res.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\nError: {res.stderr}")
    return res.stdout.strip()

def get_canary_pod():
    pods = run_cmd("kubectl get pods -l track=canary -o jsonpath='{.items[*].metadata.name}'").split()
    if not pods:
        raise RuntimeError("No canary pods found!")
    return pods[0]

def get_canary_metrics(pod_name):
    cmd = f"kubectl exec {pod_name} -- python3 -c \"import urllib.request; print(urllib.request.urlopen('http://localhost:8080/metrics', timeout=3).read().decode())\""
    raw = run_cmd(cmd)
    metrics = {}
    for line in raw.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        if len(parts) == 2:
            metrics[parts[0]] = int(parts[1])
    return metrics

def apply_configmap(cm_name, file_path):
    with open(file_path, "r") as f:
        content = f.read()
    
    cm_json = json.dumps({
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": cm_name},
        "data": {"rules.yaml": content}
    })
    cmd = f"cat <<'INNER_EOF' | kubectl apply -f -\n{cm_json}\nINNER_EOF"
    run_cmd(cmd)

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 controller/rollout_guard.py <path_to_rules.yaml>")
        sys.exit(1)

    candidate_file = sys.argv[1]
    if not os.path.exists(candidate_file):
        print(f"Error: Candidate file '{candidate_file}' not found.")
        sys.exit(1)

    print(f"[*] Step 1: Initiating progressive rollout for '{candidate_file}'...")
    canary_pod = get_canary_pod()
    print(f"[*] Target Canary Pod: {canary_pod}")

    initial_metrics = get_canary_metrics(canary_pod)
    initial_rejected = initial_metrics.get("rules_rejected_total", 0)
    initial_loaded = initial_metrics.get("rules_loaded_total", 0)
    print(f"[*] Baseline Metrics -> Loaded: {initial_loaded}, Rejected: {initial_rejected}")

    print("[*] Step 2: Applying candidate configuration ONLY to Canary...")
    apply_configmap("rules-config-canary", candidate_file)

    print("[*] Step 3: Monitoring Canary for 10 seconds (evaluating blast radius)...")
    time.sleep(10)

    updated_metrics = get_canary_metrics(canary_pod)
    new_rejected = updated_metrics.get("rules_rejected_total", 0)
    new_loaded = updated_metrics.get("rules_loaded_total", 0)
    print(f"[*] Post-Update Metrics -> Loaded: {new_loaded}, Rejected: {new_rejected}")

    # Decision Gate
    if new_rejected > initial_rejected:
        print("\n[!!! ALERT - BLAST RADIUS CONTAINED !!!]")
        print(f"Canary rejected the configuration! Rejection count incremented by {new_rejected - initial_rejected}.")
        print("ABORTING ROLLOUT: Stable fleet remains 100% untouched.")
        sys.exit(2)
    elif new_loaded > initial_loaded:
        print("\n[SUCCESS] Canary accepted and loaded candidate configuration cleanly.")
        print("[*] Step 4: Promoting to Stable Fleet (rules-config-stable)...")
        apply_configmap("rules-config-stable", candidate_file)
        print("[DONE] Progressive rollout completed successfully across all nodes!")
    else:
        print("\n[WARN] No change detected in metrics. Check file updates.")

if __name__ == "__main__":
    main()
