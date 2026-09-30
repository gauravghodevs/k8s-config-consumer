import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
CONTROLLER_DIR = BASE_DIR / "controller"

sys.path.insert(0, str(CONTROLLER_DIR))

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


if __name__ == "__main__":
    test_valid_candidate_validation()
    test_invalid_candidate_validation()

    print("CONTROLLER VALIDATION TESTS PASSED")
