"""Render private, ephemeral configuration without printing credentials."""

import os
import re
import sys
from pathlib import Path

RUNTIME = Path("/tmp/calllens-pgbouncer")


def single_line(value, name):
    if not value or any(c in value for c in "\r\n\x00"):
        raise ValueError(f"{name} must be nonempty and single-line")
    return value


def identifier(value, name):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", value):
        raise ValueError(
            f"{name} must contain only letters, digits, underscores or hyphens"
        )
    return value


def integer(env, name, default, maximum=10000, minimum=1):
    try:
        value = int(env.get(name, str(default)))
        if not minimum <= value <= maximum:
            raise ValueError
        return value
    except ValueError:
        raise ValueError(f"{name} must be between {minimum} and {maximum}") from None


def configuration(env):
    user = identifier(env.get("POSTGRES_USER", "qa_portal"), "POSTGRES_USER")
    database = identifier(env.get("POSTGRES_DB", "qa_portal"), "POSTGRES_DB")
    if database.lower() == "pgbouncer":
        raise ValueError("POSTGRES_DB cannot use the reserved pgbouncer database name")
    password = single_line(env.get("POSTGRES_PASSWORD", ""), "POSTGRES_PASSWORD")
    host = single_line(env.get("PGHOST", "db"), "PGHOST")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", host):
        raise ValueError("PGHOST must be a hostname or IP address")
    port = integer(env, "PGPORT", 5432, 65535)
    size = integer(env, "PGBOUNCER_POOL_SIZE", 20)
    reserve = integer(env, "PGBOUNCER_RESERVE_POOL_SIZE", 5, minimum=0)
    clients = integer(env, "PGBOUNCER_MAX_CLIENT_CONN", 200, maximum=900)
    wait = integer(env, "PGBOUNCER_QUERY_WAIT_TIMEOUT", 30)
    if clients < size + reserve:
        raise ValueError(
            "PGBOUNCER_MAX_CLIENT_CONN must cover the server pool plus reserve"
        )
    # PgBouncer auth-file quoting uses doubled double-quotes, not backslashes.
    users = f'"{user}" "{password.replace(chr(34), chr(34) * 2)}"\n'
    config = f"""[databases]
{database} = host={host} port={port} dbname={database}

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
unix_socket_dir =
auth_type = scram-sha-256
auth_file = {RUNTIME}/users.txt
pool_mode = transaction
default_pool_size = {size}
reserve_pool_size = {reserve}
reserve_pool_timeout = 2
max_db_connections = {size + reserve}
max_client_conn = {clients}
query_wait_timeout = {wait}
server_connect_timeout = 5
server_login_retry = 5
server_idle_timeout = 60
max_prepared_statements = 0
ignore_startup_parameters = extra_float_digits
stats_users = {user}
log_connections = 0
log_disconnections = 0
log_pooler_errors = 1
log_stats = 1
stats_period = 60
"""
    return config, users


def write_configuration(env):
    config, users = configuration(env)
    os.umask(0o077)
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    RUNTIME.chmod(0o700)
    for name, contents in (("pgbouncer.ini", config), ("users.txt", users)):
        path = RUNTIME / name
        path.write_text(contents)
        path.chmod(0o600)
    return RUNTIME / "pgbouncer.ini"


if __name__ == "__main__":
    try:
        path = write_configuration(os.environ)
    except ValueError as exc:
        sys.exit(f"Invalid PgBouncer configuration: {exc}")
    os.execvp("pgbouncer", ["pgbouncer", str(path)])
