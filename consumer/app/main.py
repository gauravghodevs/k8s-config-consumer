import hashlib
import os
import shutil
import threading
import time
from pathlib import Path

import yaml
from flask import Flask, jsonify
from prometheus_client import Counter, Gauge, generate_latest
from werkzeug.wrappers import Response


# ============================================================
# Configuration
# ============================================================

CONFIG_PATH = Path(
    os.getenv("CONFIG_PATH", "/config/rules.yaml")
)

DATA_DIR = Path(
    os.getenv("DATA_DIR", "/var/lib/rules")
)

CURRENT_CONFIG = DATA_DIR / "current.yaml"
LAST_KNOWN_GOOD = DATA_DIR / "last-known-good.yaml"

POLL_INTERVAL = float(
    os.getenv("POLL_INTERVAL", "2")
)


# ============================================================
# Flask
# ============================================================

app = Flask(__name__)


# ============================================================
# Prometheus metrics
# ============================================================

CONFIG_LOADED = Gauge(
    "rules_config_loaded",
    "Whether a valid configuration is currently loaded"
)

CONFIG_VERSION = Gauge(
    "rules_config_version",
    "Current configuration version"
)

RELOAD_SUCCESS = Counter(
    "rules_config_reload_success_total",
    "Number of successful configuration reloads"
)

RELOAD_FAILURE = Counter(
    "rules_config_reload_failure_total",
    "Number of failed configuration reloads"
)

LAST_RELOAD_TIMESTAMP = Gauge(
    "rules_config_last_reload_timestamp",
    "Unix timestamp of the last successful reload"
)


# ============================================================
# Runtime state
# ============================================================

state_lock = threading.Lock()

current_config = None
last_config_hash = None


# ============================================================
# Validation
# ============================================================

def validate_config(config):
    """
    Validate structure and semantics of the configuration.
    """

    if not isinstance(config, dict):
        raise ValueError("Configuration must be a YAML object")

    if "version" not in config:
        raise ValueError("Missing 'version'")

    if "rules" not in config:
        raise ValueError("Missing 'rules'")

    if not isinstance(config["rules"], list):
        raise ValueError("'rules' must be a list")

    valid_actions = {"allow", "deny"}

    rule_names = set()

    for rule in config["rules"]:

        if not isinstance(rule, dict):
            raise ValueError("Each rule must be an object")

        required_fields = {
            "name",
            "action",
            "priority",
        }

        missing = required_fields - rule.keys()

        if missing:
            raise ValueError(
                f"Rule missing fields: {missing}"
            )

        name = rule["name"]
        action = rule["action"]
        priority = rule["priority"]

        if name in rule_names:
            raise ValueError(
                f"Duplicate rule name: {name}"
            )

        rule_names.add(name)

        if action not in valid_actions:
            raise ValueError(
                f"Invalid action: {action}"
            )

        if not isinstance(priority, int):
            raise ValueError(
                f"Priority must be integer: {name}"
            )

        if priority < 0:
            raise ValueError(
                f"Priority cannot be negative: {name}"
            )

    return True


# ============================================================
# File helpers
# ============================================================

def calculate_hash(path):
    """
    Calculate SHA256 of the configuration file.
    """

    data = path.read_bytes()

    return hashlib.sha256(data).hexdigest()


def atomic_copy(source, destination):
    """
    Copy file atomically.

    Write to a temporary file first, then rename it.
    """

    temporary = destination.with_suffix(
        destination.suffix + ".tmp"
    )

    shutil.copyfile(source, temporary)

    os.replace(
        temporary,
        destination
    )


# ============================================================
# Configuration loader
# ============================================================

def load_configuration():
    global current_config
    global last_config_hash

    if not CONFIG_PATH.exists():

        raise FileNotFoundError(
            f"Configuration file does not exist: {CONFIG_PATH}"
        )

    new_hash = calculate_hash(CONFIG_PATH)

    # No change.
    if new_hash == last_config_hash:
        return

    print(
        f"Configuration change detected: {CONFIG_PATH}"
    )

    try:

        with CONFIG_PATH.open("r") as file:

            config = yaml.safe_load(file)

        # ----------------------------------------------------
        # Parse + semantic validation
        # ----------------------------------------------------

        validate_config(config)

        # ----------------------------------------------------
        # Promote configuration
        # ----------------------------------------------------

        DATA_DIR.mkdir(
            parents=True,
            exist_ok=True
        )

        atomic_copy(
            CONFIG_PATH,
            LAST_KNOWN_GOOD
        )

        atomic_copy(
            CONFIG_PATH,
            CURRENT_CONFIG
        )

        # ----------------------------------------------------
        # Update runtime state
        # ----------------------------------------------------

        with state_lock:

            current_config = config

        last_config_hash = new_hash

        # ----------------------------------------------------
        # Metrics
        # ----------------------------------------------------

        CONFIG_LOADED.set(1)

        try:

            CONFIG_VERSION.set(
                float(config["version"])
            )

        except (ValueError, TypeError):

            CONFIG_VERSION.set(0)

        RELOAD_SUCCESS.inc()

        LAST_RELOAD_TIMESTAMP.set(
            time.time()
        )

        print(
            "Configuration loaded successfully"
        )

    except Exception as error:

        RELOAD_FAILURE.inc()

        print(
            f"Configuration reload failed: {error}"
        )

        # IMPORTANT:
        # Do NOT update last_config_hash.
        #
        # This means the same bad configuration will be
        # retried on the next polling cycle.
        #
        # Most importantly, current_config remains unchanged.


# ============================================================
# Background configuration watcher
# ============================================================

def configuration_watcher():

    print(
        f"Watching {CONFIG_PATH}"
    )

    while True:

        try:

            load_configuration()

        except Exception as error:

            print(
                f"Watcher error: {error}"
            )

        time.sleep(
            POLL_INTERVAL
        )


# ============================================================
# Health endpoints
# ============================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "ok"
    })


@app.route("/ready")
def ready():

    with state_lock:

        loaded = current_config is not None

    if loaded:

        return jsonify({
            "status": "ready"
        }), 200

    return jsonify({
        "status": "not_ready"
    }), 503


# ============================================================
# Metrics endpoint
# ============================================================

@app.route("/metrics")
def metrics():

    return Response(
        generate_latest(),
        mimetype="text/plain"
    )


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # Initial configuration load.
    try:

        load_configuration()

    except Exception as error:

        print(
            f"Initial configuration load failed: {error}"
        )

    # Start watcher.
    watcher_thread = threading.Thread(
        target=configuration_watcher,
        daemon=True
    )

    watcher_thread.start()

    # Start HTTP server.
    app.run(
        host="0.0.0.0",
        port=8080
    )
