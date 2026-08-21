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


def test_partner_payload_is_signed_and_not_publicly_listed(test_keypair):
    payload = al.make_license_payload(email="partner@example.com", plan_id="linguist_partner")
    payload.update({"license_name": "Linguist Partner License", "max_devices": 2})
    verified = al.verify_license_key(al.sign_license_payload(payload))

    assert verified is not None
    assert verified["plan"] == "linguist_partner"
    assert verified["license_name"] == "Linguist Partner License"
    assert verified["max_devices"] == 2
    assert all(plan["id"] != "linguist_partner" for plan in al.list_atelier_plans())


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


class _FakeSnapshot:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data or {})


class _FakeDocument:
    def __init__(self, store, key):
        self.store = store
        self.key = key

    def get(self):
        return _FakeSnapshot(self.store.get(self.key))

    def set(self, value):
        self.store[self.key] = dict(value)

    def delete(self):
        self.store.pop(self.key, None)


class _FakeCollection:
    def __init__(self, store):
        self.store = store

    def document(self, key):
        return _FakeDocument(self.store, key)


class _FakeDB:
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        return _FakeCollection(self.collections.setdefault(name, {}))


def test_partner_license_allows_two_computers_and_rejects_third(monkeypatch, test_keypair):
    fake_db = _FakeDB()
    monkeypatch.setattr(al, "db", fake_db)
    payload = al.make_license_payload(email="partner@example.com", plan_id="linguist_partner")
    payload["participant_id"] = "partner-one"
    payload["max_devices"] = 2
    key = al.sign_license_payload(payload)
    fake_db.collection(al.LICENSE_COLLECTION).document("partner_partner-one").set({"status": "active"})

    assert al.activate_atelier_license(license_key=key, machine_id="mac-one")["valid"] is True
    assert al.activate_atelier_license(license_key=key, machine_id="mac-two")["valid"] is True
    third = al.activate_atelier_license(license_key=key, machine_id="mac-three")

    assert third["valid"] is False
    assert "2 computers" in third["error"]


def test_partner_deactivation_frees_one_computer_slot(monkeypatch, test_keypair):
    fake_db = _FakeDB()
    monkeypatch.setattr(al, "db", fake_db)
    payload = al.make_license_payload(email="partner@example.com", plan_id="linguist_partner")
    payload["participant_id"] = "partner-one"
    payload["max_devices"] = 2
    key = al.sign_license_payload(payload)
    fake_db.collection(al.LICENSE_COLLECTION).document("partner_partner-one").set({"status": "active"})

    al.activate_atelier_license(license_key=key, machine_id="mac-one")
    al.activate_atelier_license(license_key=key, machine_id="mac-two")
    assert al.deactivate_atelier_license(license_key=key, machine_id="mac-one") == {
        "valid": True,
        "deactivated": True,
    }
    assert al.activate_atelier_license(license_key=key, machine_id="mac-three")["valid"] is True


def test_revoked_partner_license_cannot_activate(monkeypatch, test_keypair):
    fake_db = _FakeDB()
    monkeypatch.setattr(al, "db", fake_db)
    payload = al.make_license_payload(email="partner@example.com", plan_id="linguist_partner")
    payload["participant_id"] = "partner-one"
    key = al.sign_license_payload(payload)
    fake_db.collection(al.LICENSE_COLLECTION).document("partner_partner-one").set(
        {"status": "revoked", "license_id": payload["license_id"]}
    )

    result = al.activate_atelier_license(license_key=key, machine_id="mac-one")

    assert result["valid"] is False
    assert "no longer active" in result["error"]
