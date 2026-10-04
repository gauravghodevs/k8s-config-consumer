import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
CONTROLLER_DIR = BASE_DIR / "controller"

sys.path.insert(0, str(CONTROLLER_DIR))

import rollout_guard
from rollout_guard import PromotionController


VALID_CANDIDATE = (
    BASE_DIR / "config" / "candidate-v1.4.yaml"
)

INVALID_CANDIDATE = (
    BASE_DIR / "config" / "candidate-v1.5-bad.yaml"
)


def test_valid_candidate_validation():
    controller = PromotionController(
        str(VALID_CANDIDATE)
    )

    controller.validate_candidate()

    assert controller.config_version == "1.4"
    assert controller.status.value == "VALIDATING"


def test_invalid_candidate_validation():
    controller = PromotionController(
        str(INVALID_CANDIDATE)
    )

    try:
        controller.validate_candidate()
    except RuntimeError as error:
        assert "Candidate validation failed" in str(error)
    else:
        raise AssertionError(
            "Invalid candidate unexpectedly passed controller validation"
        )


def test_missing_signature_is_rejected(monkeypatch, tmp_path):
    candidate = tmp_path / "candidate.yaml"

    candidate.write_bytes(
        VALID_CANDIDATE.read_bytes()
    )

    monkeypatch.setattr(
        rollout_guard,
        "REQUIRE_SIGNATURE",
        True,
    )

    controller = PromotionController(
        str(candidate)
    )

    try:
        controller.validate_candidate()
    except RuntimeError as error:
        assert "Signature file does not exist" in str(error)
    else:
        raise AssertionError(
            "Unsigned candidate unexpectedly passed validation"
        )


def test_invalid_signature_is_rejected(monkeypatch, tmp_path):
    candidate = tmp_path / "candidate.yaml"
    signature = tmp_path / "candidate.yaml.sig"

    candidate.write_bytes(
        VALID_CANDIDATE.read_bytes()
    )

    signature.write_text(
        "invalid-signature"
    )

    monkeypatch.setattr(
        rollout_guard,
        "REQUIRE_SIGNATURE",
        True,
    )

    controller = PromotionController(
        str(candidate)
    )

    try:
        controller.validate_candidate()
    except RuntimeError as error:
        assert (
            "Candidate signature is invalid"
            in str(error)
            or "Signature verification failed"
            in str(error)
        )
    else:
        raise AssertionError(
            "Invalid signature unexpectedly passed validation"
        )


if __name__ == "__main__":
    test_valid_candidate_validation()
    test_invalid_candidate_validation()

    print("CONTROLLER VALIDATION TESTS PASSED")
