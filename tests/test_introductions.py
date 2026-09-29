from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.models import Club, Member, MemberAttribute

client = TestClient(app)


def test_generate_reason_includes_attributes(db):
    db.add(Club(id="riverside", name="Riverside"))
    m1 = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    m2 = Member(club_id="riverside", name="B", email="b@example.com", token="tok-b", role="member")
    db.add_all([m1, m2])
    db.commit()

    db.add(MemberAttribute(member_id=m1.id, club_id="riverside", kind="need", text="needs a CFO", confidence=0.9))
    db.add(MemberAttribute(member_id=m2.id, club_id="riverside", kind="offer", text="offers CFO services", confidence=0.9))
    db.commit()

    resp = client.get(
        f"/introductions/{m1.id}/{m2.id}",
        params={"reason": "business"},
        headers={"X-Member-Token": "tok-a"},
    )
    assert resp.status_code == 200
    assert "CFO" in resp.json()["reason_text"]


@pytest.mark.parametrize("foreign_side", ["a", "b"])
def test_generate_reason_rejects_cross_club_members(db, foreign_side):
    db.add_all([Club(id="riverside", name="Riverside"), Club(id="oakhurst", name="Oakhurst")])
    own = Member(club_id="riverside", name="Own", email="own@example.com", token="tok-own", role="member")
    foreign = Member(club_id="oakhurst", name="Foreign", email="foreign@example.com", token="tok-foreign", role="member")
    db.add_all([own, foreign])
    db.flush()
    db.add(MemberAttribute(member_id=foreign.id, club_id="oakhurst", kind="context", text="private health detail", confidence=0.9, restricted=True))
    db.commit()

    ids = (foreign.id, own.id) if foreign_side == "a" else (own.id, foreign.id)
    resp = client.get(f"/introductions/{ids[0]}/{ids[1]}", params={"reason": "business"}, headers={"X-Member-Token": "tok-own"})

    assert resp.status_code == 404
    assert "private health detail" not in resp.text


def test_generate_reason_excludes_restricted_and_low_confidence_attributes(db):
    db.add(Club(id="riverside", name="Riverside"))
    own = Member(club_id="riverside", name="Own", email="own@example.com", token="tok-own", role="member")
    peer = Member(club_id="riverside", name="Peer", email="peer@example.com", token="tok-peer", role="member")
    db.add_all([own, peer])
    db.flush()
    db.add_all([
        MemberAttribute(member_id=own.id, club_id="riverside", kind="need", text="needs a CFO", confidence=0.9),
        MemberAttribute(member_id=peer.id, club_id="riverside", kind="offer", text="offers CFO services", confidence=0.9),
        MemberAttribute(member_id=peer.id, club_id="riverside", kind="context", text="private diagnosis", confidence=0.9, restricted=True),
        MemberAttribute(member_id=peer.id, club_id="riverside", kind="need", text="uncertain future plan", confidence=0.3),
    ])
    db.commit()

    resp = client.get(f"/introductions/{own.id}/{peer.id}", params={"reason": "business"}, headers={"X-Member-Token": "tok-own"})

    assert resp.status_code == 200
    assert "offers CFO services" in resp.json()["reason_text"]
    assert "private diagnosis" not in resp.json()["reason_text"]
    assert "uncertain future plan" not in resp.json()["reason_text"]


def test_generate_reason_requires_eligible_attributes_on_both_sides(db):
    db.add(Club(id="riverside", name="Riverside"))
    own = Member(club_id="riverside", name="Own", email="own@example.com", token="tok-own", role="member")
    peer = Member(club_id="riverside", name="Peer", email="peer@example.com", token="tok-peer", role="member")
    db.add_all([own, peer])
    db.flush()
    db.add(MemberAttribute(member_id=peer.id, club_id="riverside", kind="context", text="private diagnosis", confidence=0.9, restricted=True))
    db.commit()

    resp = client.get(f"/introductions/{own.id}/{peer.id}", params={"reason": "business"}, headers={"X-Member-Token": "tok-own"})

    assert resp.status_code == 200
    assert resp.json() == {"reason_text": "insufficient basis for an introduction"}
