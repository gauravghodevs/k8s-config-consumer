import os
import sys
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml


BASE_DIR = Path(__file__).resolve().parents[1]
APP = BASE_DIR / "consumer" / "app" / "main.py"
SCHEMA = BASE_DIR / "consumer" / "schema" / "rules.schema.json"


VALID_CONFIG = {
    "version": "1.0",
    "rules": [
        {
            "name": "block_bad_ip",
            "action": "deny",
            "priority": 305,
        },
        {
            "name": "allow_internal",
            "action": "allow",
            "priority": 10,
        },
    ],
}


INVALID_CONFIG = {
    "version": "1.0",
    "rules": [
        {
            "name": "block_bad_ip",
            "action": "banana",
            "priority": 305,
        }
    ],
}


def wait_for_ready(expected_status):
    url = "http://127.0.0.1:8080/ready"

    for _ in range(30):
        try:
            response = urllib.request.urlopen(url, timeout=1)
            status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        except Exception:
            status = None

        if status == expected_status:
            return True

        time.sleep(1)

    return False


def run_consumer(config):
    tmp_dir = Path(tempfile.mkdtemp())

    config_path = tmp_dir / "rules.yaml"
    data_dir = tmp_dir / "data"
    data_dir.mkdir()

    with config_path.open("w") as file:
        yaml.safe_dump(config, file)

    env = os.environ.copy()
    env["CONFIG_PATH"] = str(config_path)
    env["SCHEMA_PATH"] = str(SCHEMA)
    env["DATA_DIR"] = str(data_dir)
    env["POLL_INTERVAL"] = "1"

    process = subprocess.Popen(
        [sys.executable, str(APP)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )

    return process, data_dir, tmp_dir


def stop_consumer(process, tmp_dir):
    process.terminate()

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)

    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_valid_config_reaches_ready():
    process, data_dir, tmp_dir = run_consumer(VALID_CONFIG)

    try:
        assert wait_for_ready(200), (
            "Valid configuration did not make the consumer ready"
        )

        assert (data_dir / "current.yaml").exists()
        assert (data_dir / "last-known-good.yaml").exists()

    finally:
        stop_consumer(process, tmp_dir)


def test_invalid_config_is_rejected():
    process, data_dir, tmp_dir = run_consumer(INVALID_CONFIG)

    try:
        assert wait_for_ready(503), (
            "Invalid configuration was not rejected"
        )

        assert not (data_dir / "current.yaml").exists()
        assert not (data_dir / "last-known-good.yaml").exists()

    finally:
        stop_consumer(process, tmp_dir)


if __name__ == "__main__":
    test_valid_config_reaches_ready()
    test_invalid_config_is_rejected()
    print("CONSUMER CONTRACT TESTS PASSED")
