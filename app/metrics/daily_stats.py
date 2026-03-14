from datetime import datetime
from google.cloud import firestore

db = firestore.Client()

COLLECTION = "daily_usage_stats"


def update_daily_usage_stats(
    audio_duration_seconds: float,
    processing_time_seconds: float,
    estimated_cost_usd: float,
    realtime_factor: float,
    file_size_bytes: int,
    language: str,
):

    now = datetime.utcnow()
    doc_id = now.strftime("%Y-%m-%d")

    ref = db.collection(COLLECTION).document(doc_id)

    @firestore.transactional
    def txn_update(txn):

        snap = ref.get(transaction=txn)

        if snap.exists:
            data = snap.to_dict()
        else:
            data = {
                "date": doc_id,
                "jobs_total": 0,
                "audio_seconds": 0,
                "processing_seconds": 0,
                "estimated_cost_usd": 0,
                "realtime_factor_sum": 0,
                "realtime_factor_count": 0,
                "languages": {},
                "largest_file_bytes": 0,
            }

        data["jobs_total"] += 1
        data["audio_seconds"] += audio_duration_seconds
        data["processing_seconds"] += processing_time_seconds
        data["estimated_cost_usd"] += estimated_cost_usd

        data["realtime_factor_sum"] += realtime_factor
        data["realtime_factor_count"] += 1

        data["avg_realtime_factor"] = (
            data["realtime_factor_sum"] /
            data["realtime_factor_count"]
        )

        data["languages"][language] = data["languages"].get(language, 0) + 1

        if file_size_bytes > data["largest_file_bytes"]:
            data["largest_file_bytes"] = file_size_bytes

        data["minutes_transcribed"] = data["audio_seconds"] / 60

        data["updated_at"] = now.isoformat()

        txn.set(ref, data)

    txn_update(db.transaction())