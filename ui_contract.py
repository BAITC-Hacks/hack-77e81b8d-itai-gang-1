"""Provisional UI contract; agree these field names with Person 1 and Person 2."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Source(StrictModel):
    id: str = Field(min_length=1)
    document: str = Field(min_length=1)
    version: Literal["before", "after"]
    location: str = Field(min_length=1)
    text: str = Field(min_length=1)


class Finding(StrictModel):
    title: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)


class Department(Finding):
    status: Literal["created", "preserved", "reorganized", "removed"]


class Function(Finding):
    status: Literal["preserved", "transferred", "lost", "duplicated", "new"]
    before_units: list[str]
    after_units: list[str]


class AnalysisReport(StrictModel):
    departments: list[Department]
    functions: list[Function]
    duplicates: list[Finding]
    conflicts: list[Finding]
    recommendations: list[Finding]
    conclusion: Finding
    sources: list[Source]

    @model_validator(mode="after")
    def check_references(self):
        ids = [source.id for source in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("Повторяются ID источников")
        known = set(ids)
        findings = [*self.departments, *self.functions, *self.duplicates,
                    *self.conflicts, *self.recommendations, self.conclusion]
        for finding in findings:
            unknown = set(finding.source_ids) - known
            if unknown:
                raise ValueError(f"Не найдены источники: {', '.join(sorted(unknown))}")
        return self
