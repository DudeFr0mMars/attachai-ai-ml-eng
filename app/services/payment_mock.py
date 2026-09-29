from dataclasses import dataclass
from threading import Lock

from app.config import settings


class PaymentTimeoutError(Exception):
    """Raised when the (mock) payment provider times out with an ambiguous
    response — the caller does not know whether the charge went through."""


class PaymentConflictError(Exception):
    """An idempotency key was reused for a different amount."""


@dataclass
class ChargeResult:
    status: str  # "succeeded" | "failed"


class PaymentMockClient:
    def __init__(self) -> None:
        # Every attempted charge, in order — a stand-in for the provider's own
        # ledger, useful for proving a bug caused two real-world charges.
        self.charge_log: list[int] = []
        self._outcomes: dict[str, tuple[int, ChargeResult | None]] = {}
        self._lock = Lock()

    def lookup(self, amount_cents: int, idempotency_key: str) -> ChargeResult | None:
        """Return a known provider result without initiating another charge."""
        with self._lock:
            prior = self._outcomes.get(idempotency_key)
            if prior is None:
                return None
            original_amount, outcome = prior
            if original_amount != amount_cents:
                raise PaymentConflictError("idempotency key already used for another amount")
            return outcome

    def reset(self) -> None:
        """Clear mock provider state between isolated tests."""
        with self._lock:
            self.charge_log.clear()
            self._outcomes.clear()

    def charge(self, amount_cents: int, idempotency_key: str | None = None) -> ChargeResult:
        with self._lock:
            if idempotency_key is not None and idempotency_key in self._outcomes:
                original_amount, outcome = self._outcomes[idempotency_key]
                if original_amount != amount_cents:
                    raise PaymentConflictError("idempotency key already used for another amount")
                if outcome is None:
                    raise PaymentTimeoutError("provider timed out")
                return outcome

            self.charge_log.append(amount_cents)
            if amount_cents == settings.payment_timeout_trigger_cents:
                if idempotency_key is not None:
                    self._outcomes[idempotency_key] = (amount_cents, None)
                raise PaymentTimeoutError("provider timed out")
            result = ChargeResult(status="failed" if amount_cents <= 0 else "succeeded")
            if idempotency_key is not None:
                self._outcomes[idempotency_key] = (amount_cents, result)
            return result


payment_mock_client = PaymentMockClient()
