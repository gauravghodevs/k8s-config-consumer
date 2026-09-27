#!/usr/bin/env python3

import subprocess
import sys
import os
import json
import time
import hashlib
from enum import Enum
from datetime import datetime, timezone


BAKE_INTERNAL = int(os.getenv("BAKE_INTERNAL", "30"))
BAKE_1_PERCENT = int(os.getenv("BAKE_1_PERCENT", "60"))
BAKE_10_PERCENT = int(os.getenv("BAKE_10_PERCENT", "60"))


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

        print(
            "[VALIDATE] Candidate passed schema and semantic validation"
        )

        print(
            f"[VALIDATE] Config version: {self.config_version}"
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

        # Save the original configuration once per cell
        if namespace not in self.previous_configs:
            previous_command = (
                f"kubectl get configmap rules-config "
                f"-n {namespace} "
                f"-o jsonpath='{{.data.rules\\.yaml}}'"
            )

            previous_content = self.run_cmd(previous_command)

            self.previous_configs[namespace] = previous_content

            print(
                f"[ROLLBACK] Saved previous configuration "
                f"for {namespace}"
            )

        content = open(self.candidate_file).read()

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

        print(
            f"[K8S] Candidate applied to {namespace}"
        )

    # ---------------------------------------------------------
    # Health
    # ---------------------------------------------------------

    def get_pod(self, namespace):
        command = (
            f"kubectl get pods "
            f"-n {namespace} "
            f"-l app=rules-consumer "
            f"-o jsonpath='{{.items[0].metadata.name}}'"
        )

        pod = self.run_cmd(command)

        if not pod:
            raise RuntimeError(
                f"No rules-consumer pod found "
                f"in {namespace}"
            )

        return pod

    def get_metrics(self, namespace):
        pod = self.get_pod(namespace)

        command = (
            f"kubectl exec -n {namespace} {pod} -- "
            f"python3 -c "
            f"\"import urllib.request; "
            f"print(urllib.request.urlopen("
            f"'http://localhost:8080/metrics', "
            f"timeout=3).read().decode())\""
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

    def check_health(self, namespace, baseline_metrics=None):
        print(f"[HEALTH] Checking {namespace}")

        metrics = self.get_metrics(namespace)

        loaded = metrics.get("rules_config_loaded", 0)
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

        with open(self.candidate_file, "rb") as file:
            candidate_hash = hashlib.sha256(
                file.read()
            ).hexdigest()

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

    def bake(self, seconds, namespace, baseline_metrics=None):
        self.transition(State.BAKING)

        print(
            f"[BAKE] {namespace} "
            f"for up to {seconds} seconds"
        )

        deadline = time.time() + seconds

        while time.time() < deadline:
            if self.check_health(
                namespace,
                baseline_metrics
            ):
                self.transition(State.HEALTHY)
                return

            time.sleep(2)

        raise RuntimeError(
            f"Health check failed in {namespace} "
            f"after {seconds} seconds"
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

        # Restore in reverse order of promotion
        for namespace, content in reversed(
            list(self.previous_configs.items())
        ):
            print(
                f"[ROLLBACK] Restoring {namespace}"
            )

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

            print(
                f"[ROLLBACK] Restored {namespace}"
            )

        print(
            "[ROLLBACK] Cross-cell rollback completed"
        )

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

            self.rollback()

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
