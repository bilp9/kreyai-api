from app.state import firestore_jobs


class _Doc:
    def __init__(self, doc_id: str, data: dict):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


def test_list_recent_jobs_falls_back_when_order_by_fails(monkeypatch):
    docs = [
        _Doc("job-1", {"created_at": "2026-03-24T10:00:00+00:00", "status": "completed"}),
        _Doc("job-2", {"created_at": "2026-03-24T11:00:00+00:00", "status": "failed"}),
        _Doc("job-3", {"created_at": "2026-03-24T09:00:00+00:00", "status": "queued"}),
    ]

    class _FallbackQuery:
        def stream(self):
            return iter(docs)

    class _Collection:
        def order_by(self, *args, **kwargs):
            raise RuntimeError("order_by unavailable")

        def limit(self, value):
            assert value == 2
            return _FallbackQuery()

    monkeypatch.setattr(firestore_jobs, "db", type("DB", (), {"collection": lambda self, name: _Collection()})())

    jobs = firestore_jobs.list_recent_jobs(limit=2)

    assert [job["job_id"] for job in jobs] == ["job-2", "job-1"]


def test_count_jobs_by_status_falls_back_when_aggregation_fails(monkeypatch):
    docs = [_Doc("job-1", {"status": "completed"}), _Doc("job-2", {"status": "completed"})]

    class _WhereQuery:
        def count(self):
            raise RuntimeError("aggregation unavailable")

        def stream(self):
            return iter(docs)

    class _Collection:
        def where(self, field, op, value):
            assert (field, op, value) == ("status", "==", "completed")
            return _WhereQuery()

    monkeypatch.setattr(firestore_jobs, "db", type("DB", (), {"collection": lambda self, name: _Collection()})())

    assert firestore_jobs.count_jobs_by_status("completed") == 2


def test_list_recent_jobs_filters_locally(monkeypatch):
    docs = [
        _Doc(
            "job-1",
            {
                "created_at": "2026-03-24T10:00:00+00:00",
                "status": "completed",
                "language": "en",
                "email": "billy@kreyai.com",
            },
        ),
        _Doc(
            "job-2",
            {
                "created_at": "2026-03-24T11:00:00+00:00",
                "status": "failed",
                "language": "ht",
                "email": "other@example.com",
            },
        ),
        _Doc(
            "job-3",
            {
                "created_at": "2026-03-24T12:00:00+00:00",
                "status": "failed",
                "language": "ht",
                "email": "billy@kreyai.com",
            },
        ),
    ]

    class _OrderedQuery:
        def where(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def limit(self, value):
            assert value == 100
            return self

        def start_after(self, doc):
            return self

        def stream(self):
            return iter(docs)

    class _Collection:
        def where(self, *args, **kwargs):
            return _OrderedQuery()

        def order_by(self, *args, **kwargs):
            return _OrderedQuery()

    monkeypatch.setattr(firestore_jobs, "db", type("DB", (), {"collection": lambda self, name: _Collection()})())

    jobs = firestore_jobs.list_recent_jobs(
        limit=1,
        status="failed",
        language="ht",
        email_query="billy",
    )

    assert [job["job_id"] for job in jobs] == ["job-3"]
