"""Strict request and response models for the retail demo adapters."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Reject unknown fields at the demo system boundary."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GetOrderInput(StrictModel):
    order_id: str = Field(min_length=1, max_length=64)


class OrderOutput(StrictModel):
    order_id: str
    customer_email: str
    total_cents: int
    currency: str
    status: str
    refundable: bool


class UpdateTicketInput(StrictModel):
    ticket_id: str = Field(min_length=1, max_length=64)
    status: Literal["open", "processing", "resolved"]
    note: str = Field(min_length=1, max_length=1000)


class TicketOutput(StrictModel):
    ticket_id: str
    status: str
    note: str
    change_id: str


class IssueRefundInput(StrictModel):
    order_id: str = Field(min_length=1, max_length=64)
    amount_cents: int = Field(gt=0, le=100_000_000)
    reason: str = Field(default="customer_request", min_length=1, max_length=200)


class RefundOutput(StrictModel):
    refund_id: str
    order_id: str
    amount_cents: int
    currency: str
    status: Literal["succeeded"]


class SendEmailInput(StrictModel):
    to: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)


class EmailOutput(StrictModel):
    message_id: str
    to: str
    status: Literal["sent"]
