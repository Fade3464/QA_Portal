"""Check actual SCRAM authentication and PostgreSQL through the pool."""

import os
import subprocess
import sys


if __name__ == "__main__":
    env = {
        **os.environ,
        "PGHOST": "127.0.0.1",
        "PGPORT": "6432",
        "PGDATABASE": os.environ["POSTGRES_DB"],
        "PGUSER": os.environ["POSTGRES_USER"],
        "PGPASSWORD": os.environ["POSTGRES_PASSWORD"],
        "PGCONNECT_TIMEOUT": "3",
        "PGOPTIONS": "",
    }
    try:
        result = subprocess.run(
            ["psql", "-X", "-w", "-tAc", "SELECT 1"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
        sys.exit(0 if result.returncode == 0 and result.stdout.strip() == b"1" else 1)
    except (subprocess.TimeoutExpired, OSError):
        sys.exit(1)
