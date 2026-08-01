from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.services.dekk_licenses import get_dekk_download_summary, record_dekk_download_event


class ProductDownloadTests(unittest.TestCase):
    @patch("app.services.dekk_licenses.db")
    def test_records_supported_product(self, mock_db: MagicMock):
        document = MagicMock(id="event-1")
        mock_db.collection.return_value.add.return_value = (None, document)

        result = record_dekk_download_event(product="atelier", version="0.1.6", source="updater")

        self.assertEqual(result, {"id": "event-1", "recorded": True})
        record = mock_db.collection.return_value.add.call_args.args[0]
        self.assertEqual(record["product"], "atelier")
        self.assertEqual(record["source"], "updater")

    def test_rejects_unknown_product(self):
        with self.assertRaisesRegex(ValueError, "Unknown product"):
            record_dekk_download_event(product="other")

    @patch("app.services.dekk_licenses.db")
    def test_summary_includes_product_source_platform_and_version(self, mock_db: MagicMock):
        events = [
            {"product": "dekk", "version": "0.1.6", "platform": "macos", "source": "website"},
            {"product": "atelier", "version": "0.1.6", "platform": "macos", "source": "updater"},
        ]
        query = mock_db.collection.return_value.order_by.return_value.limit.return_value
        query.stream.return_value = [MagicMock(to_dict=lambda event=event: event) for event in events]

        summary = get_dekk_download_summary()

        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["by_product"], {"dekk": 1, "atelier": 1})
        self.assertEqual(summary["by_source"], {"website": 1, "updater": 1})


if __name__ == "__main__":
    unittest.main()
