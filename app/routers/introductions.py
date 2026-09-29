from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_member
from app.config import settings
from app.db import get_db
from app.models import Member, MemberAttribute

router = APIRouter(prefix="/introductions", tags=["introductions"])


@router.get("/{member_a_id}/{member_b_id}")
def generate_reason(
    member_a_id: int,
    member_b_id: int,
    reason: str,
    db: Session = Depends(get_db),
    member: Member = Depends(get_current_member),
):
    for target_id in (member_a_id, member_b_id):
        target = db.query(Member.id).filter(Member.id == target_id, Member.club_id == member.club_id).first()
        if target is None:
            raise HTTPException(status_code=404, detail="member not found")

    def eligible_attributes(target_id: int) -> list[MemberAttribute]:
        return (
            db.query(MemberAttribute)
            .filter(
                MemberAttribute.member_id == target_id,
                MemberAttribute.club_id == member.club_id,
                MemberAttribute.restricted.is_(False),
                MemberAttribute.confidence >= settings.introduction_min_confidence,
            )
            .all()
        )

    attrs_a = eligible_attributes(member_a_id)
    attrs_b = eligible_attributes(member_b_id)

    if not attrs_a or not attrs_b:
        return {"reason_text": "insufficient basis for an introduction"}

    a_text = "; ".join(a.text for a in attrs_a)
    b_text = "; ".join(b.text for b in attrs_b)
    return {"reason_text": f"Because {a_text} and {b_text} — a good {reason} match."}
