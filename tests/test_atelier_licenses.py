import base64

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from app.services import atelier_licenses as al


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


@pytest.fixture()
def test_keypair(monkeypatch):
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    monkeypatch.setenv("ATELIER_LICENSE_PRIVATE_KEY", _b64url(private_bytes))
    monkeypatch.setenv("ATELIER_LICENSE_PUBLIC_KEY", _b64url(public_bytes))
    return private_key


def test_sign_and_verify_round_trip(test_keypair):
    payload = al.make_license_payload(email="translator@example.com", plan_id="classic")
    license_key = al.sign_license_payload(payload)

    assert license_key.startswith(f"{al.LICENSE_PREFIX}.")
    verified = al.verify_license_key(license_key)
    assert verified is not None
    assert verified["email"] == "translator@example.com"
    assert verified["plan"] == "classic"
    assert verified["product"] == al.PRODUCT_ID


def test_verify_rejects_tampered_payload(test_keypair):
    payload = al.make_license_payload(email="translator@example.com", plan_id="classic")
    license_key = al.sign_license_payload(payload)
    prefix, payload_b64, sig_b64 = license_key.split(".")

    tampered_payload = al.b64url_decode(payload_b64).replace(b"classic", b"pro-tier")
    tampered_key = f"{prefix}.{al.b64url_encode(tampered_payload)}.{sig_b64}"

    assert al.verify_license_key(tampered_key) is None


def test_verify_rejects_garbage_input(test_keypair):
    assert al.verify_license_key("not-a-license-key") is None
    assert al.verify_license_key("") is None
    assert al.verify_license_key("ATLR1.onlytwoparts") is None


def test_verify_rejects_wrong_product_prefix(test_keypair):
    payload = al.make_license_payload(email="translator@example.com", plan_id="classic")
    license_key = al.sign_license_payload(payload)
    forged_prefix = "DEKK1" + license_key[len(al.LICENSE_PREFIX):]

    assert al.verify_license_key(forged_prefix) is None
