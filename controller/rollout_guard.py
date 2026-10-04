#!/usr/bin/env python3

import subprocess
import sys
import os
import json
import time
import hashlib
import urllib.parse
from enum import Enum
from datetime import datetime, timezone

from controller.s3_store import S3ConfigStore
from controller.signing import load_public_key, verify_bytes


BAKE_INTERNAL = int(os.getenv("BAKE_INTERNAL", "30"))
BAKE_1_PERCENT = int(os.getenv("BAKE_1_PERCENT", "60"))
BAKE_10_PERCENT = int(os.getenv("BAKE_10_PERCENT", "60"))

PROMETHEUS_URL = os.getenv(
    "PROMETHEUS_URL",
    "http://127.0.0.1:9090"
)
# Test-only deterministic runtime failure injection.
INJECT_RUNTIME_FAILURE = (
    os.getenv("INJECT_RUNTIME_FAILURE", "false").lower() == "true"
)

MAX_CONFIG_SIZE = int(
    os.getenv("MAX_CONFIG_SIZE", "1048576")
)

REQUIRE_SIGNATURE = (
    os.getenv("REQUIRE_SIGNATURE", "false").lower() == "true"
)

PUBLIC_KEY_PATH = os.getenv(
    "PUBLIC_KEY_PATH",
    "security/public/ed25519-public.pem"
)

class State(Enum):
    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    PROMOTING = "PROMOTING"
    BAKING = "BAKING"
    HEALTHY = "HEALTHY"
    HALTED = "HALTED"
    ROLLING_BACK = "ROLLING_BACK"
    COMPLETED = "COMPLETED"


