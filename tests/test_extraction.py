from fastapi.testclient import TestClient
import httpx

from app.config import settings
from app.main import app
from app.models import Club, ConversationMessage, Member, MemberAttribute
from app.services.attribute_extraction import ExtractedAttribute, OpenAIAttributeExtractor, get_attribute_extractor

client = TestClient(app)


class FakeExtractor:
    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = []

    def extract(self, body):
        self.calls.append(body)
        value = self.outputs[body]
        if isinstance(value, Exception):
            raise value
        return value


def seed_messages(db, bodies):
    db.add_all([Club(id="riverside", name="Riverside"), Club(id="oakhurst", name="Oakhurst")])
    admin = Member(club_id="riverside", name="Admin", email="admin@example.com", token="admin", role="admin")
    member = Member(club_id="riverside", name="Member", email="member@example.com", token="member", role="member")
    other_admin = Member(club_id="oakhurst", name="Other Admin", email="other@example.com", token="other", role="admin")
    db.add_all([admin, member, other_admin])
    db.flush()
    messages = [ConversationMessage(club_id="riverside", member_id=member.id, body=body) for body in bodies]
    db.add_all(messages)
    db.commit()
    return member, messages


def test_happy_path_restricted_flag_and_idempotency(db):
    member, messages = seed_messages(db, ["I need a fractional CFO", "I've been in therapy"])
    fake = FakeExtractor({
        messages[0].body: [ExtractedAttribute(kind="need", text="needs a fractional CFO", confidence=0.95, restricted=False)],
        # A mistaken model flag must not put explicit therapy data into matching.
        messages[1].body: [ExtractedAttribute(kind="context", text="has been in therapy", confidence=0.95, restricted=False)],
    })
    app.dependency_overrides[get_attribute_extractor] = lambda: fake
    try:
        payload = {"message_ids": [m.id for m in messages]}
        first = client.post("/clubs/riverside/extract-attributes", json=payload, headers={"X-Member-Token": "admin"})
        second = client.post("/clubs/riverside/extract-attributes", json=payload, headers={"X-Member-Token": "admin"})
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200
    assert [r["status"] for r in first.json()["results"]] == ["processed", "processed"]
    assert [r["status"] for r in second.json()["results"]] == ["already_processed", "already_processed"]
    assert len(fake.calls) == 2
    attrs = db.query(MemberAttribute).filter(MemberAttribute.member_id == member.id).order_by(MemberAttribute.source_message_id).all()
    assert len(attrs) == 2
    assert [a.restricted for a in attrs] == [False, True]
    assert all(a.club_id == "riverside" for a in attrs)


def test_batch_continues_after_message_three_fails(db):
    _, messages = seed_messages(db, ["one", "two", "three", "four", "five"])
    fake = FakeExtractor({
        body: RuntimeError("permanent LLM failure") if body == "three" else [
            ExtractedAttribute(kind="interest", text=f"interest {body}", confidence=0.9, restricted=False)
        ]
        for body in ["one", "two", "three", "four", "five"]
    })
    app.dependency_overrides[get_attribute_extractor] = lambda: fake
    try:
        response = client.post(
            "/clubs/riverside/extract-attributes",
            json={"message_ids": [m.id for m in messages]},
            headers={"X-Member-Token": "admin"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [r["status"] for r in response.json()["results"]] == ["processed", "processed", "failed", "processed", "processed"]
    assert fake.calls == ["one", "two", "three", "four", "five"]
    assert db.query(MemberAttribute).filter(MemberAttribute.source_message_id == messages[2].id).count() == 0
    assert db.query(MemberAttribute).filter(MemberAttribute.source_message_id == messages[3].id).count() == 1


def test_authorization_and_cross_club_message_id(db):
    _, messages = seed_messages(db, ["hello"])
    other = db.query(Member).filter(Member.token == "other").one()
    foreign = ConversationMessage(club_id="oakhurst", member_id=other.id, body="private")
    db.add(foreign)
    db.commit()
    fake = FakeExtractor({"hello": [], "private": []})
    app.dependency_overrides[get_attribute_extractor] = lambda: fake
    try:
        denied_member = client.post("/clubs/riverside/extract-attributes", json={"message_ids": [messages[0].id]}, headers={"X-Member-Token": "member"})
        denied_foreign_admin = client.post("/clubs/riverside/extract-attributes", json={"message_ids": [messages[0].id]}, headers={"X-Member-Token": "other"})
        missing = client.post("/clubs/riverside/extract-attributes", json={"message_ids": [foreign.id]}, headers={"X-Member-Token": "admin"})
    finally:
        app.dependency_overrides.clear()

    assert denied_member.status_code == 403
    assert denied_foreign_admin.status_code == 403
    assert missing.json()["results"][0]["status"] == "not_found"
    assert fake.calls == []


def test_transient_openai_failures_retry_then_succeed(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    calls = []
    delays = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if len(calls) < 3:
            return httpx.Response(429 if len(calls) == 1 else 503)
        return httpx.Response(200, json={
            "status": "completed",
            "output": [{"content": [{"type": "output_text", "text": '{"attributes": [{"kind": "context", "text": "has been in therapy", "confidence": 0.9, "restricted": false}]}'}]}],
        })

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr("app.services.attribute_extraction.time.sleep", delays.append)
    monkeypatch.setattr("app.services.attribute_extraction.random.uniform", lambda *_: 0)
    attributes = OpenAIAttributeExtractor().extract("I've been in therapy")

    assert len(calls) == 3
    assert delays == [0.5, 1.0]
    assert attributes[0].restricted is True
    assert all(call[0] == "https://api.openai.com/v1/responses" for call in calls)
