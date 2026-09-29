from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_member
from app.db import get_db
from app.models import Booking, ConversationSession, Member, PaymentAttempt
from app.schemas import ConfirmPaymentIn
from app.services.payment_mock import PaymentConflictError, PaymentTimeoutError, payment_mock_client

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post("/{booking_id}/confirm-payment")
def confirm_payment(
    booking_id: int,
    payload: ConfirmPaymentIn,
    db: Session = Depends(get_db),
    member: Member = Depends(get_current_member),
):
    booking = (
        db.query(Booking)
        .filter(Booking.id == booking_id, Booking.member_id == member.id)
        .with_for_update()
        .first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="booking not found")
    if payload.amount_cents != booking.amount_cents:
        raise HTTPException(status_code=400, detail="payment amount does not match booking")
    amount_cents = booking.amount_cents

    owning_session = db.query(ConversationSession).filter(ConversationSession.booking_id == booking.id).first()
    if owning_session and owning_session.status != "confirmed":
        raise HTTPException(status_code=409, detail="payment is managed by the active session")

    key = f"booking:{booking.id}"
    attempt = (
        db.query(PaymentAttempt)
        .filter(PaymentAttempt.booking_id == booking.id, PaymentAttempt.idempotency_key == key)
        .first()
    )
    if booking.status == "confirmed":
        return {"status": "succeeded", "attempt_id": attempt.id if attempt else None, "booking_status": booking.status}

    is_new_attempt = attempt is None
    if is_new_attempt:
        attempt = PaymentAttempt(
            booking_id=booking.id,
            idempotency_key=key,
            amount_cents=amount_cents,
            status="initiated",
        )
        db.add(attempt)
        db.commit()
    elif attempt.amount_cents != amount_cents:
        raise HTTPException(status_code=409, detail="payment amount conflicts with prior attempt")
    elif attempt.status in ("succeeded", "failed"):
        return {"status": attempt.status, "attempt_id": attempt.id, "booking_status": booking.status}

    try:
        result = (
            payment_mock_client.charge(amount_cents, idempotency_key=key)
            if is_new_attempt
            else payment_mock_client.lookup(amount_cents, key)
        )
    except PaymentTimeoutError:
        attempt.status = "unknown"
        db.commit()
        raise HTTPException(status_code=504, detail="payment provider timed out")
    except PaymentConflictError:
        raise HTTPException(status_code=409, detail="payment amount conflicts with prior attempt")

    if result is None:
        raise HTTPException(status_code=504, detail="payment outcome requires reconciliation")

    attempt.status = result.status
    if result.status == "succeeded":
        booking.status = "confirmed"
    db.commit()

    return {"status": result.status, "attempt_id": attempt.id, "booking_status": booking.status}
