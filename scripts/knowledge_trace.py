"""Read-only reproduction of the knowledge boundary using seeded data.

Run with the application's normal DATABASE_URL against a seeded database.
"""

import json

from fastapi.testclient import TestClient

from app.main import app


def main() -> None:
    path = "/clubs/riverside/knowledge/query?q=guest%20fees"
    with TestClient(app) as client:
        response = client.get(path, headers={"X-Member-Token": "riverside-member-1"})
    print(f"GET {path}")
    print("X-Member-Token: riverside-member-1")
    print(f"HTTP {response.status_code}")
    print(json.dumps(response.json(), ensure_ascii=False))


if __name__ == "__main__":
    main()
