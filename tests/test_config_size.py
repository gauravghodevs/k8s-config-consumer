import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
CONTROLLER_DIR = BASE_DIR / "controller"

sys.path.insert(0, str(CONTROLLER_DIR))

from rollout_guard import PromotionController


OVERSIZED_CANDIDATE = (
    BASE_DIR / "config" / "candidate-oversized.yaml"
)


def test_oversized_candidate_is_rejected():
    controller = PromotionController(
        str(OVERSIZED_CANDIDATE)
    )

    try:
        controller.validate_candidate()

    except RuntimeError as error:
        assert "exceeds maximum" in str(error)

    else:
        raise AssertionError(
            "OVERSIZED CANDIDATE WAS ACCEPTED"
        )


if __name__ == "__main__":
    test_oversized_candidate_is_rejected()
    print("CONFIG SIZE TEST PASSED")
