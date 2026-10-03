"""Admin-triggered extraction of seeded or newly received conversation messages."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import get_current_member
from app.db import get_db
from app.llm_client import LLMClient, get_llm_client
from app.models import ConversationMessage, Member, MemberAttribute
from app.services.attribute_extraction import enforce_restricted

router = APIRouter(prefix="/clubs", tags=["extraction"])


class ExtractAttributesIn(BaseModel):
    message_ids: list[int] = Field(min_length=1)


@router.post("/{club_id}/extract-attributes")
def extract_attributes(
    club_id: str,
    payload: ExtractAttributesIn,
    db: Session = Depends(get_db),
    caller: Member = Depends(get_current_member),
    llm_client: LLMClient = Depends(get_llm_client),
):
    if caller.role not in {"admin", "service"} or caller.club_id != club_id:
        raise HTTPException(status_code=403, detail="club admin or service role required")

    outcomes = []
    for message_id in payload.message_ids:
        try:
            # PostgreSQL transaction-level lock serializes concurrent requests for
            # the same message without a schema migration or a unique constraint.
            db.execute(text("SELECT pg_advisory_xact_lock(:message_id)"), {"message_id": message_id})
            message = (
                db.query(ConversationMessage)
                .join(Member, ConversationMessage.member_id == Member.id)
                .filter(
                    ConversationMessage.id == message_id,
                    ConversationMessage.club_id == club_id,
                    Member.club_id == club_id,
                )
                .first()
            )
            if message is None:
                outcomes.append({"message_id": message_id, "status": "not_found", "attribute_count": 0})
                db.rollback()
                continue

            processed_key = MemberAttribute.source_message_id == message.id
            existing = db.query(MemberAttribute).filter(processed_key).all()
            if existing:
                outcomes.append({"message_id": message_id, "status": "already_processed", "attribute_count": len(existing)})
                db.rollback()
                continue

            extracted = enforce_restricted(message.body, llm_client.extract_attributes(message.body))
            for attribute in extracted:
                db.add(MemberAttribute(
                    member_id=message.member_id,
                    club_id=message.club_id,
                    source_message_id=message.id,
                    kind=attribute["kind"],
                    text=attribute["text"],
                    confidence=attribute["confidence"],
                    restricted=attribute["restricted"],
                ))
            db.commit()
            outcomes.append({"message_id": message_id, "status": "processed", "attribute_count": len(extracted)})
        except Exception as exc:
            db.rollback()
            outcomes.append({"message_id": message_id, "status": "failed", "attribute_count": 0, "error": type(exc).__name__})

    return {"results": outcomes}
