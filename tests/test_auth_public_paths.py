from app.middleware.auth import _is_public_path


def test_customer_routes_with_scoped_access_are_public_to_global_middleware():
    assert _is_public_path("/api/")
    assert _is_public_path("/api/verify")
    assert _is_public_path("/api/jobs/KR-ABC123")
    assert _is_public_path("/api/atelier/activate")


def test_internal_and_unknown_routes_are_not_public():
    assert not _is_public_path("/ops/dashboard")
    assert not _is_public_path("/api/upload")
    assert not _is_public_path("/api/unknown-future-route")
