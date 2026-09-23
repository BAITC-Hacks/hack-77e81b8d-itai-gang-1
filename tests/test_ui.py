import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from backend_adapter import InputDocument, analyze
from demo_data import demo_report
from ui_contract import AnalysisReport

APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")


class ReportTests(unittest.TestCase):
    def test_export_roundtrip(self):
        report = demo_report()
        self.assertEqual(AnalysisReport.model_validate_json(report.model_dump_json()), report)

    def test_missing_source_rejected(self):
        data = demo_report().model_dump()
        data["functions"][0]["source_ids"] = ["invented:p999"]
        with self.assertRaises(ValidationError):
            AnalysisReport.model_validate(data)

    def test_duplicate_source_rejected(self):
        data = demo_report().model_dump()
        data["sources"].append(data["sources"][0])
        with self.assertRaises(ValidationError):
            AnalysisReport.model_validate(data)

    def test_uncited_conclusion_rejected(self):
        data = demo_report().model_dump()
        data["conclusion"]["source_ids"] = []
        with self.assertRaises(ValidationError):
            AnalysisReport.model_validate(data)

    def test_adapter_passes_file_bytes_to_backend(self):
        before = [InputDocument("old.docx", b"old")]
        after = [InputDocument("new.pdf", b"new")]

        def backend_call(received_before, received_after):
            self.assertEqual(received_before, before)
            self.assertEqual(received_after, after)
            return demo_report().model_dump()

        with patch.dict(sys.modules, {"backend": SimpleNamespace(analyze_documents=backend_call)}):
            self.assertEqual(analyze(before, after), demo_report())


class UITests(unittest.TestCase):
    def test_demo_and_source_selection(self):
        app = AppTest.from_file(APP_PATH).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.tabs), 5)
        self.assertEqual([m.value for m in app.metric], ["2", "1", "1", "1"])
        self.assertTrue(any("Учебные данные" in w.value for w in app.warning))
        app.selectbox[1].select(1).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("after:p2" in e.label for e in app.expander))

    def test_documents_mode_does_not_show_demo_results(self):
        app = AppTest.from_file(APP_PATH).run(timeout=30)
        app.radio[0].set_value("Документы").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.metric), 0)
        self.assertTrue(app.button[0].disabled)

    def test_import_valid_and_invalid_json(self):
        app = AppTest.from_file(APP_PATH).run(timeout=30)
        app.radio[0].set_value("Готовый JSON").run()
        for content, valid in ((demo_report().model_dump_json().encode(), True), (b"{}", False)):
            upload = SimpleNamespace(name="result.json", getvalue=lambda: content)
            with patch("streamlit.file_uploader", return_value=upload):
                app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.metric), 4 if valid else 0)
            self.assertEqual(len(app.error), 0 if valid else 1)


if __name__ == "__main__":
    unittest.main()
