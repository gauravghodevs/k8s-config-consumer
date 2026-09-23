import os
import shutil
import time
import yaml
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
INCOMING_PATH = os.getenv("CONFIG_PATH", "/etc/rules/rules.yaml")
STORAGE_DIR = "/var/lib/rules"
CURRENT_PATH = os.path.join(STORAGE_DIR, "current.yaml")
LKG_PATH = os.path.join(STORAGE_DIR, "last-known-good.yaml")

# Metrics state
METRICS = {
    "rules_loaded_total": 0,
    "rules_rejected_total": 0,
    "rules_active_count": 0,
}

def validate_config(data):
    if not isinstance(data, dict):
        return False, "Root config must be a YAML mapping/dictionary"
    if "version" not in data or not isinstance(data["version"], str):
        return False, "Missing or invalid 'version' field"
    if "rules" not in data or not isinstance(data["rules"], list):
        return False, "Missing or invalid 'rules' list"

    for idx, rule in enumerate(data["rules"]):
        if not isinstance(rule, dict):
            return False, f"Rule index {idx} must be a dictionary"
        if "name" not in rule or not isinstance(rule["name"], str):
            return False, f"Rule index {idx} missing string 'name'"
        if rule.get("action") not in ["allow", "deny"]:
            return False, f"Rule '{rule.get('name')}' action must be 'allow' or 'deny'"
        if "priority" not in rule or not isinstance(rule["priority"], int):
            return False, f"Rule '{rule.get('name')}' priority must be an integer"

    return True, "Valid"

def apply_config(raw_content):
    global METRICS
    try:
        parsed = yaml.safe_load(raw_content)
    except yaml.YAMLError as e:
        METRICS["rules_rejected_total"] += 1
        print(f"[REJECT] YAML Syntax Error: {e}")
        return False

    is_valid, msg = validate_config(parsed)
    if not is_valid:
        METRICS["rules_rejected_total"] += 1
        print(f"[REJECT] Semantic Validation Failed: {msg}")
        return False

    # Rotate and save valid config
    os.makedirs(STORAGE_DIR, exist_ok=True)
    if os.path.exists(CURRENT_PATH):
        shutil.copyfile(CURRENT_PATH, LKG_PATH)

    with open(CURRENT_PATH, "w") as f:
        yaml.safe_dump(parsed, f)

    if not os.path.exists(LKG_PATH):
        shutil.copyfile(CURRENT_PATH, LKG_PATH)

    METRICS["rules_loaded_total"] += 1
    METRICS["rules_active_count"] = len(parsed.get("rules", []))
    print(f"[LOAD] Config v{parsed['version']} loaded with {METRICS['rules_active_count']} rules.")
    return True

class HealthMetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        elif self.path == "/metrics":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            output = (
                f"# HELP rules_loaded_total Total number of valid rule configs loaded\n"
                f"# TYPE rules_loaded_total counter\n"
                f"rules_loaded_total {METRICS['rules_loaded_total']}\n\n"
                f"# HELP rules_rejected_total Total number of invalid rule configs rejected\n"
                f"# TYPE rules_rejected_total counter\n"
                f"rules_rejected_total {METRICS['rules_rejected_total']}\n\n"
                f"# HELP rules_active_count Current number of active rules\n"
                f"# TYPE rules_active_count gauge\n"
                f"rules_active_count {METRICS['rules_active_count']}\n"
            )
            self.wfile.write(output.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return  # Silence access logs to keep terminal clean

def run_server():
    server = HTTPServer(("0.0.0.0", 8080), HealthMetricsHandler)
    server.serve_forever()

def main():
    print("[INIT] Starting blast-radius-guard consumer...")
    os.makedirs(STORAGE_DIR, exist_ok=True)

    threading.Thread(target=run_server, daemon=True).start()
    print("[SERVER] Health (/healthz) and Metrics (/metrics) running on port 8080.")

    last_content = None
    while True:
        if os.path.exists(INCOMING_PATH):
            try:
                with open(INCOMING_PATH, "r") as f:
                    current_content = f.read()
                if current_content != last_content:
                    print("[CHANGE] Detected modification in rules file.")
                    apply_config(current_content)
                    last_content = current_content
            except Exception as e:
                print(f"[ERROR] Reading file failed: {e}")
        else:
            print(f"[WARN] Config path {INCOMING_PATH} not mounted yet...")

        time.sleep(3)

if __name__ == "__main__":
    main()
