"""Contracts shared by the document parser, NIM agent and report/UI layers.

Requires Pydantic 2. Parsers own extraction and stable clause identifiers;
the agent never invents page numbers or parses binary document formats.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1)]
Side = Literal["before", "after"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Clause(Contract):
    id: Text
    text: Text


class Document(Contract):
    id: Text
    name: Text
    clauses: list[Clause] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_clauses(self):
        ids = [clause.id for clause in self.clauses]
        if len(ids) != len(set(ids)):
            raise ValueError("Clause ids must be unique within a document")
        return self


class AnalysisRequest(Contract):
    before: list[Document] = Field(min_length=1)
    after: list[Document] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_documents(self):
        for documents in (self.before, self.after):
            ids = [document.id for document in documents]
            if len(ids) != len(set(ids)):
                raise ValueError("Document ids must be unique within each side")
        return self


class SourceReference(Contract):
    side: Side
    document_id: Text
    clause_id: Text
    quote: Text = Field(description="Exact excerpt from the referenced clause")


class UnitChange(Contract):
    status: Literal["preserved", "created", "removed", "reorganized", "uncertain"]
    before_units: list[Text]
    after_units: list[Text]
    explanation: Text
    sources: list[SourceReference] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_sides(self):
        sides = {s.side for s in self.sources}
        if self.status == "created":
            valid = not self.before_units and bool(self.after_units) and "after" in sides
        elif self.status == "removed":
            valid = bool(self.before_units) and not self.after_units and "before" in sides
        elif self.status in ("preserved", "reorganized"):
            valid = bool(self.before_units and self.after_units) and sides == {"before", "after"}
        else:
            valid = bool(self.before_units or self.after_units)
        if not valid:
            raise ValueError("Unit status requires matching units and source sides")
        return self


class FunctionMapping(Contract):
    function: Text
    status: Literal["preserved", "transferred", "changed", "potentially_lost", "added", "uncertain"]
    before_units: list[Text]
    after_units: list[Text]
    explanation: Text
    sources: list[SourceReference] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_sources(self):
        sides = {s.side for s in self.sources}
        required = {"before", "after"}
        if self.status == "potentially_lost":
            required = {"before"}
        elif self.status == "added":
            required = {"after"}
        elif self.status == "uncertain":
            required = set()
        if not required <= sides:
            raise ValueError("Function status requires evidence from the corresponding sides")
        return self


class Finding(Contract):
    kind: Literal["function_loss", "duplication", "responsibility_overlap", "conflict_of_interest"]
    severity: Literal["low", "medium", "high"]
    units: list[Text] = Field(min_length=1)
    description: Text
    recommendation: Text
    sources: list[SourceReference] = Field(min_length=1)

    @model_validator(mode="after")
    def supporting_evidence(self):
        if self.kind == "function_loss":
            if not any(s.side == "before" for s in self.sources):
                raise ValueError("Potential loss requires a before source")
        else:
            evidence = {
                (s.document_id, s.clause_id, " ".join(s.quote.split()))
                for s in self.sources if s.side == "after"
            }
            if len(evidence) < 2:
                raise ValueError("Overlap/conflict requires two distinct after excerpts")
            if self.kind in ("duplication", "responsibility_overlap") and len(set(self.units)) < 2:
                raise ValueError("Cross-unit overlap requires at least two units")
        return self


class AnalysisResult(Contract):
    unit_changes: list[UnitChange]
    function_mappings: list[FunctionMapping]
    findings: list[Finding]
    summary: Text = Field(description="Conclusion based only on sourced items above")
    limitations: list[Text]
    requires_human_review: Literal[True]

    def validate_sources(self, request: AnalysisRequest) -> "AnalysisResult":
        """Reject fabricated locators/quotes; does not prove semantic entailment."""
        index = {
            (side, document.id, clause.id): " ".join(clause.text.split())
            for side in ("before", "after")
            for document in getattr(request, side)
            for clause in document.clauses
        }
        for item in [*self.unit_changes, *self.function_mappings, *self.findings]:
            for source in item.sources:
                key = (source.side, source.document_id, source.clause_id)
                if key not in index:
                    raise ValueError("Unknown document or clause in source reference")
                if " ".join(source.quote.split()) not in index[key]:
                    raise ValueError("Source quote is not present in the referenced clause")
        return self
