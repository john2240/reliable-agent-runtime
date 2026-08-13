"""Concurrency-safe in-memory retail service used by examples and tests.

The service models an external provider rather than runtime behavior. Keeping
it behind tool adapters makes the demo replaceable without coupling the core
runtime to retail concepts.
"""

import asyncio
import uuid
from copy import deepcopy
from typing import cast

from reliable_agent_runtime.domain.errors import PermanentToolError, UnknownToolOutcome
from reliable_agent_runtime.domain.models import CheckResult
from reliable_agent_runtime.domain.types import JsonObject


class RetailSystem:
    """Minimal external system with provider-side idempotency semantics."""

    def __init__(self, *, refund_unknown_outcome_once: bool = False) -> None:
        self._lock = asyncio.Lock()
        self._orders: dict[str, JsonObject] = {
            "ord-1001": {
                "order_id": "ord-1001",
                "customer_email": "customer@example.com",
                "total_cents": 12_900,
                "currency": "CNY",
                "status": "paid",
                "refundable": True,
            },
        }
        self._tickets: dict[str, JsonObject] = {
            "tic-1001": {
                "ticket_id": "tic-1001",
                "status": "open",
                "note": "Customer requested a refund.",
            },
        }
        self._ticket_changes: dict[str, JsonObject] = {}
        self._refunds_by_key: dict[str, JsonObject] = {}
        self._emails_by_key: dict[str, JsonObject] = {}
        self._refund_unknown_outcome_remaining = 1 if refund_unknown_outcome_once else 0

    async def get_order(self, order_id: str) -> JsonObject | None:
        async with self._lock:
            order = self._orders.get(order_id)
            return deepcopy(order) if order else None

    async def get_ticket(self, ticket_id: str) -> JsonObject | None:
        async with self._lock:
            ticket = self._tickets.get(ticket_id)
            return deepcopy(ticket) if ticket else None

    async def update_ticket(
        self,
        *,
        idempotency_key: str,
        ticket_id: str,
        status: str,
        note: str,
    ) -> JsonObject:
        async with self._lock:
            existing_change = self._ticket_changes.get(idempotency_key)
            if existing_change:
                return deepcopy(cast(JsonObject, existing_change["after"]))

            current = self._tickets.get(ticket_id)
            if current is None:
                raise PermanentToolError(
                    f"ticket {ticket_id!r} does not exist",
                    details={"ticket_id": ticket_id},
                )

            before = deepcopy(current)
            after: JsonObject = {
                "ticket_id": ticket_id,
                "status": status,
                "note": note,
                "change_id": idempotency_key,
            }
            self._tickets[ticket_id] = deepcopy(after)
            self._ticket_changes[idempotency_key] = {
                "before": before,
                "after": deepcopy(after),
                "compensated": False,
            }
            return deepcopy(after)

    async def get_ticket_change(self, idempotency_key: str) -> JsonObject | None:
        async with self._lock:
            change = self._ticket_changes.get(idempotency_key)
            if not change:
                return None
            return deepcopy(cast(JsonObject, change["after"]))

    async def compensate_ticket_change(self, change_id: str) -> JsonObject:
        async with self._lock:
            change = self._ticket_changes.get(change_id)
            if change is None:
                raise PermanentToolError(
                    f"ticket change {change_id!r} does not exist",
                    details={"change_id": change_id},
                )
            before = deepcopy(cast(JsonObject, change["before"]))
            ticket_id = cast(str, before["ticket_id"])
            if not cast(bool, change["compensated"]):
                self._tickets[ticket_id] = before
                change["compensated"] = True
            restored = deepcopy(self._tickets[ticket_id])
            restored["change_id"] = change_id
            return restored

    async def check_refund_preconditions(
        self,
        *,
        idempotency_key: str,
        order_id: str,
        amount_cents: int,
    ) -> CheckResult:
        async with self._lock:
            if idempotency_key in self._refunds_by_key:
                return CheckResult.success()
            order = self._orders.get(order_id)
            if order is None:
                return CheckResult(
                    passed=False,
                    reason=f"order {order_id!r} does not exist",
                    details={"order_id": order_id},
                )
            if not cast(bool, order["refundable"]):
                return CheckResult(
                    passed=False,
                    reason=f"order {order_id!r} is not refundable",
                    details={"order_id": order_id},
                )
            if cast(str, order["status"]) != "paid":
                return CheckResult(
                    passed=False,
                    reason=f"order {order_id!r} is not in paid state",
                    details={"order_id": order_id, "status": order["status"]},
                )
            if cast(int, order["total_cents"]) != amount_cents:
                return CheckResult(
                    passed=False,
                    reason="refund amount must match the order total in this demo",
                    details={
                        "order_id": order_id,
                        "expected_amount_cents": order["total_cents"],
                        "actual_amount_cents": amount_cents,
                    },
                )
            return CheckResult.success()

    async def issue_refund(
        self,
        *,
        idempotency_key: str,
        order_id: str,
        amount_cents: int,
    ) -> JsonObject:
        async with self._lock:
            existing = self._refunds_by_key.get(idempotency_key)
            if existing:
                return deepcopy(existing)

            order = self._orders.get(order_id)
            if order is None:
                raise PermanentToolError(f"order {order_id!r} does not exist")
            if cast(str, order["status"]) != "paid":
                raise PermanentToolError(
                    f"order {order_id!r} is not refundable in state {order['status']!r}",
                )
            if cast(int, order["total_cents"]) != amount_cents:
                raise PermanentToolError("refund amount does not match order total")

            refund: JsonObject = {
                "refund_id": f"ref_{uuid.uuid4().hex}",
                "order_id": order_id,
                "amount_cents": amount_cents,
                "currency": order["currency"],
                "status": "succeeded",
            }
            self._refunds_by_key[idempotency_key] = deepcopy(refund)
            order["status"] = "refunded"
            order["refundable"] = False

            if self._refund_unknown_outcome_remaining > 0:
                self._refund_unknown_outcome_remaining -= 1
                raise UnknownToolOutcome(
                    "refund API connection dropped after the provider committed",
                    details={"order_id": order_id},
                )
            return deepcopy(refund)

    async def get_refund_by_key(self, idempotency_key: str) -> JsonObject | None:
        async with self._lock:
            refund = self._refunds_by_key.get(idempotency_key)
            return deepcopy(refund) if refund else None

    async def refund_count(self) -> int:
        async with self._lock:
            return len(self._refunds_by_key)

    async def send_email(
        self,
        *,
        idempotency_key: str,
        to: str,
        subject: str,
        body: str,
    ) -> JsonObject:
        del subject, body
        async with self._lock:
            existing = self._emails_by_key.get(idempotency_key)
            if existing:
                return deepcopy(existing)
            message: JsonObject = {
                "message_id": f"msg_{uuid.uuid4().hex}",
                "to": to,
                "status": "sent",
            }
            self._emails_by_key[idempotency_key] = deepcopy(message)
            return message

    async def get_email_by_key(self, idempotency_key: str) -> JsonObject | None:
        async with self._lock:
            email = self._emails_by_key.get(idempotency_key)
            return deepcopy(email) if email else None
