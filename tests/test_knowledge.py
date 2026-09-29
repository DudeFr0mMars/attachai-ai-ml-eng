from fastapi.testclient import TestClient

from app.embeddings import embedding_client
from app.main import app
from app.models import Club, KnowledgeChunk, Member

client = TestClient(app)


def test_query_own_club_returns_results(db):
    db.add(Club(id="riverside", name="Riverside"))
    db.add(Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member"))
    db.add(
        KnowledgeChunk(
            club_id="riverside",
            title="Fees",
            body="Guest fees are $50.",
            embedding=embedding_client.embed("Guest fees are $50."),
        )
    )
    db.commit()

    resp = client.get(
        "/clubs/riverside/knowledge/query",
        params={"q": "guest fees"},
        headers={"X-Member-Token": "tok-a"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_query_rejects_non_member(db):
    db.add(Club(id="riverside", name="Riverside"))
    db.add(Club(id="oakhurst", name="Oakhurst"))
    db.add(Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member"))
    db.commit()

    resp = client.get(
        "/clubs/oakhurst/knowledge/query",
        params={"q": "guest fees"},
        headers={"X-Member-Token": "tok-a"},
    )
    assert resp.status_code == 403


def test_query_never_returns_other_club_chunks(db):
    db.add_all([Club(id="riverside", name="Riverside"), Club(id="oakhurst", name="Oakhurst")])
    db.add(Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member"))
    db.add_all(
        [
            KnowledgeChunk(
                club_id="riverside",
                title="Riverside rules",
                body="Riverside opens at seven.",
                embedding=embedding_client.embed("Riverside opens at seven."),
            ),
            KnowledgeChunk(
                club_id="oakhurst",
                title="Private Oakhurst policy",
                body="Oakhurst guest fees are $75.",
                embedding=embedding_client.embed("Oakhurst guest fees are $75."),
            ),
        ]
    )
    db.commit()

    resp = client.get(
        "/clubs/riverside/knowledge/query",
        params={"q": "Oakhurst guest fees are $75."},
        headers={"X-Member-Token": "tok-a"},
    )

    assert resp.status_code == 200
    assert [chunk["title"] for chunk in resp.json()] == ["Riverside rules"]
