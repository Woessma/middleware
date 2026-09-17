from dataclasses import dataclass, field


@dataclass
class TaskData:
    based_on_reference: str
    focus_reference: str
    for_reference: str

    identifier_value: str | None = None
    identifier_system: str = "urn:ietf:rfc:3986"

    status: str = "requested"
    intent: str = "order"
    priority: str = "routine"

    authored_on: str | None = None
    last_modified: str | None = None

    requester_reference: str | None = None
    owner_reference: str | None = None

    business_status_text: str | None = None

    input_references: list[str] = field(default_factory=list)
    output_references: list[str] = field(default_factory=list)
