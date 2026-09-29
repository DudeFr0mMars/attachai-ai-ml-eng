"""Two-pass real-API extraction demo on seeded PostgreSQL without altering seed rows."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import SessionLocal, engine
from app.main import app
from app.models import ConversationMessage, Member, MemberAttribute
from app.services.matching_service import build_member_profile_text


def main() -> None:
    if engine.url.get_backend_name() != "postgresql" or engine.url.database != "kindred":
        raise SystemExit("extraction_demo requires seeded PostgreSQL kindred")

    records = json.loads((Path(__file__).resolve().parents[1] / "eval" / "golden_set.json").read_text())
    with SessionLocal() as db:
        member = db.query(Member).filter(Member.token == "riverside-member-5").one()
        messages = []
        for record in records:
            message = db.query(ConversationMessage).filter(
                ConversationMessage.club_id == member.club_id,
                ConversationMessage.member_id == member.id,
                ConversationMessage.body == record["message"],
            ).first()
            if message is None:
                message = ConversationMessage(
                    club_id=member.club_id,
                    member_id=member.id,
                    body=record["message"],
                )
                db.add(message)
                db.flush()
            messages.append(message)
        db.commit()
        message_ids = [message.id for message in messages]

    with TestClient(app) as client:
        for pass_number in (1, 2):
            response = client.post(
                "/clubs/riverside/extract-attributes",
                json={"message_ids": message_ids},
                headers={"X-Member-Token": "riverside-admin"},
            )
            print(f"pass {pass_number}: HTTP {response.status_code} {response.json()}")
            if response.status_code != 200:
                raise SystemExit("extraction batch failed")

    with SessionLocal() as db:
        rows = db.query(MemberAttribute).filter(MemberAttribute.source_message_id.in_(message_ids)).all()
        print(f"persisted attributes={len(rows)} restricted={sum(row.restricted for row in rows)}")
        member = db.query(Member).filter(Member.token == "riverside-member-5").one()
        profile = build_member_profile_text(member, db)
        if "therapy" in profile.lower():
            raise SystemExit("restricted therapy data entered matching profile")
        print("restricted therapy excluded from matching profile: True")


if __name__ == "__main__":
    main()
