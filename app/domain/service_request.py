from dataclasses import dataclass, field


@dataclass
class ServiceRequestData:
    identifier_value: str

    subject_reference: str

    status: str = "active"
    intent: str = "order"

    requester_reference: str | None = None
    recipient_reference: str | None = None

    authored_on: str | None = None

    category_codings: list[dict] = field(default_factory=list)
    reason_references: list[str] = field(default_factory=list)
    supporting_info_references: list[str] = field(default_factory=list)

    note_text: str | None = None

    additional_profile_urls: list[str] = field(default_factory=list)
