import os
import sys
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parents[1]
CONSUMER_DIR = BASE_DIR / "consumer"
SCHEMA = CONSUMER_DIR / "schema" / "rules.schema.json"

os.environ["SCHEMA_PATH"] = str(SCHEMA)
sys.path.insert(0, str(CONSUMER_DIR))

from app.main import validate_config


def test_broken_candidate_is_rejected():
    path = BASE_DIR / "config" / "candidate-v1.5-bad.yaml"

    with path.open() as file:
        config = yaml.safe_load(file)

    try:
        validate_config(config)
    except ValueError as error:
        message = str(error)

        assert (
            "Schema validation failed" in message
            or "action" in message
        )

    else:
        raise AssertionError(
            "BROKEN CANDIDATE WAS ACCEPTED"
        )


if __name__ == "__main__":
    test_broken_candidate_is_rejected()
    print("CI FAILURE-GUARD TEST PASSED")
