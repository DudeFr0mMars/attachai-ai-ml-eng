from sqlalchemy.orm import Session as DbSession

from app.models import Booking, ConversationSession, PaymentAttempt
from app.services.payment_mock import PaymentConflictError, PaymentTimeoutError, payment_mock_client


class SimulatedCrash(Exception):
    """Lets a caller reproduce a process crash between the charge succeeding
    and the session/booking being persisted — the same ambiguous-outcome
    scenario as a real payment-provider timeout, but deterministic to trigger."""


def advance_turn(session: ConversationSession, intent: str, payload: dict, db: DbSession) -> dict:
    if intent == "refund_dispute":
        session.status = "escalated"
        db.commit()
        return {"status": "escalated"}

    if session.status == "confirmed":
        return {"status": "confirmed", "booking_id": session.booking_id}
    if session.status == "escalated":
        return {"status": "escalated"}

    if intent == "book":
        party_size = payload.get("party_size")
        if party_size is not None:
            session.party_size = party_size
        if session.party_size is not None:
            session.awaiting_confirmation = True
        db.commit()
        return {
            "status": "awaiting_confirmation" if session.awaiting_confirmation else "need_party_size",
            "party_size": session.party_size,
        }

    if intent == "affirm" and session.awaiting_confirmation:
        amount_cents = payload.get("amount_cents", 0)
        key = f"session:{session.id}"

        is_new_attempt = session.booking_id is None
        if is_new_attempt:
            booking = Booking(
                member_id=session.member_id,
                club_id=session.club_id,
                description="Session-confirmed booking",
                amount_cents=amount_cents,
                status="pending",
            )
            db.add(booking)
            db.flush()
            attempt = PaymentAttempt(
                booking_id=booking.id,
                idempotency_key=key,
                amount_cents=amount_cents,
                status="initiated",
            )
            db.add(attempt)
            session.booking_id = booking.id
            db.commit()
        else:
            booking = db.get(Booking, session.booking_id)
            attempt = (
                db.query(PaymentAttempt)
                .filter(PaymentAttempt.booking_id == booking.id, PaymentAttempt.idempotency_key == key)
                .first()
            )
            if attempt is None or attempt.amount_cents != amount_cents:
                raise PaymentConflictError("payment amount conflicts with prior attempt")
            if attempt.status == "succeeded":
                session.status = "confirmed"
                session.awaiting_confirmation = False
                db.commit()
                return {"status": "confirmed", "booking_id": booking.id}
            if attempt.status == "failed":
                session.status = "escalated"
                session.awaiting_confirmation = False
                db.commit()
                return {"status": "escalated"}

        try:
            result = (
                payment_mock_client.charge(amount_cents, idempotency_key=key)
                if is_new_attempt
                else payment_mock_client.lookup(amount_cents, key)
            )
        except PaymentTimeoutError:
            attempt.status = "unknown"
            db.commit()
            raise

        if result is None:
            raise PaymentTimeoutError("payment outcome requires reconciliation")

        if payload.get("simulate_crash"):
            raise SimulatedCrash("process died after the charge, before the session/booking were saved")

        attempt.status = result.status
        if result.status != "succeeded":
            session.status = "escalated"
            session.awaiting_confirmation = False
            db.commit()
            return {"status": "escalated"}

        booking.status = "confirmed"
        session.status = "confirmed"
        session.awaiting_confirmation = False
        db.commit()
        return {"status": "confirmed", "booking_id": booking.id}

    return {"status": session.status}
