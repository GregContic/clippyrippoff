from __future__ import annotations

import getpass

from backend.services.auth import AuthenticationError, auth_repository


def main() -> int:
    username = input("Owner username: ").strip()
    password = getpass.getpass("Owner password (12+ characters): ")
    confirmation = getpass.getpass("Confirm owner password: ")
    if password != confirmation:
        print("Passwords do not match.")
        return 1
    try:
        principal = auth_repository.bootstrap(username, password)
    except AuthenticationError as exc:
        print(f"Unable to create owner: {exc}")
        return 1
    print(f"Created owner account '{principal.username}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
