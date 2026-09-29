import pytest
from fastapi.testclient import TestClient

from app.embeddings import embedding_client
from app.main import app
from app.models import Club, Member, MemberAttribute
from app.services.matching_service import build_member_profile_text
from app.services.embedding_pipeline import refresh_member_embedding

client = TestClient(app)


def test_rank_candidates_returns_sorted_list(db):
    db.add(Club(id="riverside", name="Riverside"))
    m1 = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    m2 = Member(club_id="riverside", name="B", email="b@example.com", token="tok-b", role="member")
    db.add_all([m1, m2])
    db.commit()

    db.add(MemberAttribute(member_id=m1.id, club_id="riverside", kind="need", text="needs a CFO", confidence=0.9))
    db.add(MemberAttribute(member_id=m2.id, club_id="riverside", kind="offer", text="offers CFO services", confidence=0.9))
    db.commit()

    m2.profile_embedding = embedding_client.embed(build_member_profile_text(m2, db))
    db.commit()

    resp = client.get(
        f"/members/{m1.id}/candidates",
        params={"reason": "business"},
        headers={"X-Member-Token": "tok-a"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["member_id"] == m2.id


def test_profile_text_excludes_restricted_attributes(db):
    db.add(Club(id="riverside", name="Riverside"))
    member = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(member)
    db.flush()
    db.add_all([
        MemberAttribute(member_id=member.id, club_id="riverside", kind="interest", text="plays padel", confidence=0.9),
        MemberAttribute(member_id=member.id, club_id="riverside", kind="context", text="private diagnosis", confidence=0.9, restricted=True),
    ])
    db.commit()

    assert build_member_profile_text(member, db) == "plays padel"


def test_ranking_ignores_preexisting_embedding_from_restricted_data(db):
    db.add(Club(id="riverside", name="Riverside"))
    requester = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    candidate = Member(club_id="riverside", name="B", email="b@example.com", token="tok-b", role="member")
    db.add_all([requester, candidate])
    db.flush()
    db.add_all([
        MemberAttribute(member_id=requester.id, club_id="riverside", kind="interest", text="plays padel", confidence=0.9),
        MemberAttribute(member_id=candidate.id, club_id="riverside", kind="context", text="plays padel", confidence=0.9, restricted=True),
    ])
    candidate.profile_embedding = embedding_client.embed("plays padel")
    db.commit()

    resp = client.get(
        f"/members/{requester.id}/candidates",
        params={"reason": "shared interests"},
        headers={"X-Member-Token": "tok-a"},
    )

    assert resp.status_code == 200
    assert resp.json()[0]["member_id"] == candidate.id
    assert resp.json()[0]["score"] == 0.0


def test_refresh_embedding_replaces_restricted_legacy_vector(db):
    db.add(Club(id="riverside", name="Riverside"))
    member = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(member)
    db.flush()
    db.add_all([
        MemberAttribute(member_id=member.id, club_id="riverside", kind="interest", text="plays padel", confidence=0.9),
        MemberAttribute(member_id=member.id, club_id="riverside", kind="context", text="private diagnosis", confidence=0.9, restricted=True),
    ])
    member.profile_embedding = embedding_client.embed("private diagnosis")
    db.commit()

    refresh_member_embedding(member, db)

    assert list(member.profile_embedding) == pytest.approx(embedding_client.embed("plays padel"))
