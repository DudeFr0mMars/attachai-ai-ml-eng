from fastapi.testclient import TestClient

from app.main import app
from app.models import Club, Member
from app.services.payment_mock import payment_mock_client

client = TestClient(app)


def test_session_books_end_to_end(db):
    db.add(Club(id="riverside", name="Riverside"))
    m = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(m)
    db.commit()

    resp = client.post("/sessions", headers={"X-Member-Token": "tok-a"})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    resp = client.post(
        f"/sessions/{session_id}/turn",
        json={"intent": "book", "party_size": 2},
        headers={"X-Member-Token": "tok-a"},
    )
    assert resp.json()["status"] == "awaiting_confirmation"

    resp = client.post(
        f"/sessions/{session_id}/turn",
        json={"intent": "affirm", "amount_cents": 4000},
        headers={"X-Member-Token": "tok-a"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"


def test_refund_dispute_escalates(db):
    db.add(Club(id="riverside", name="Riverside"))
    m = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(m)
    db.commit()

    session_id = client.post("/sessions", headers={"X-Member-Token": "tok-a"}).json()["session_id"]

    resp = client.post(
        f"/sessions/{session_id}/turn",
        json={"intent": "refund_dispute"},
        headers={"X-Member-Token": "tok-a"},
    )
    assert resp.json()["status"] == "escalated"


def test_session_retry_after_crash_does_not_charge_twice(db):
    db.add(Club(id="riverside", name="Riverside"))
    member = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(member)
    db.commit()
    headers = {"X-Member-Token": "tok-a"}
    session_id = client.post("/sessions", headers=headers).json()["session_id"]
    client.post(f"/sessions/{session_id}/turn", json={"intent": "book", "party_size": 2}, headers=headers)

    before = len(payment_mock_client.charge_log)
    first = client.post(f"/sessions/{session_id}/turn", json={"intent": "affirm", "amount_cents": 4000, "simulate_crash": True}, headers=headers)
    second = client.post(f"/sessions/{session_id}/turn", json={"intent": "affirm", "amount_cents": 4000}, headers=headers)

    assert first.status_code == 500
    assert second.status_code == 200
    assert second.json()["status"] == "confirmed"
    assert len(payment_mock_client.charge_log) - before == 1


def test_confirmed_session_cannot_reopen_and_recharge(db):
    db.add(Club(id="riverside", name="Riverside"))
    member = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(member)
    db.commit()
    headers = {"X-Member-Token": "tok-a"}
    session_id = client.post("/sessions", headers=headers).json()["session_id"]
    client.post(f"/sessions/{session_id}/turn", json={"intent": "book", "party_size": 2}, headers=headers)

    before = len(payment_mock_client.charge_log)
    first = client.post(f"/sessions/{session_id}/turn", json={"intent": "affirm", "amount_cents": 4000}, headers=headers)
    client.post(f"/sessions/{session_id}/turn", json={"intent": "book", "party_size": 3}, headers=headers)
    replay = client.post(f"/sessions/{session_id}/turn", json={"intent": "affirm", "amount_cents": 4000}, headers=headers)

    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    assert len(payment_mock_client.charge_log) - before == 1


def test_session_timeout_replay_does_not_recharge(db):
    db.add(Club(id="riverside", name="Riverside"))
    member = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(member)
    db.commit()
    headers = {"X-Member-Token": "tok-a"}
    session_id = client.post("/sessions", headers=headers).json()["session_id"]
    client.post(f"/sessions/{session_id}/turn", json={"intent": "book", "party_size": 2}, headers=headers)

    before = len(payment_mock_client.charge_log)
    payload = {"intent": "affirm", "amount_cents": 999999}
    first = client.post(f"/sessions/{session_id}/turn", json=payload, headers=headers)
    second = client.post(f"/sessions/{session_id}/turn", json=payload, headers=headers)

    assert first.status_code == second.status_code == 504
    assert len(payment_mock_client.charge_log) - before == 1
    assert client.get(f"/sessions/{session_id}", headers=headers).json()["awaiting_confirmation"] is True


def test_session_crash_retry_with_different_amount_is_rejected(db):
    db.add(Club(id="riverside", name="Riverside"))
    member = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(member)
    db.commit()
    headers = {"X-Member-Token": "tok-a"}
    session_id = client.post("/sessions", headers=headers).json()["session_id"]
    client.post(f"/sessions/{session_id}/turn", json={"intent": "book", "party_size": 2}, headers=headers)

    before = len(payment_mock_client.charge_log)
    first = client.post(f"/sessions/{session_id}/turn", json={"intent": "affirm", "amount_cents": 4000, "simulate_crash": True}, headers=headers)
    second = client.post(f"/sessions/{session_id}/turn", json={"intent": "affirm", "amount_cents": 5000}, headers=headers)

    assert first.status_code == 500
    assert second.status_code == 409
    assert len(payment_mock_client.charge_log) - before == 1


def test_direct_confirmation_of_session_booking_does_not_recharge(db):
    db.add(Club(id="riverside", name="Riverside"))
    member = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(member)
    db.commit()
    headers = {"X-Member-Token": "tok-a"}
    session_id = client.post("/sessions", headers=headers).json()["session_id"]
    client.post(f"/sessions/{session_id}/turn", json={"intent": "book", "party_size": 2}, headers=headers)
    confirmed = client.post(f"/sessions/{session_id}/turn", json={"intent": "affirm", "amount_cents": 4000}, headers=headers)

    before = len(payment_mock_client.charge_log)
    response = client.post(f"/bookings/{confirmed.json()['booking_id']}/confirm-payment", json={"amount_cents": 4000}, headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert len(payment_mock_client.charge_log) == before


def test_session_retry_after_process_state_loss_never_recharges(db):
    db.add(Club(id="riverside", name="Riverside"))
    member = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(member)
    db.commit()
    headers = {"X-Member-Token": "tok-a"}
    session_id = client.post("/sessions", headers=headers).json()["session_id"]
    client.post(f"/sessions/{session_id}/turn", json={"intent": "book", "party_size": 2}, headers=headers)

    first = client.post(f"/sessions/{session_id}/turn", json={"intent": "affirm", "amount_cents": 4000, "simulate_crash": True}, headers=headers)
    assert first.status_code == 500
    assert payment_mock_client.charge_log == [4000]

    payment_mock_client.reset()
    replay = client.post(f"/sessions/{session_id}/turn", json={"intent": "affirm", "amount_cents": 4000}, headers=headers)

    assert replay.status_code == 504
    assert payment_mock_client.charge_log == []


def test_pending_session_booking_cannot_be_charged_directly(db):
    db.add(Club(id="riverside", name="Riverside"))
    member = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(member)
    db.commit()
    headers = {"X-Member-Token": "tok-a"}
    session_id = client.post("/sessions", headers=headers).json()["session_id"]
    client.post(f"/sessions/{session_id}/turn", json={"intent": "book", "party_size": 2}, headers=headers)
    client.post(f"/sessions/{session_id}/turn", json={"intent": "affirm", "amount_cents": 4000, "simulate_crash": True}, headers=headers)
    booking_id = client.get(f"/sessions/{session_id}", headers=headers).json()["booking_id"]

    before = len(payment_mock_client.charge_log)
    response = client.post(f"/bookings/{booking_id}/confirm-payment", json={"amount_cents": 4000}, headers=headers)

    assert response.status_code == 409
    assert len(payment_mock_client.charge_log) == before
