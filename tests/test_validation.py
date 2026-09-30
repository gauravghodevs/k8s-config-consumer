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


def load_yaml(filename):
    path = BASE_DIR / "config" / filename

    with path.open() as file:
        return yaml.safe_load(file)


def test_valid_candidate_passes():
    config = load_yaml("candidate-v1.4.yaml")

    validate_config(config)


def test_invalid_action_fails():
    config = load_yaml("candidate-v1.5-bad.yaml")

    try:
        validate_config(config)
    except ValueError as error:
        assert (
            "Schema validation failed" in str(error)
            or "action" in str(error)
        )
    else:
        raise AssertionError(
            "Invalid action candidate unexpectedly passed validation"
        )


def test_duplicate_rule_name_fails():
    config = load_yaml("candidate-v1.5-failure.yaml")

    try:
        validate_config(config)
    except ValueError as error:
        assert "Duplicate rule name" in str(error)
    else:
        raise AssertionError(
            "Duplicate rule candidate unexpectedly passed validation"
        )


if __name__ == "__main__":
    test_valid_candidate_passes()
    test_invalid_action_fails()
    test_duplicate_rule_name_fails()

    print("VALIDATION TESTS PASSED")
