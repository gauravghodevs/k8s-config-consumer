#!/bin/bash
import os
import time

def main():
    app_env = os.getenv("APP_ENV", "development")
    db_host = os.getenv("DB_HOST", "localhost")
    poll_interval = int(os.getenv("POLL_INTERVAL", "5"))

    print(f"Starting Config Consumer...")
    print(f"Target Environment: {app_env}")
    print(f"Database Host: {db_host}")

    while True:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S' )}] Config synced successfully. App running in '{app_env}' mode targeting '{db_host}'.")
        time.sleep(poll_interval)

if __name__ == "__main__":
    main()
