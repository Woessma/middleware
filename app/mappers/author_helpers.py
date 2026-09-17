def add_author_display(resource, entry, field="author"):
    author = entry.get("authorDisplay")
    if not author:
        return resource

    resource_type = resource.get("resourceType")
    if resource_type in {"Observation", "Immunization"}:
        resource["performer"] = [{"display": author}] if resource_type == "Observation" else [{"actor": {"display": author}}]
    elif resource_type in {"AllergyIntolerance", "Condition"}:
        resource["recorder"] = {"display": author}
    elif resource_type == "MedicationStatement":
        resource["informationSource"] = {"display": author}
    elif resource_type == "Procedure":
        resource["performer"] = [{"actor": {"display": author}}]
    elif resource_type == "Encounter":
        resource["participant"] = [{"individual": {"display": author}}]
    else:
        resource[field] = [{"display": author}]
    return resource
