import os
import shutil
import yaml

# These globals and constants should match your existing project setup
METRICS = {
    "rules_rejected_total": 0,
    "rules_loaded_total": 0,
    "rules_active_count": 0
}
STORAGE_DIR = "/etc/blast-radius-guard"  # Adjust this path as needed
CURRENT_PATH = os.path.join(STORAGE_DIR, "config.yaml")
LKG_PATH = os.path.join(STORAGE_DIR, "config_lkg.yaml")

def validate_config(data):
    """
    Validates the structure and data types of the parsed YAML configuration.
    Returns a tuple: (is_valid: bool, message: str)
    """
    # Ensure the root of the YAML is a dictionary
    if not isinstance(data, dict):
        return False, "Root config must be a YAML mapping/dictionary"
    
    # Check for the version field
    if "version" not in data or not isinstance(data["version"], str):
        return False, "Missing or invalid 'version' field"
        
    # Ensure rules exist and are formatted as a list
    if "rules" not in data or not isinstance(data["rules"], list):
        return False, "Missing or invalid 'rules' list"
        
    # Iterate through and validate each individual rule
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
    """
    Parses raw YAML, validates the schema, and safely updates the configuration files.
    """
    global METRICS
    
    # Step 1: Parse the YAML
    try:
        parsed = yaml.safe_load(raw_content)
    except yaml.YAMLError as e:
        METRICS["rules_rejected_total"] += 1
        print(f"[REJECT] YAML Syntax Error: {e}", flush=True)
        return False
        
    # Step 2: Validate the semantic structure
    is_valid, msg = validate_config(parsed)
    if not is_valid:
        METRICS["rules_rejected_total"] += 1
        print(f"[REJECT] Semantic Validation Failed: {msg}", flush=True)
        return False
        
    # Step 3: Manage files and create backups
    os.makedirs(STORAGE_DIR, exist_ok=True)
    
    # If a current config exists, back it up to the LKG (Last Known Good) path
    if os.path.exists(CURRENT_PATH):
        shutil.copyfile(CURRENT_PATH, LKG_PATH)
        
    # Write the new parsed configuration to the current path
    with open(CURRENT_PATH, "w") as f:
        yaml.safe_dump(parsed, f)
        
    # If an LKG backup didn't exist before, create one now to establish a baseline
    if not os.path.exists(LKG_PATH):
        shutil.copyfile(CURRENT_PATH, LKG_PATH)
        
    # Step 4: Update success metrics
    METRICS["rules_loaded_total"] += 1
    METRICS["rules_active_count"] = len(parsed.get("rules", []))
    
    return True


