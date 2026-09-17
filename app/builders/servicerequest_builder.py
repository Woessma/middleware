from domain.service_request import ServiceRequestData


UMZH_SERVICEREQUEST_PROFILE = (
    "http://fhir.ch/ig/ch-umzh-connect/StructureDefinition/ch-umzh-connect-servicerequest"
)


def build_umzh_servicerequest(
    data: ServiceRequestData,
    resource_id: str,
) -> dict:
    profiles = [
        UMZH_SERVICEREQUEST_PROFILE,
        *data.additional_profile_urls,
    ]

    # Keep profile order stable and remove duplicates.
    profiles = list(dict.fromkeys(profiles))

    resource = {
        "resourceType": "ServiceRequest",
        "id": resource_id,
        "meta": {
            "profile": profiles,
        },
        "status": data.status,
        "intent": data.intent,
        "subject": {
            "reference": data.subject_reference,
        },
    }

    if data.identifier_value:
        resource["identifier"] = [
            {
                "type": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                            "code": "PLAC",
                        }
                    ]
                },
                "value": data.identifier_value,
            }
        ]

    if data.category_codings:
        resource["category"] = [
            {
                "coding": data.category_codings,
            }
        ]

    if data.authored_on:
        resource["authoredOn"] = data.authored_on

    if data.note_text:
        resource["note"] = [
            {
                "text": data.note_text,
            }
        ]

    if data.requester_reference:
        resource["requester"] = {
            "reference": data.requester_reference,
        }

    if data.recipient_reference:
        resource["performer"] = [
            {
                "reference": data.recipient_reference,
            }
        ]

    if data.reason_references:
        resource["reasonReference"] = [
            {
                "reference": ref,
            }
            for ref in data.reason_references
        ]

    if data.supporting_info_references:
        resource["supportingInfo"] = [
            {
                "reference": ref,
            }
            for ref in data.supporting_info_references
        ]

    return resource
