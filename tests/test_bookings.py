import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Booking, Club, Member, PaymentAttempt
from app.services.payment_mock import payment_mock_client

client = TestClient(app)


def test_confirm_payment_succeeds(db):
    db.add(Club(id="riverside", name="Riverside"))
    m = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(m)
    db.commit()

    booking = Booking(member_id=m.id, club_id="riverside", description="Dinner", amount_cents=5000, status="pending")
    db.add(booking)
    db.commit()

    resp = client.post(
        f"/bookings/{booking.id}/confirm-payment",
        json={"amount_cents": 5000},
        headers={"X-Member-Token": "tok-a"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "succeeded"
    assert db.get(PaymentAttempt, resp.json()["attempt_id"]).amount_cents == booking.amount_cents


def test_confirm_payment_replay_does_not_charge_twice(db):
    db.add(Club(id="riverside", name="Riverside"))
    member = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(member)
    db.flush()
    booking = Booking(member_id=member.id, club_id="riverside", description="Dinner", amount_cents=5000, status="pending")
    db.add(booking)
    db.commit()

    before = len(payment_mock_client.charge_log)
    path = f"/bookings/{booking.id}/confirm-payment"
    headers = {"X-Member-Token": "tok-a"}
    first = client.post(path, json={"amount_cents": 5000}, headers=headers)
    second = client.post(path, json={"amount_cents": 5000}, headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(payment_mock_client.charge_log) - before == 1


def test_confirm_payment_timeout_replay_does_not_recharge(db):
    db.add(Club(id="riverside", name="Riverside"))
    member = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(member)
    db.flush()
    booking = Booking(member_id=member.id, club_id="riverside", description="Dinner", amount_cents=999999, status="pending")
    db.add(booking)
    db.commit()

    before = len(payment_mock_client.charge_log)
    path = f"/bookings/{booking.id}/confirm-payment"
    headers = {"X-Member-Token": "tok-a"}
    first = client.post(path, json={"amount_cents": 999999}, headers=headers)
    second = client.post(path, json={"amount_cents": 999999}, headers=headers)

    assert first.status_code == second.status_code == 504
    assert len(payment_mock_client.charge_log) - before == 1


@pytest.mark.parametrize("submitted_amount", [0, 1, 9000])
def test_confirm_payment_rejects_wrong_amount_without_charge(db, submitted_amount):
    db.add(Club(id="riverside", name="Riverside"))
    member = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(member)
    db.flush()
    booking = Booking(member_id=member.id, club_id="riverside", description="Dinner", amount_cents=8000, status="pending")
    db.add(booking)
    db.commit()

    before = len(payment_mock_client.charge_log)
    response = client.post(f"/bookings/{booking.id}/confirm-payment", json={"amount_cents": submitted_amount}, headers={"X-Member-Token": "tok-a"})

    assert response.status_code == 400
    assert booking.status == "pending"
    assert db.query(PaymentAttempt).filter(PaymentAttempt.booking_id == booking.id).count() == 0
    assert len(payment_mock_client.charge_log) == before


def test_confirmed_booking_rejects_different_amount_on_replay(db):
    db.add(Club(id="riverside", name="Riverside"))
    member = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(member)
    db.flush()
    booking = Booking(member_id=member.id, club_id="riverside", description="Dinner", amount_cents=8000, status="pending")
    db.add(booking)
    db.commit()
    headers = {"X-Member-Token": "tok-a"}
    client.post(f"/bookings/{booking.id}/confirm-payment", json={"amount_cents": 8000}, headers=headers)

    before = len(payment_mock_client.charge_log)
    replay = client.post(f"/bookings/{booking.id}/confirm-payment", json={"amount_cents": 1}, headers=headers)

    assert replay.status_code == 400
    assert len(payment_mock_client.charge_log) == before


def test_booking_retry_after_process_state_loss_never_recharges(db, monkeypatch):
    db.add(Club(id="riverside", name="Riverside"))
    member = Member(club_id="riverside", name="A", email="a@example.com", token="tok-a", role="member")
    db.add(member)
    db.flush()
    booking = Booking(member_id=member.id, club_id="riverside", description="Dinner", amount_cents=5000, status="pending")
    db.add(booking)
    db.commit()

    original_charge = payment_mock_client.charge

    def crash_after_charge(*args, **kwargs):
        original_charge(*args, **kwargs)
        raise RuntimeError("simulated process crash")

    path = f"/bookings/{booking.id}/confirm-payment"
    headers = {"X-Member-Token": "tok-a"}
    with monkeypatch.context() as patch:
        patch.setattr(payment_mock_client, "charge", crash_after_charge)
        with pytest.raises(RuntimeError, match="simulated process crash"):
            client.post(path, json={"amount_cents": 5000}, headers=headers)

    payment_mock_client.reset()
    replay = client.post(path, json={"amount_cents": 5000}, headers=headers)

    assert replay.status_code == 504
    assert payment_mock_client.charge_log == []
