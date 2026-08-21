import asyncio

from app.models.user import User
from app.routes import ops


def test_partner_license_route_issues_both_products_without_returning_keys(monkeypatch):
    calls = []
    emails = []

    def fake_issue(**kwargs):
        product = "atelier" if len(calls) == 0 else "dekk"
        calls.append((product, kwargs))
        return {
            "applied": True,
            "license_id": f"{product}_license",
            "license_key": f"{product.upper()}-SECRET-KEY",
        }

    async def fake_email(**kwargs):
        emails.append(kwargs)

    monkeypatch.setattr(ops, "issue_atelier_partner_license", fake_issue)
    monkeypatch.setattr(ops, "issue_dekk_partner_license", fake_issue)
    monkeypatch.setattr(ops, "send_linguist_partner_license_email", fake_email)

    response = asyncio.run(
        ops.issue_linguist_partner_license_route(
            ops.LinguistPartnerLicenseRequest(
                email="Partner@Example.com",
                name="Marie Test",
                cohort="2026-a",
                products=["atelier", "dekk"],
            ),
            User(id="ops-user", email="owner@example.com"),
        )
    )

    assert response["email"] == "partner@example.com"
    assert response["email_sent"] is True
    assert response["products"]["atelier"] == {"license_id": "atelier_license", "issued": True}
    assert response["products"]["dekk"] == {"license_id": "dekk_license", "issued": True}
    assert "SECRET" not in str(response)
    assert emails[0]["licenses"] == {
        "atelier": "ATELIER-SECRET-KEY",
        "dekk": "DEKK-SECRET-KEY",
    }


def test_partner_license_route_is_idempotent_and_does_not_resend(monkeypatch):
    async def fail_email(**kwargs):
        raise AssertionError("An idempotent retry must not resend keys.")

    monkeypatch.setattr(
        ops,
        "issue_atelier_partner_license",
        lambda **kwargs: {"applied": False, "license_id": "atelier_existing", "license_key": "SECRET"},
    )
    monkeypatch.setattr(ops, "send_linguist_partner_license_email", fail_email)

    response = asyncio.run(
        ops.issue_linguist_partner_license_route(
            ops.LinguistPartnerLicenseRequest(
                email="partner@example.com",
                products=["atelier"],
            ),
            User(id="ops-user", email="owner@example.com"),
        )
    )

    assert response["email_sent"] is False
    assert response["products"]["atelier"]["issued"] is False
