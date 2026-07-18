import asyncio
from types import SimpleNamespace

import pytest

from app.routes import billing


class FakeRequest:
    headers = {"Stripe-Signature": "test-signature"}

    async def body(self):
        return b"test-payload"


@pytest.mark.parametrize(
    ("product", "plan", "plan_name", "license_id", "issuer_name", "buyer_sender_name"),
    [
        ("dekk", "personal", "Dekk Personal", "dekk_test", "issue_dekk_license_for_checkout", "send_dekk_license_email"),
        ("atelier", "classic", "aTelier Classic", "atelier_test", "issue_atelier_license_for_checkout", "send_atelier_license_email"),
    ],
)
def test_paid_license_checkout_sends_buyer_and_internal_notifications(
    monkeypatch,
    product,
    plan,
    plan_name,
    license_id,
    issuer_name,
    buyer_sender_name,
):
    session = SimpleNamespace(
        id="cs_test_license",
        metadata={"product": product, "plan": plan, "email": "buyer@example.com"},
        customer_details={"email": "buyer@example.com"},
        payment_status="paid",
        amount_total=4900,
        customer="cus_test",
    )
    event = {"type": "checkout.session.completed", "data": {"object": session}}
    buyer_calls = []
    internal_calls = []

    monkeypatch.setattr(billing, "construct_webhook_event", lambda payload, signature: event)
    monkeypatch.setattr(
        billing,
        issuer_name,
        lambda **kwargs: {
            "applied": True,
            "plan_name": plan_name,
            "license_key": "SIGNED-LICENSE-KEY",
            "license_id": license_id,
        },
    )

    async def fake_buyer_sender(**kwargs):
        buyer_calls.append(kwargs)

    async def fake_internal_sender(**kwargs):
        internal_calls.append(kwargs)

    monkeypatch.setattr(billing, buyer_sender_name, fake_buyer_sender)
    monkeypatch.setattr(billing, "send_internal_license_sale_email", fake_internal_sender)

    response = asyncio.run(billing.stripe_webhook_route(FakeRequest()))

    assert response == {"received": True}
    assert len(buyer_calls) == 1
    assert buyer_calls[0]["email"] == "buyer@example.com"
    assert buyer_calls[0]["license_key"] == "SIGNED-LICENSE-KEY"
    assert len(internal_calls) == 1
    assert internal_calls[0]["customer_email"] == "buyer@example.com"
    assert internal_calls[0]["stripe_session_id"] == "cs_test_license"
    assert internal_calls[0]["license_id"] == license_id
    assert "license_key" not in internal_calls[0]
