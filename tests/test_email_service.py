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
