"""Read-only Part 4a demo against actual seeded PostgreSQL members."""

import json

from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal, engine
from app.main import app
from app.models import Member, MemberAttribute


def main() -> None:
    if engine.url.get_backend_name() != "postgresql" or engine.url.database != "kindred":
        raise SystemExit("grounded_intro_demo requires seeded PostgreSQL kindred")

    with SessionLocal() as db:
        members = {
            token: db.query(Member).filter(Member.token == token).one()
            for token in ("riverside-member-1", "riverside-member-2", "riverside-member-3")
        }
        requester = members["riverside-member-1"]
        offerer = members["riverside-member-2"]
        private_member = members["riverside-member-3"]

        with TestClient(app) as client:
            for target in (offerer, private_member):
                path = f"/introductions/{requester.id}/{target.id}?reason=business"
                response = client.get(path, headers={"X-Member-Token": requester.token})
                print(f"GET {path}")
                print(f"HTTP {response.status_code}")
                print(json.dumps(response.json(), ensure_ascii=False))
                if response.status_code != 200:
                    raise SystemExit("grounded introduction request failed")
                if target is private_member:
                    if response.json() != {"reason_text": "insufficient basis for an introduction", "used_attributes": []}:
                        raise SystemExit("restricted-only member should not yield a reason")
                    continue

                used = response.json()["used_attributes"]
                if not used or {item["member_id"] for item in used} != {requester.id, offerer.id}:
                    raise SystemExit("missing audit provenance")
                for item in used:
                    attribute = db.get(MemberAttribute, item["id"])
                    if (
                        attribute is None
                        or attribute.restricted
                        or attribute.confidence <= settings.introduction_min_confidence
                        or attribute.text != item["text"]
                        or attribute.text not in response.json()["reason_text"]
                    ):
                        raise SystemExit("reason contains an ineligible or ungrounded attribute")
        print("seeded provenance and privacy checks: passed")


if __name__ == "__main__":
    main()
