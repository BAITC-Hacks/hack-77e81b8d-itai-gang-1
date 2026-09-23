"""Backend integration for the Streamlit UI.

The UI sends uploaded file bytes here. This module owns parsing, NIM analysis
and conversion from the Person 1 agent contract into the Person 3 UI contract.
"""

from __future__ import annotations

import io
from typing import Iterable

from src.agent import analyze_documents as agent_analyze_documents
from src.parsers import document_clause_index, parse_document
from src.schemas import AnalysisResult, Document, Finding as AgentFinding, SourceReference
from ui_contract import AnalysisReport, Department, Finding, Function, Source


def analyze_documents(before, after) -> dict:
    before_docs = _parse_inputs(before, "before")
    after_docs = _parse_inputs(after, "after")
    result = agent_analyze_documents(before_docs, after_docs)
    report = agent_result_to_report(result, before_docs, after_docs)
    return report.model_dump(mode="json")


def agent_result_to_report(
    result: AnalysisResult,
    before_docs: list[Document],
    after_docs: list[Document],
) -> AnalysisReport:
    clause_index = document_clause_index(before_docs, after_docs)
    source_lookup: dict[str, Source] = {}

    def ids_for(sources: Iterable[SourceReference]) -> list[str]:
        ids = []
        for ref in sources:
            source_id = _source_id(ref)
            if source_id not in source_lookup:
                document, clause = clause_index[(ref.side, ref.document_id, ref.clause_id)]
                source_lookup[source_id] = Source(
                    id=source_id,
                    document=document.name,
                    version=ref.side,
                    location=ref.clause_id,
                    text=clause.text,
                )
            ids.append(source_id)
        return list(dict.fromkeys(ids))

    departments = [
        Department(
            title=_unit_title(item.before_units, item.after_units),
            status=_department_status(item.status),
            explanation=item.explanation,
            source_ids=ids_for(item.sources),
        )
        for item in result.unit_changes
    ]
    functions = [
        Function(
            title=item.function,
            status=_function_status(item.status),
            before_units=item.before_units,
            after_units=item.after_units,
            explanation=item.explanation,
            source_ids=ids_for(item.sources),
        )
        for item in result.function_mappings
    ]

    duplicates = []
    conflicts = []
    recommendations = []
    for finding in result.findings:
        ui_finding = Finding(
            title=finding.description,
            explanation=finding.recommendation,
            source_ids=ids_for(finding.sources),
        )
        if finding.kind == "duplication":
            duplicates.append(ui_finding)
        else:
            conflicts.append(ui_finding)
        recommendations.append(_recommendation(finding, ui_finding.source_ids))

    if not source_lookup:
        _seed_first_source(before_docs, after_docs, source_lookup)
    conclusion_source_ids = _conclusion_source_ids(departments, functions, duplicates, conflicts, source_lookup)
    conclusion = Finding(
        title="Итоговое заключение",
        explanation=_summary_with_limitations(result),
        source_ids=conclusion_source_ids,
    )

    return AnalysisReport(
        departments=departments,
        functions=functions,
        duplicates=duplicates,
        conflicts=conflicts,
        recommendations=recommendations,
        conclusion=conclusion,
        sources=list(source_lookup.values()),
    )


def _parse_inputs(inputs, side: str) -> list[Document]:
    documents = []
    for index, item in enumerate(inputs, start=1):
        stream = io.BytesIO(item.content)
        stream.name = item.name
        documents.append(
            parse_document(
                stream,
                document_id=_document_id(item.name, side, index),
                document_label=item.name,
            )
        )
    return documents


def _source_id(ref: SourceReference) -> str:
    return f"{ref.side}:{ref.document_id}:{ref.clause_id}"


def _document_id(name: str, side: str, index: int) -> str:
    lowered = name.lower()
    if side == "before" and ("редакция_8" in lowered or "red8" in lowered):
        return "red8"
    if side == "after" and ("редакция_9" in lowered or "red9" in lowered):
        return "red9"
    return f"{side}{index}"


def _unit_title(before_units: list[str], after_units: list[str]) -> str:
    before = ", ".join(before_units) or "—"
    after = ", ".join(after_units) or "—"
    return before if before == after else f"{before} → {after}"


def _department_status(status: str) -> str:
    return {
        "preserved": "preserved",
        "created": "created",
        "removed": "removed",
        "reorganized": "reorganized",
        "uncertain": "reorganized",
    }[status]


def _function_status(status: str) -> str:
    return {
        "preserved": "preserved",
        "transferred": "transferred",
        "changed": "transferred",
        "potentially_lost": "lost",
        "added": "new",
        "uncertain": "preserved",
    }[status]


def _recommendation(finding: AgentFinding, source_ids: list[str]) -> Finding:
    return Finding(
        title=f"Рекомендация: {finding.kind}",
        explanation=finding.recommendation,
        source_ids=source_ids,
    )


def _seed_first_source(
    before_docs: list[Document],
    after_docs: list[Document],
    source_lookup: dict[str, Source],
) -> None:
    for version, documents in (("before", before_docs), ("after", after_docs)):
        for document in documents:
            if document.clauses:
                clause = document.clauses[0]
                source_id = f"{version}:{document.id}:{clause.id}"
                source_lookup[source_id] = Source(
                    id=source_id,
                    document=document.name,
                    version=version,
                    location=clause.id,
                    text=clause.text,
                )
                return


def _conclusion_source_ids(*groups) -> list[str]:
    ids = []
    for group in groups[:-1]:
        for item in group:
            ids.extend(item.source_ids)
    source_lookup = groups[-1]
    if not ids and source_lookup:
        ids.append(next(iter(source_lookup)))
    return list(dict.fromkeys(ids))[:20]


def _summary_with_limitations(result: AnalysisResult) -> str:
    if not result.limitations:
        return result.summary
    return result.summary + "\n\nОграничения: " + " ".join(result.limitations)
