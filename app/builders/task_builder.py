from domain.task import TaskData


UMZH_COORDINATION_TASK_PROFILE = (
    "http://fhir.ch/ig/ch-umzh-connect/StructureDefinition/ch-umzh-connect-coordinationtask"
)


TASK_CODE_FULFILL = {
    "coding": [
        {
            "system": "http://hl7.org/fhir/CodeSystem/task-code",
            "code": "fulfill",
            "display": "Fulfill the focal request",
        }
    ]
}


def _build_typed_reference(reference: str) -> dict:
    return {
        "type": {
            "text": "Health assessment questionnaire",
        },
        "valueReference": {
            "reference": reference,
        },
    }


def build_umzh_task(
    data: TaskData,
    resource_id: str,
) -> dict:
    resource = {
        "resourceType": "Task",
        "id": resource_id,
        "meta": {
            "profile": [
                UMZH_COORDINATION_TASK_PROFILE,
            ]
        },
        "basedOn": [
            {
                "reference": data.based_on_reference,
            }
        ],
        "status": data.status,
        "intent": data.intent,
        "priority": data.priority,
        "code": TASK_CODE_FULFILL,
        "focus": {
            "reference": data.focus_reference,
        },
        "for": {
            "reference": data.for_reference,
        },
    }

    if data.identifier_value:
        resource["identifier"] = [
            {
                "system": data.identifier_system,
                "value": data.identifier_value,
            }
        ]

    if data.authored_on:
        resource["authoredOn"] = data.authored_on

    if data.last_modified:
        resource["lastModified"] = data.last_modified

    if data.requester_reference:
        resource["requester"] = {
            "reference": data.requester_reference,
        }

    if data.owner_reference:
        resource["owner"] = {
            "reference": data.owner_reference,
        }

    if data.business_status_text:
        resource["businessStatus"] = {
            "text": data.business_status_text,
        }

    if data.input_references:
        resource["input"] = [
            _build_typed_reference(reference)
            for reference in data.input_references
        ]

    if data.output_references:
        resource["output"] = [
            _build_typed_reference(reference)
            for reference in data.output_references
        ]

    return resource
