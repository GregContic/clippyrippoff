from __future__ import annotations

import getpass

from backend.db import DatabaseConfigurationError
from backend.services.auth import AuthenticationError, auth_repository


def main() -> int:
    email = input("Admin email: ").strip()
    password = getpass.getpass("Admin password (12+ characters): ")
    confirmation = getpass.getpass("Confirm admin password: ")
    if password != confirmation:
        print("Passwords do not match.")
        return 1
    try:
        principal = auth_repository.bootstrap(email, password)
    except (AuthenticationError, DatabaseConfigurationError) as exc:
        print(f"Unable to create admin: {exc}")
        return 1
    print(f"Created admin account '{principal.email or principal.username}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
