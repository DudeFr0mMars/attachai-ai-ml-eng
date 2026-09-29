import math

from sqlalchemy.orm import Session

from app.embeddings import embedding_client
from app.models import Member, MemberAttribute


def build_member_profile_text(member: Member, db: Session) -> str:
    attrs = (
        db.query(MemberAttribute)
        .filter(
            MemberAttribute.member_id == member.id,
            MemberAttribute.club_id == member.club_id,
            MemberAttribute.restricted.is_(False),
        )
        .all()
    )
    return " | ".join(a.text for a in attrs)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def rank_candidates(member: Member, reason: str, db: Session) -> list[dict]:
    candidates = (
        db.query(Member)
        .filter(Member.club_id == member.club_id, Member.id != member.id)
        .all()
    )

    query_vec = embedding_client.embed(build_member_profile_text(member, db))
    results = []
    for candidate in candidates:
        if candidate.profile_embedding is None:
            continue
        # Stored vectors may predate restricted-attribute filtering, so never
        # use them to score a candidate.
        candidate_vec = embedding_client.embed(build_member_profile_text(candidate, db))
        score = cosine_similarity(query_vec, candidate_vec)
        results.append({"member_id": candidate.id, "name": candidate.name, "score": round(float(score), 4)})

    results.sort(key=lambda r: -r["score"])
    return results
