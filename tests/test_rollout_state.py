import base64
import hashlib
import json
from pathlib import Path

import pytest

from controller.rollout_guard import (
    PromotionController,
    State,
)


def create_controller(tmp_path, monkeypatch):
    state_file = tmp_path / "blast-radius-guard-state.json"

    monkeypatch.setattr(
        PromotionController,
        "state_file",
        str(state_file),
        raising=False,
    )

    controller = PromotionController(
        str(tmp_path / "candidate.yaml")
    )

    controller.state_file = str(state_file)

    return controller


def test_state_persists_previous_config(tmp_path):
    controller = PromotionController(
        str(tmp_path / "candidate.yaml")
    )

    controller.state_file = str(
        tmp_path / "blast-radius-guard-state.json"
    )

    previous_bytes = (
        b'version: "1.3"\n'
        b"rules:\n"
        b"  - name: allow_internal\n"
        b"    action: allow\n"
        b"    priority: 10\n"
    )

    previous_hash = hashlib.sha256(
        previous_bytes
    ).hexdigest()

    controller.config_version = "1.4"
    controller.stage = "10%"
    controller.status = State.BAKING

    controller.previous_configs = {
        "blast-cell-1": {
            "content": previous_bytes,
            "sha256": previous_hash,
        }
    }

    controller.save_state()

    state = json.loads(
        Path(controller.state_file).read_text()
    )

    assert state["configVersion"] == "1.4"
    assert state["stage"] == "10%"
    assert state["status"] == "BAKING"

    persisted = state["previousConfigs"][
        "blast-cell-1"
    ]

    assert (
        base64.b64decode(
            persisted["content"]
        )
        == previous_bytes
    )

    assert persisted["sha256"] == previous_hash


def test_controller_recovers_previous_config_after_restart(
    tmp_path
):
    state_file = (
        tmp_path /
        "blast-radius-guard-state.json"
    )

    candidate = (
        tmp_path /
        "candidate.yaml"
    )

    candidate.write_text(
        'version: "1.4"\n'
    )

    previous_bytes = (
        b'version: "1.3"\n'
        b"rules:\n"
        b"  - name: allow_internal\n"
        b"    action: allow\n"
        b"    priority: 10\n"
    )

    previous_hash = hashlib.sha256(
        previous_bytes
    ).hexdigest()

    state = {
        "configVersion": "1.4",
        "stage": "10%",
        "status": "BAKING",
        "startedAt": "2026-10-05T00:00:00+00:00",
        "previousConfigs": {
            "blast-cell-1": {
                "content": base64.b64encode(
                    previous_bytes
                ).decode("ascii"),
                "sha256": previous_hash,
            }
        },
    }

    state_file.write_text(
        json.dumps(state, indent=2)
    )

    controller = PromotionController(
        str(candidate)
    )

    controller.state_file = str(state_file)

    controller.load_state()

    assert controller.config_version == "1.4"
    assert controller.stage == "10%"
    assert controller.status == State.BAKING

    assert (
        controller.previous_configs[
            "blast-cell-1"
        ]["content"]
        == previous_bytes
    )

    assert (
        controller.previous_configs[
            "blast-cell-1"
        ]["sha256"]
        == previous_hash
    )


def test_corrupted_persisted_config_is_rejected(
    tmp_path
):
    state_file = (
        tmp_path /
        "blast-radius-guard-state.json"
    )

    candidate = (
        tmp_path /
        "candidate.yaml"
    )

    candidate.write_text(
        'version: "1.4"\n'
    )

    original_bytes = b'version: "1.3"\n'

    state = {
        "configVersion": "1.4",
        "stage": "10%",
        "status": "BAKING",
        "startedAt": "2026-10-05T00:00:00+00:00",
        "previousConfigs": {
            "blast-cell-1": {
                "content": base64.b64encode(
                    b"tampered-content"
                ).decode("ascii"),
                "sha256": hashlib.sha256(
                    original_bytes
                ).hexdigest(),
            }
        },
    }

    state_file.write_text(
        json.dumps(state, indent=2)
    )

    controller = PromotionController(
        str(candidate)
    )

    controller.state_file = str(state_file)

    with pytest.raises(
        RuntimeError,
        match="Persisted rollback state integrity check failed",
    ):
        controller.load_state()


def test_save_state_uses_atomic_replace(tmp_path):
    state_file = (
        tmp_path /
        "blast-radius-guard-state.json"
    )

    controller = PromotionController(
        str(tmp_path / "candidate.yaml")
    )

    controller.state_file = str(state_file)

    controller.config_version = "1.4"
    controller.stage = "1%"
    controller.status = State.HEALTHY

    controller.save_state()

    assert state_file.exists()

    temp_file = Path(
        f"{state_file}.tmp"
    )

    assert not temp_file.exists()

    state = json.loads(
        state_file.read_text()
    )

    assert state["configVersion"] == "1.4"
    assert state["stage"] == "1%"
    assert state["status"] == "HEALTHY"