class PromotionController:

    def __init__(self, candidate_file):
        self.candidate_file = candidate_file
        self.config_version = None
        self.stage = "0%"
        self.status = State.PENDING
        self.started_at = datetime.now(timezone.utc).isoformat()

        self.state_file = "/tmp/blast-radius-guard-state.json"
        self.previous_configs = {}

        self.s3_store = None
        self.s3_version_id = None
        self.candidate_hash = None

        if os.getenv("USE_S3", "false").lower() == "true":
            self.s3_store = S3ConfigStore()

    # ---------------------------------------------------------
    # Utility
    # ---------------------------------------------------------

    def run_cmd(self, cmd):
        result = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Command failed:\n{cmd}\n\n"
                f"Error:\n{result.stderr}"
            )

        return result.stdout.strip()

    def run_cmd_raw(self, cmd):
        result = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=False
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Command failed:\n{cmd}\n\n"
                f"Error:\n{result.stderr.decode(errors='replace')}"
            )

        return result.stdout

    def transition(self, new_state):
        print(
            f"[STATE] {self.status.value} -> {new_state.value}"
        )

        self.status = new_state
        self.save_state()

    def save_state(self):
        state = {
            "configVersion": self.config_version,
            "stage": self.stage,
            "status": self.status.value,
            "startedAt": self.started_at
        }

        with open(self.state_file, "w") as file:
            json.dump(state, file, indent=2)

    # ---------------------------------------------------------
    # Validation
    # ---------------------------------------------------------

    def validate_candidate(self):
        self.transition(State.VALIDATING)

        print(
            f"[VALIDATE] Checking candidate: {self.candidate_file}"
        )

        if not os.path.exists(self.candidate_file):
            raise RuntimeError(
                f"Candidate file does not exist: {self.candidate_file}"
            )

        candidate_size = os.path.getsize(
            self.candidate_file
        )

        print(
            f"[VALIDATE] Candidate size={candidate_size} bytes"
        )

        if candidate_size > MAX_CONFIG_SIZE:
            raise RuntimeError(
                f"Candidate configuration exceeds maximum "
                f"allowed size of {MAX_CONFIG_SIZE} bytes"
            )

        import yaml

        project_dir = os.path.dirname(
            os.path.dirname(
                os.path.abspath(__file__)
            )
        )

        consumer_dir = os.path.join(
            project_dir,
            "consumer"
        )

        schema_path = os.path.join(
            consumer_dir,
            "schema",
            "rules.schema.json"
        )

        os.environ["SCHEMA_PATH"] = schema_path

        sys.path.insert(0, consumer_dir)

        from app.main import validate_config

        with open(self.candidate_file) as file:
            config = yaml.safe_load(file)

        if config is None:
            raise RuntimeError(
                "Candidate configuration is empty"
            )

        try:
            validate_config(config)
        except Exception as error:
            raise RuntimeError(
                f"Candidate validation failed: {error}"
            )

        self.config_version = config["version"]

        with open(self.candidate_file, "rb") as file:
            candidate_bytes = file.read()

        self.candidate_hash = hashlib.sha256(
            candidate_bytes
        ).hexdigest()

        print(
            "[VALIDATE] Candidate passed schema and semantic validation"
        )

        print(
            f"[VALIDATE] Config version: {self.config_version}"
        )

        print(
            f"[VALIDATE] Candidate SHA-256: {self.candidate_hash}"
        )

        if REQUIRE_SIGNATURE:
            signature_path = f"{self.candidate_file}.sig"

            print(
                f"[SIGNATURE] Verifying: {signature_path}"
            )

            if not os.path.exists(signature_path):
                raise RuntimeError(
                    f"Signature file does not exist: {signature_path}"
                )

            try:
                public_key = load_public_key(
                    PUBLIC_KEY_PATH
                )

                with open(signature_path, "r") as file:
                    signature = file.read().strip()

                signature_valid = verify_bytes(
                    candidate_bytes,
                    signature,
                    public_key
                )

            except Exception as error:
                raise RuntimeError(
                    f"Signature verification failed: {error}"
                )

            if not signature_valid:
                raise RuntimeError(
                    "Candidate signature is invalid"
                )

            print(
                "[SIGNATURE] Ed25519 verification passed"
            )

        if self.s3_store is not None:
            print(
                "[S3] Uploading validated candidate"
            )

            with open(self.candidate_file, "r") as file:
                candidate_content = file.read()

            s3_result = self.s3_store.upload_config(
                self.config_version,
                candidate_content
            )

            self.s3_version_id = s3_result["version_id"]

            print(
                f"[S3] Stored: {s3_result['key']}"
            )

            print(
                f"[S3] VersionId: {self.s3_version_id}"
            )

            print(
                f"[S3] SHA-256: {s3_result['sha256']}"
            )

            if s3_result["sha256"] != self.candidate_hash:
                raise RuntimeError(
                    "S3 SHA-256 does not match candidate"
                )

            print(
                "[S3] Integrity verification passed"
            )

            if REQUIRE_SIGNATURE:
                signature_path = (
                    f"{self.candidate_file}.sig"
                )

                with open(
                    signature_path,
                    "r"
                ) as file:
                    signature = file.read().strip()

                signature_result = (
                    self.s3_store.upload_signature(
                        self.config_version,
                        signature
                    )
                )

                print(
                    f"[S3] Signature stored: "
                    f"{signature_result['key']}"
                )

                print(
                    f"[S3] Signature VersionId: "
                    f"{signature_result['version_id']}"
                )

                print(
                    "[S3] Signed artifact pair stored"
                )

        self.save_state()

    # ---------------------------------------------------------
    # Kubernetes promotion
    # ---------------------------------------------------------

    def apply_to_cell(self, namespace):
        print(
            f"[K8S] Applying candidate configuration "
            f"to {namespace}"
        )

        # Save the original configuration once per cell.
        # Capture raw bytes so rollback can verify exact content.
        if namespace not in self.previous_configs:
            previous_command = (
                f"kubectl get configmap rules-config "
                f"-n {namespace} "
                f"-o jsonpath='{{.data.rules\\.yaml}}'"
            )

            previous_bytes = self.run_cmd_raw(previous_command)

            previous_hash = hashlib.sha256(
                previous_bytes
            ).hexdigest()

            self.previous_configs[namespace] = {
                "content": previous_bytes,
                "sha256": previous_hash,
            }

            print(
                f"[ROLLBACK] Saved previous configuration "
                f"for {namespace}"
            )

            print(
                f"[ROLLBACK] Previous SHA-256: {previous_hash}"
            )

        with open(self.candidate_file) as file:
            content = file.read()

        escaped = json.dumps(content)

        patch = (
            '{"data":{"rules.yaml":'
            + escaped +
            '}}'
        )

        command = (
            f"kubectl patch configmap rules-config "
            f"-n {namespace} "
            f"--type merge "
            f"-p '{patch}'"
        )

        self.run_cmd(command)

        restart_command = (
            f"kubectl rollout restart deployment/rules-consumer "
            f"-n {namespace}"
        )

        self.run_cmd(restart_command)

        rollout_wait_command = (
            f"kubectl rollout status deployment/rules-consumer "
            f"-n {namespace} --timeout=60s"
        )

        self.run_cmd(rollout_wait_command)

        print(
            f"[K8S] Consumer restarted in {namespace}"
        )

        print(
            f"[K8S] Candidate applied to {namespace}"
        )

    # ---------------------------------------------------------
    # Health
    # ---------------------------------------------------------

    def get_pod(self, namespace):
        command = (
            "kubectl get pods "
            "-n " + namespace + " "
            "-l app=rules-consumer "
            "--field-selector=status.phase=Running "
            "-o json"
        )

        output = self.run_cmd(command)

        import json

        data = json.loads(output)
        candidates = []

        for item in data.get("items", []):
            metadata = item.get("metadata", {})
            status = item.get("status", {})

            # Ignore pods that are being terminated.
            if metadata.get("deletionTimestamp"):
                continue

            # Only use pods whose Ready condition is True.
            ready = False
            for condition in status.get("conditions", []):
                if (
                    condition.get("type") == "Ready"
                    and condition.get("status") == "True"
                ):
                    ready = True
                    break

            if ready:
                candidates.append(item)

        if not candidates:
            raise RuntimeError(
                "No Ready rules-consumer pod found "
                "in " + namespace
            )

        # Prefer the newest Ready pod after a rollout.
        candidates.sort(
            key=lambda item: item.get("metadata", {}).get(
                "creationTimestamp", ""
            ),
            reverse=True
        )

        return candidates[0]["metadata"]["name"]

    def get_metrics(self, namespace):
        last_error = None

        for attempt in range(1, 6):
            try:
                # Find a fresh pod on every attempt.
                pod = self.get_pod(namespace)

                command = (
                    f"kubectl exec -n {namespace} {pod} -- "
                    f"python3 -c "
                    f"\"import urllib.request; "
                    f"print(urllib.request.urlopen("
                    f"'http://127.0.0.1:8080/metrics', "
                    f"timeout=5).read().decode())\""
                )

                raw = self.run_cmd(command)

                metrics = {}

                for line in raw.splitlines():
                    if line.startswith("#"):
                        continue

                    if not line.strip():
                        continue

                    parts = line.split()

                    if len(parts) == 2:
                        try:
                            metrics[parts[0]] = float(parts[1])
                        except ValueError:
                            continue

                return metrics

            except Exception as error:
                last_error = error

                print(
                    f"[HEALTH] Metrics attempt "
                    f"{attempt}/5 failed: {error}"
                )

                if attempt < 5:
                    time.sleep(2)

        raise RuntimeError(
            f"Unable to read metrics from "
            f"{namespace} after 5 attempts: {last_error}"
        )

    def query_prometheus(self, query):
        encoded_query = urllib.parse.quote(query, safe="")

        command = (
            f"python3 -c "
            f"\"import urllib.request, json; "
            f"url='{PROMETHEUS_URL}/api/v1/query?query={encoded_query}'; "
            f"data=json.loads("
            f"urllib.request.urlopen(url, timeout=5).read().decode()"
            f"); "
            f"print(json.dumps(data))\""
        )

        output = self.run_cmd(command)

        response = json.loads(output)

        if response.get("status") != "success":
            raise RuntimeError(
                f"Prometheus query failed: {response}"
            )

        return response.get(
            "data",
            {}
        ).get(
            "result",
            []
        )

    def check_prometheus_health(self, namespace):
        job_name = namespace.replace(
            "blast-cell-",
            "rules-consumer-cell-"
        )

        query = (
            f'rules_config_loaded{{job="{job_name}"}}'
        )

        results = self.query_prometheus(query)

        if not results:
            print(
                f"[PROMETHEUS] No metric found for {namespace}"
            )
            return False

        value = results[0].get("value", [None, "0"])[1]

        print(
            f"[PROMETHEUS] {namespace} "
            f"rules_config_loaded={value}"
        )

        return value == "1"

    def check_health(self, namespace, baseline_metrics=None):
        print(
            f"[HEALTH] Checking {namespace}"
        )

        # Check Deployment readiness at cell level.
        ready_command = (
            f"kubectl get deployment rules-consumer "
            f"-n {namespace} "
            f"-o jsonpath='{{.status.readyReplicas}}'"
        )

        try:
            ready_output = self.run_cmd(ready_command).strip()
            ready_replicas = int(ready_output or "0")
        except Exception as error:
            print(
                f"[HEALTH] Deployment readiness check failed: {error}"
            )
            return False

        print(
            f"[HEALTH] ready_replicas={ready_replicas}"
        )

        if ready_replicas < 1:
            print(
                "[HEALTH] No Ready rules-consumer replicas"
            )
            return False

        # Check application health endpoint.
        pod = self.get_pod(namespace)

        health_command = (
            f"kubectl exec -n {namespace} {pod} -- "
            f"python3 -c "
            f"\"import urllib.request; "
            f"urllib.request.urlopen("
            f"'http://127.0.0.1:8080/health', "
            f"timeout=5).read()\""
        )

        try:
            self.run_cmd(health_command)
        except Exception as error:
            print(
                f"[HEALTH] Application health check failed: {error}"
            )
            return False

        print(
            "[HEALTH] Application health endpoint is OK"
        )

        metrics = self.get_metrics(namespace)

        loaded = metrics.get(
            "rules_config_loaded",
            0
        )

        failures = metrics.get(
            "rules_config_reload_failure_total",
            0
        )

        print(
            f"[HEALTH] loaded={loaded} "
            f"failures={failures}"
        )

        if loaded != 1:
            return False

        if not self.check_prometheus_health(namespace):
            print(
                "[HEALTH] Prometheus health gate failed"
            )
            return False

        if baseline_metrics is not None:
            baseline_failures = baseline_metrics.get(
                "rules_config_reload_failure_total",
                0
            )

            if failures > baseline_failures:
                print(
                    "[HEALTH] Reload failure counter increased"
                )
                return False

        if self.candidate_hash is None:
            raise RuntimeError(
                "Candidate SHA-256 has not been calculated"
            )

        candidate_hash = self.candidate_hash

        # Re-select the pod instead of reusing an old pod.
        pod = self.get_pod(namespace)

        command = (
            f"kubectl exec -n {namespace} {pod} -- "
            f"sha256sum /config/rules.yaml"
        )

        output = self.run_cmd(command)

        active_hash = output.split()[0]

        print(
            f"[HEALTH] candidate_hash={candidate_hash}"
        )

        print(
            f"[HEALTH] active_hash={active_hash}"
        )

        if candidate_hash != active_hash:
            print(
                "[HEALTH] Candidate is not active"
            )
            return False

        print(
            "[HEALTH] Candidate is active and healthy"
        )

        return True

    def wait_for_candidate(self, namespace, timeout=90):
        print(
            f"[WAIT] Waiting for candidate to become active "
            f"in {namespace}"
        )

        deadline = time.time() + timeout

        while time.time() < deadline:
            if self.check_health(namespace):
                print(
                    f"[WAIT] Candidate is active in {namespace}"
                )
                return

            time.sleep(2)

        raise RuntimeError(
            f"Candidate did not become active in {namespace} "
            f"within {timeout} seconds"
        )

    def bake(self, seconds, namespace, baseline_metrics=None):
        self.transition(State.BAKING)

        print(
            f"[BAKE] {namespace} "
            f"for {seconds} seconds"
        )

        deadline = time.time() + seconds
        checks = 0

        while time.time() < deadline:
            checks += 1

            print(
                f"[BAKE] Health check #{checks} "
                f"for {namespace}"
            )

            try:
                healthy = self.check_health(
                    namespace,
                    baseline_metrics
                )
            except Exception as error:
                print(
                    f"[BAKE] Health check error: {error}"
                )
                healthy = False

            if not healthy:
                raise RuntimeError(
                    f"Health check failed during bake "
                    f"in {namespace}"
                )

            remaining = max(
                0,
                int(deadline - time.time())
            )

            print(
                f"[BAKE] Healthy — {remaining}s remaining"
            )

            if remaining > 0:
                time.sleep(min(5, remaining))

        self.transition(State.HEALTHY)

        print(
            f"[BAKE] Completed successfully for "
            f"{namespace} after {seconds} seconds"
        )

    # ---------------------------------------------------------
    # Rollback
    # ---------------------------------------------------------

    def rollback(self):
        self.transition(State.ROLLING_BACK)

        print(
            "[ROLLBACK] Restoring previous configurations"
        )

        if not self.previous_configs:
            print(
                "[ROLLBACK] No cell changes recorded"
            )
            return

        for namespace, rollback_data in reversed(
            list(self.previous_configs.items())
        ):
            print(
                f"[ROLLBACK] Restoring {namespace}"
            )

            previous_bytes = rollback_data["content"]
            expected_hash = rollback_data["sha256"]

            content = previous_bytes.decode("utf-8")
            escaped = json.dumps(content)

            patch = (
                '{"data":{"rules.yaml":'
                + escaped +
                '}}'
            )

            command = (
                f"kubectl patch configmap rules-config "
                f"-n {namespace} "
                f"--type merge "
                f"-p '{patch}'"
            )

            self.run_cmd(command)

            # Restart so the restored ConfigMap becomes active.
            restart_command = (
                f"kubectl rollout restart deployment/rules-consumer "
                f"-n {namespace}"
            )

            self.run_cmd(restart_command)

            rollout_wait_command = (
                f"kubectl rollout status deployment/rules-consumer "
                f"-n {namespace} --timeout=60s"
            )

            self.run_cmd(rollout_wait_command)

            # Verify the restored ConfigMap against the exact
            # previously captured SHA-256.
            verify_command = (
                f"kubectl get configmap rules-config "
                f"-n {namespace} "
                f"-o jsonpath='{{.data.rules\\.yaml}}'"
            )

            restored_bytes = self.run_cmd_raw(
                verify_command
            )

            restored_hash = hashlib.sha256(
                restored_bytes
            ).hexdigest()

            print(
                f"[ROLLBACK] Restored SHA-256: {restored_hash}"
            )

            if restored_hash != expected_hash:
                raise RuntimeError(
                    f"Rollback integrity verification failed "
                    f"for {namespace}: "
                    f"expected {expected_hash}, "
                    f"got {restored_hash}"
                )

            print(
                f"[ROLLBACK] Integrity verified for {namespace}"
            )

            print(
                f"[ROLLBACK] Restored {namespace}"
            )

        print(
            "[ROLLBACK] Cross-cell rollback completed"
        )

    # ---------------------------------------------------------
    # Promotion
    # ---------------------------------------------------------

    def promote(self):

        stages = [
            ("INTERNAL", "blast-cell-1", BAKE_INTERNAL),
            ("1%", "blast-cell-1", BAKE_1_PERCENT),
            ("10%", "blast-cell-2", BAKE_10_PERCENT),
            ("100%", "blast-cell-3", 0),
        ]

        for stage, namespace, bake_time in stages:

            self.transition(State.PROMOTING)

            self.stage = stage
            self.save_state()

            print(
                f"[PROMOTE] {self.config_version} "
                f"-> {stage}"
            )

            baseline_metrics = self.get_metrics(namespace)

            print(
                f"[BASELINE] {namespace} "
                f"successes="
                f"{baseline_metrics.get('rules_config_reload_success_total', 0)} "
                f"failures="
                f"{baseline_metrics.get('rules_config_reload_failure_total', 0)}"
            )

            self.apply_to_cell(namespace)

            self.wait_for_candidate(namespace)

            if (
                INJECT_RUNTIME_FAILURE
                and namespace == "blast-cell-1"
                and bake_time > 0
            ):
                print(
                    "[TEST] Injecting deterministic runtime health failure "
                    f"in {namespace}"
                )

                self.run_cmd(
                    "kubectl set env deployment/rules-consumer "
                    f"-n {namespace} "
                    "FORCE_HEALTH_FAILURE=true"
                )

                self.run_cmd(
                    "kubectl rollout status deployment/rules-consumer "
                    f"-n {namespace} --timeout=60s"
                )

            if bake_time > 0:

                self.bake(
                    bake_time,
                    namespace,
                    baseline_metrics
                )

            else:

                healthy = self.check_health(
                    namespace,
                    baseline_metrics
                )

                if not healthy:
                    raise RuntimeError(
                        f"Health check failed in {namespace}"
                    )

                self.transition(State.HEALTHY)

        self.transition(State.COMPLETED)

    # ---------------------------------------------------------
    # Controller entry point
    # ---------------------------------------------------------

    def run(self):

        print("=" * 70)
        print("BLAST RADIUS GUARD — PROMOTION CONTROLLER")
        print("=" * 70)

        try:

            self.validate_candidate()

            self.promote()

            print("=" * 70)
            print("PROMOTION COMPLETED")
            print("=" * 70)

        except Exception as error:

            print(
                f"\n[FAILURE] {error}"
            )

            self.transition(State.HALTED)

            try:
                self.rollback()
            except Exception as rollback_error:
                print(
                    f"[ROLLBACK FAILURE] {rollback_error}"
                )

            print("=" * 70)
            print("ROLLOUT HALTED AND ROLLBACK INITIATED")
            print("=" * 70)

            return 2

        return 0


def main():

    if len(sys.argv) != 2:

        print(
            "Usage: python3 "
            "controller/rollout_guard.py "
            "<candidate.yaml>"
        )

        sys.exit(1)

    candidate = sys.argv[1]

    controller = PromotionController(
        candidate
    )

    sys.exit(
        controller.run()
    )


if __name__ == "__main__":
    main()
