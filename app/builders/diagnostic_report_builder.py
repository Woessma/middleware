from domain.diagnostic_report import DiagnosticReportData


def build_diagnostic_report(
    data: DiagnosticReportData,
    resource_id: str,
) -> dict:
    resource = {
        "resourceType": "DiagnosticReport",
        "id": resource_id,
        "status": data.status,
        "code": {
            "coding": data.code_codings,
        },
        "subject": {
            "reference": data.subject_reference,
        },
    }

    if data.based_on_references:
        resource["basedOn"] = [
            {
                "reference": reference,
            }
            for reference in data.based_on_references
        ]

    if data.performer_references:
        resource["performer"] = [
            {
                "reference": reference,
            }
            for reference in data.performer_references
        ]

    if data.result_references:
        resource["result"] = [
            {
                "reference": reference,
            }
            for reference in data.result_references
        ]

    if data.effective_datetime:
        resource["effectiveDateTime"] = data.effective_datetime

    if data.issued:
        resource["issued"] = data.issued

    if data.conclusion:
        resource["conclusion"] = data.conclusion

    if data.presented_forms:
        resource["presentedForm"] = data.presented_forms

    return resource
