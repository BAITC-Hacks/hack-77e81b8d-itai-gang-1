"""The team's integration point. No parsing or model decisions belong in the UI."""

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

from ui_contract import AnalysisReport


@dataclass(frozen=True)
class InputDocument:
    name: str
    content: bytes


def backend_available() -> bool:
    return Path(__file__).with_name("backend.py").is_file()


def analyze(before: list[InputDocument], after: list[InputDocument]) -> AnalysisReport:
    """Person 1 supplies backend.analyze_documents(before, after) -> dict.

    Both arguments contain InputDocument instances. The backend calls the parser,
    NIM and its own validation, then returns the report plus the parser's sources.
    No files are persisted by this adapter.
    """
    if not before or not after:
        raise ValueError("Нужны оба комплекта документов")
    result = import_module("backend").analyze_documents(before, after)
    if isinstance(result, AnalysisReport):
        result = result.model_dump()
    return AnalysisReport.model_validate(result)
