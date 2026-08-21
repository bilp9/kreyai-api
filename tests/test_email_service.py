import asyncio

import pytest

from app.services import email_service


def test_send_verification_email_sends_encoded_verify_link(monkeypatch):
    sent = {}

    async def fake_send_email(to_email, subject, html):
        sent["to_email"] = to_email
        sent["subject"] = subject
        sent["html"] = html

    monkeypatch.setattr(email_service, "FRONTEND_BASE_URL", "https://kreyai.com")
    monkeypatch.setattr(email_service, "_send_email", fake_send_email)

    asyncio.run(
        email_service.send_verification_email(
            "user+test@example.com",
            "KR-ABC123",
            "123456",
        )
    )

    assert sent["to_email"] == "user+test@example.com"
    assert sent["subject"] == "Verify your email — KreyAI"
    assert "https://kreyai.com/verify?" in sent["html"]
    assert "job=KR-ABC123" in sent["html"]
    assert "email=user%2Btest%40example.com" in sent["html"]
    assert "code=123456" in sent["html"]


@pytest.mark.parametrize(
    ("sender", "subject", "activation_text"),
    [
        (email_service.send_dekk_license_email, "Your Dekk license key — KreyAI", "License"),
        (email_service.send_atelier_license_email, "Your aTelier license key — KreyAI", "Settings &gt; License"),
    ],
)
def test_license_email_contains_purchase_and_support_details(monkeypatch, sender, subject, activation_text):
    sent = {}

    async def fake_send_email(to_email, sent_subject, html):
        sent.update(to_email=to_email, subject=sent_subject, html=html)

    monkeypatch.setattr(email_service, "FRONTEND_BASE_URL", "https://www.kreyai.com")
    monkeypatch.setattr(email_service, "_send_email", fake_send_email)

    asyncio.run(
        sender(
            email="buyer@example.com",
            plan_name="Test Plan",
            license_key="SIGNED-LICENSE-KEY",
            amount_total_cents=4900,
        )
    )

    assert sent["to_email"] == "buyer@example.com"
    assert sent["subject"] == subject
    assert "Test Plan" in sent["html"]
    assert "SIGNED-LICENSE-KEY" in sent["html"]
    assert "$49.00" in sent["html"]
    assert activation_text in sent["html"]
    assert "support@kreyai.com" in sent["html"]


def test_internal_license_sale_email_excludes_license_key(monkeypatch):
    sent = {}

    async def fake_send_emails(to_emails, subject, html):
        sent.update(to_emails=to_emails, subject=subject, html=html)

    monkeypatch.setattr(email_service, "INTERNAL_SALES_NOTIFICATION_EMAILS", ["owner@example.com"])
    monkeypatch.setattr(email_service, "_send_emails", fake_send_emails)

    asyncio.run(
        email_service.send_internal_license_sale_email(
            product_name="Dekk",
            plan_name="Dekk Personal",
            customer_email="buyer@example.com",
            amount_total_cents=3900,
            stripe_session_id="cs_test_123",
            license_id="dekk_abc123",
        )
    )

    assert sent["to_emails"] == ["owner@example.com"]
    assert sent["subject"] == "New Dekk license sale — Dekk Personal"
    assert "buyer@example.com" in sent["html"]
    assert "$39.00" in sent["html"]
    assert "cs_test_123" in sent["html"]
    assert "dekk_abc123" in sent["html"]
    assert "license key is intentionally excluded" in sent["html"]


def test_linguist_partner_email_contains_both_product_keys(monkeypatch):
    sent = {}

    async def fake_send_email(to_email, subject, html):
        sent.update(to_email=to_email, subject=subject, html=html)

    monkeypatch.setattr(email_service, "FRONTEND_BASE_URL", "https://www.kreyai.com")
    monkeypatch.setattr(email_service, "_send_email", fake_send_email)

    asyncio.run(
        email_service.send_linguist_partner_license_email(
            email="partner@example.com",
            participant_name="Marie Test",
            licenses={"atelier": "ATELIER-KEY", "dekk": "DEKK-KEY"},
        )
    )

    assert sent["to_email"] == "partner@example.com"
    assert sent["subject"] == "Your KreyAI Linguist Partner licenses"
    assert "Marie Test" in sent["html"]
    assert "ATELIER-KEY" in sent["html"]
    assert "DEKK-KEY" in sent["html"]
    assert "complimentary" in sent["html"]
