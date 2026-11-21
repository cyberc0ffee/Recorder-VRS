"""Administration commands.

python -m app.cli [--config PATH] set-password [--username admin]

The configuration is the one the service uses: --config, else RTSP_RECORDER_CONFIG, else
./config.yaml. A missing file is an error, so the password never ends up in a different database.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from app.core.config import load_settings
from app.core.database import Database
from app.services.auth_service import AuthService


def set_password(username: str | None, config_path: Path) -> int:
    if not config_path.is_file():
        print(f"Configuration file not found: {config_path} (use --config)", file=sys.stderr)
        return 1
    settings = load_settings(config_path)
    print(f"Database: {settings.database_path}")
    database = Database(settings.database_path)
    try:
        database.init_schema()
        username = username or settings.admin_username
        password = getpass.getpass(f"New password for {username}: ")
        if password != getpass.getpass("Repeat it: "):
            print("The passwords do not match", file=sys.stderr)
            return 1
        try:
            AuthService(database, settings).set_password(username, password)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"Password set for {username}; open sessions of this user were closed.")
        return 0
    finally:
        database.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(os.getenv("RTSP_RECORDER_CONFIG", "config.yaml")),
        help="configuration file of the service (default: $RTSP_RECORDER_CONFIG or config.yaml)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    password_parser = commands.add_parser("set-password", help="set or reset a user's password")
    password_parser.add_argument(
        "--username", help="default: admin_username from the configuration"
    )
    args = parser.parse_args(argv)
    if args.command == "set-password":
        return set_password(args.username, args.config)
    return 2


if __name__ == "__main__":
    sys.exit(main())
