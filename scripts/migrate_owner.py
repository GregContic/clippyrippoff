from __future__ import annotations

import getpass
import json
import os
from pathlib import Path

from backend.db import DatabaseConfigurationError
from backend.services.auth import AuthenticationError, auth_repository, normalize_email


def main() -> int:
    root = Path(os.getenv("AUTH_DATA_DIR", "processing/auth"))
    owner_path = root / "users.json"
    if not owner_path.exists():
        print(f"No filesystem owner file found at {owner_path}. Nothing was migrated.")
        return 1
    try:
        payload = json.loads(owner_path.read_text(encoding="utf-8"))
        owner = payload.get("owner")
        if not isinstance(owner, dict):
            raise ValueError("owner record is missing")
        legacy_username = str(owner.get("username", "")).strip()
        email = normalize_email(input(f"Migration email [{legacy_username}]: ").strip() or legacy_username)
    except (OSError, ValueError, AuthenticationError) as exc:
        print(f"Unable to read a valid filesystem owner: {exc}")
        return 1
    password = getpass.getpass("New database password (12+ characters): ")
    confirmation = getpass.getpass("Confirm database password: ")
    if password != confirmation:
        print("Passwords do not match.")
        return 1
    try:
        auth_repository.bootstrap(email, password)
    except (AuthenticationError, DatabaseConfigurationError) as exc:
        print(f"Unable to migrate owner: {exc}")
        return 1
    print(f"Migrated the owner account to '{email}'. Existing filesystem auth data was preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
