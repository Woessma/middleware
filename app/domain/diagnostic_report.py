from dataclasses import dataclass, field


@dataclass
class DiagnosticReportData:
    status: str
    code_codings: list[dict]

    subject_reference: str

    based_on_references: list[str] = field(default_factory=list)
    performer_references: list[str] = field(default_factory=list)
    result_references: list[str] = field(default_factory=list)

    effective_datetime: str | None = None
    issued: str | None = None

    conclusion: str | None = None
    presented_forms: list[dict] = field(default_factory=list)
