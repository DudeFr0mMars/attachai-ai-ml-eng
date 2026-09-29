"""Read-only introduction privacy trace against the seeded PostgreSQL database.

Run with DATABASE_URL pointing at the seeded kindred database, not kindred_test.
"""

import json

from fastapi.testclient import TestClient

from app.db import SessionLocal, engine
from app.main import app
from app.models import Member, MemberAttribute


def main() -> None:
    if engine.url.get_backend_name() != "postgresql" or engine.url.database != "kindred":
        raise SystemExit("review_trace requires the seeded PostgreSQL kindred database")

    with SessionLocal() as db:
        caller = db.query(Member).filter(Member.token == "riverside-member-1").one()
        cross_club = db.query(Member).filter(Member.token == "oakhurst-member-4").one()
        same_club_private = db.query(Member).filter(Member.token == "riverside-member-3").one()
        for member in (cross_club, same_club_private):
            exists = db.query(MemberAttribute.id).filter(
                MemberAttribute.member_id == member.id,
                MemberAttribute.club_id == member.club_id,
                MemberAttribute.restricted.is_(True),
            ).first()
            if not exists:
                raise SystemExit(f"seeded restricted attribute missing for {member.token}")

    with TestClient(app) as client:
        for target in (cross_club, same_club_private):
            path = f"/introductions/{caller.id}/{target.id}?reason=business"
            response = client.get(path, headers={"X-Member-Token": caller.token})
            print(f"GET {path}")
            print(f"X-Member-Token: {caller.token}")
            print(f"HTTP {response.status_code}")
            print(json.dumps(response.json(), ensure_ascii=False))
            if target is cross_club and response.status_code != 404:
                raise SystemExit("cross-club introduction was not rejected")
            if target is same_club_private and (
                response.status_code != 200
                or "insufficient" not in response.json().get("reason_text", "").lower()
            ):
                raise SystemExit("restricted-only member influenced introduction")

        path = f"/members/{caller.id}/candidates?reason=business"
        response = client.get(path, headers={"X-Member-Token": caller.token})
        print(f"GET {path}")
        print(f"X-Member-Token: {caller.token}")
        print(f"HTTP {response.status_code}")
        print(json.dumps(response.json(), ensure_ascii=False))
        if response.status_code != 200:
            raise SystemExit("seeded matching request failed")
        candidates = response.json()
        restricted_only = next((c for c in candidates if c["member_id"] == same_club_private.id), None)
        if restricted_only is None or restricted_only["score"] != 0:
            raise SystemExit("restricted-only member affected matching score")
        if any(c["member_id"] == cross_club.id for c in candidates):
            raise SystemExit("cross-club member appeared in matching")


if __name__ == "__main__":
    main()
