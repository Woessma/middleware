import logging
from parser.cda.constants import NS

from utils.fhir_utils import (
    cda_ts_to_fhir_datetime,
)

AT_NS = NS | {"hl7at": "urn:hl7-at:v3"}
SDTC_NS = "urn:hl7-org:sdtc"


from parser.cda.helpers import (
    text_or_none,
    attr_or_none,
    collect_narrative_texts,
    resolve_reference_text,
)


logger = logging.getLogger(__name__)


def _extract_section_narrative_text(section):
    text_node = section.find("hl7:text", NS)
    if text_node is None:
        return None

    text_value = text_or_none(text_node)
    if text_value:
        return text_value

    reference_node = text_node.find("hl7:reference", NS)
    if reference_node is not None:
        return resolve_reference_text(
            reference_node.attrib.get("value"),
            {}
        )

    return None


def _extract_section_attachments(section):
    attachments = []
    section_title = text_or_none(section.find("hl7:title", NS))

    for observation_media in section.findall(
        "hl7:entry/hl7:observationMedia",
        NS,
    ):
        value_node = observation_media.find("hl7:value", NS)

        if value_node is None:
            continue

        media_type = value_node.attrib.get("mediaType")
        data = text_or_none(value_node)

        if not media_type or not data:
            continue

        attachments.append(
            {
                "id": (
                    observation_media.attrib.get("ID")
                    or observation_media.attrib.get("id")
                ),
                "contentType": media_type,
                "data": data,
                "title": section_title,
            }
        )

    return attachments


def _extract_section_author_time(section):
    author_time_node = section.find("hl7:author/hl7:time", NS)

    if author_time_node is None:
        return None

    return author_time_node.attrib.get("value")


def _extract_quantity_summary(node):
    if node is None:
        return None

    summary = {
        "xsiType": node.attrib.get("{http://www.w3.org/2001/XMLSchema-instance}type"),
        "value": node.attrib.get("value"),
        "unit": node.attrib.get("unit"),
        "nullFlavor": node.attrib.get("nullFlavor"),
    }

    for child_name in ("low", "high", "center", "width"):
        child_node = node.find(f"hl7:{child_name}", NS)

        if child_node is not None:
            summary[child_name] = {
                "value": child_node.attrib.get("value"),
                "nullFlavor": child_node.attrib.get("nullFlavor"),
            }

    return {k: v for k, v in summary.items() if v is not None}


def _extract_node_text(node, narrative_texts):
    if node is None:
        return None

    text_value = text_or_none(node)
    if text_value:
        return text_value

    reference_node = node.find("hl7:reference", NS)
    if reference_node is not None:
        return resolve_reference_text(
            reference_node.attrib.get("value"),
            narrative_texts,
        )

    return None


def _extract_author_times(node):
    author_times = []

    for author_node in node.findall(".//hl7:author", NS):
        time_node = author_node.find("hl7:time", NS)

        if time_node is None:
            continue

        value = time_node.attrib.get("value")
        if value:
            author_times.append(value)

    return author_times


def _extract_author_display(node, author_displays=None):
    displays = []

    for author_node in node.findall(".//hl7:author", NS):
        assigned_author = author_node.find("hl7:assignedAuthor", NS)
        if assigned_author is None:
            continue

        name_node = assigned_author.find(
            "hl7:assignedPerson/hl7:name",
            NS,
        )
        if name_node is not None:
            given = [
                text_or_none(item)
                for item in name_node.findall("hl7:given", NS)
            ]
            family = text_or_none(name_node.find("hl7:family", NS))
            suffix = [
                text_or_none(item)
                for item in name_node.findall("hl7:suffix", NS)
            ]
            display = " ".join(
                value for value in [*given, family, *suffix] if value
            )
            if display:
                displays.append(display)
                continue

        author_ids = [
            item.attrib.get("extension") or item.attrib.get("root")
            for item in assigned_author.findall("hl7:id", NS)
        ]
        author_ids = [value for value in author_ids if value]
        resolved_displays = [
            author_displays[author_id]
            for author_id in author_ids
            if author_displays and author_id in author_displays
        ]
        if resolved_displays:
            displays.extend(dict.fromkeys(resolved_displays))
            continue
        if author_ids:
            displays.append(f"CDA author ID: {' / '.join(author_ids)}")

    unique_displays = list(dict.fromkeys(displays))
    return "; ".join(unique_displays) or None


def _author_display_by_id(root):
    displays = {}
    for author_node in root.findall(".//hl7:author", NS):
        assigned_author = author_node.find("hl7:assignedAuthor", NS)
        name_node = (
            assigned_author.find("hl7:assignedPerson/hl7:name", NS)
            if assigned_author is not None
            else None
        )
        if name_node is None:
            continue
        given = [
            text_or_none(item)
            for item in name_node.findall("hl7:given", NS)
        ]
        family = text_or_none(name_node.find("hl7:family", NS))
        suffix = [
            text_or_none(item)
            for item in name_node.findall("hl7:suffix", NS)
        ]
        display = " ".join(
            value for value in [*given, family, *suffix] if value
        )
        if not display:
            continue
        for id_node in assigned_author.findall("hl7:id", NS):
            for value in (id_node.attrib.get("extension"), id_node.attrib.get("root")):
                if value:
                    displays[value] = display
    return displays


def _extract_medication_relationships(node, narrative_texts):
    relationships = []

    for relationship in node.findall("hl7:entryRelationship", NS):
        relationship_info = {
            "typeCode": relationship.attrib.get("typeCode"),
            "inversionInd": relationship.attrib.get("inversionInd"),
        }

        child = None
        child_type = None

        for candidate_type in ("observation", "act", "supply", "substanceAdministration"):
            candidate = relationship.find(f"hl7:{candidate_type}", NS)

            if candidate is not None:
                child = candidate
                child_type = candidate_type
                break

        if child is None:
            continue

        relationship_info["childType"] = child_type

        id_node = child.find("hl7:id", NS)
        if id_node is not None:
            relationship_info["id"] = {
                "root": id_node.attrib.get("root"),
                "extension": id_node.attrib.get("extension"),
            }

        code_node = child.find("hl7:code", NS)
        if code_node is not None:
            relationship_info["code"] = extract_code(code_node)

        status_node = child.find("hl7:statusCode", NS)
        if status_node is not None:
            relationship_info["statusCode"] = attr_or_none(status_node, "code")

        text_node = child.find("hl7:text", NS)
        text_value = _extract_node_text(text_node, narrative_texts)
        if text_value:
            relationship_info["text"] = text_value

        value_node = child.find("hl7:value", NS)
        if value_node is not None:
            relationship_info["value"] = extract_value(value_node, narrative_texts)

        effective_node = child.find("hl7:effectiveTime", NS)
        if effective_node is not None:
            relationship_info["effectiveTime"] = effective_node.attrib.get("value")

        author_time_node = child.find("hl7:author/hl7:time", NS)
        if author_time_node is not None:
            relationship_info["authorTime"] = author_time_node.attrib.get("value")

        if child_type == "supply":
            quantity_node = child.find("hl7:quantity", NS)
            if quantity_node is not None:
                relationship_info["quantity"] = _extract_quantity_summary(quantity_node)

            repeat_number_node = child.find("hl7:repeatNumber", NS)
            if repeat_number_node is not None:
                relationship_info["repeatNumber"] = repeat_number_node.attrib.get("value")

        if child_type == "substanceAdministration":
            dose_quantity_node = child.find("hl7:doseQuantity", NS)
            if dose_quantity_node is not None:
                relationship_info["doseQuantity"] = _extract_quantity_summary(dose_quantity_node)

            route_code_node = child.find("hl7:routeCode", NS)
            if route_code_node is not None:
                relationship_info["routeCode"] = extract_code(route_code_node)

            administration_unit_code_node = child.find("hl7:administrationUnitCode", NS)
            if administration_unit_code_node is not None:
                relationship_info["administrationUnitCode"] = extract_code(administration_unit_code_node)

        relationships.append(
            {
                k: v
                for k, v in relationship_info.items()
                if v is not None
            }
        )

    return relationships


def _apply_allergy_details(entry_info, target_observation, narrative_texts):
    participant_entity = target_observation.find(
        "hl7:participant/hl7:participantRole/hl7:playingEntity",
        NS
    )

    if participant_entity is not None:
        participant_code_node = participant_entity.find(
            "hl7:code",
            NS
        )

        participant_name_node = participant_entity.find(
            "hl7:name",
            NS
        )

        entry_info["allergen"] = {
            "code": extract_code(
                participant_code_node
            ),
            "name": text_or_none(
                participant_name_node
            )
        }

    reactions = []
    criticality = None
    allergy_status = None
    severity = None

    def _capture_severity(related_observation):
        nonlocal severity

        related_code_node = related_observation.find(
            "hl7:code",
            NS
        )

        related_value_node = related_observation.find(
            "hl7:value",
            NS
        )

        related_text_reference_node = related_observation.find(
            "hl7:text/hl7:reference",
            NS
        )

        related_text = None

        if related_text_reference_node is not None:
            related_text = resolve_reference_text(
                related_text_reference_node.attrib.get("value"),
                narrative_texts
            )

        related_text = related_text or text_or_none(
            related_observation.find("hl7:text", NS)
        )

        related_code = extract_code(
            related_code_node
        )

        related_value = extract_value(
            related_value_node,
            narrative_texts
        )

        if related_text:
            if related_value is None:
                related_value = {}

            if not related_value.get("displayName"):
                related_value["displayName"] = related_text

            if not related_value.get("text"):
                related_value["text"] = related_text

        for child_relationship in related_observation.findall(
            "hl7:entryRelationship",
            NS
        ):
            child_observation = child_relationship.find(
                "hl7:observation",
                NS
            )

            if child_observation is None:
                continue

            child_code, child_value, child_text = _capture_severity(
                child_observation
            )

            if child_code and child_code.get("code") == "SEV":
                severity = child_value

                if child_text and severity is not None:
                    if not severity.get("displayName"):
                        severity["displayName"] = child_text

                    if not severity.get("text"):
                        severity["text"] = child_text

        if related_code and related_code.get("code") == "SEV":
            severity = related_value

            if related_text and severity is not None:
                if not severity.get("displayName"):
                    severity["displayName"] = related_text

                if not severity.get("text"):
                    severity["text"] = related_text

        if related_text and not severity and related_code and related_code.get("code") != "SEV":
            text_lower = related_text.lower()
            if "hoch" in text_lower or "high" in text_lower:
                severity = {
                    "code": "24484000",
                    "displayName": "High",
                    "text": "High"
                }
            elif "mittel" in text_lower or "moderate" in text_lower:
                severity = {
                    "code": "255604002",
                    "displayName": "Moderate",
                    "text": "Moderate"
                }
            elif "leicht" in text_lower or "mild" in text_lower:
                severity = {
                    "code": "255604002",
                    "displayName": "Mild",
                    "text": "Mild"
                }

        return related_code, related_value, related_text

    for relationship in target_observation.findall(
        "hl7:entryRelationship",
        NS
    ):
        relationship_type = relationship.attrib.get(
            "typeCode"
        )

        related_observation = relationship.find(
            "hl7:observation",
            NS
        )

        if related_observation is None:
            continue

        related_code, related_value, related_text = _capture_severity(
            related_observation
        )

        related_effective_raw = None
        related_effective_node = related_observation.find(
            "hl7:effectiveTime",
            NS
        )

        if related_effective_node is not None:
            related_low_node = related_effective_node.find(
                "hl7:low",
                NS
            )

            related_effective_raw = (
                related_effective_node.attrib.get("value")
            )

            if related_low_node is not None:
                related_effective_raw = (
                    related_low_node.attrib.get("value")
                    or related_effective_raw
                )

        if relationship_type == "MFST":
            reaction_entry = {
                "code": related_code,
                "value": related_value,
                "effectiveTime": related_effective_raw,
                "effectiveDateTime": cda_ts_to_fhir_datetime(
                    related_effective_raw
                )
            }

            if related_text:
                reaction_entry["text"] = related_text

            reactions.append(reaction_entry)

        elif related_code and related_code.get("code") == "82606-5":
            criticality = related_value

        elif related_code and related_code.get("code") == "33999-4":
            allergy_status = related_value

        elif (
            related_code
            and related_code.get("code") == "SEV"
        ):
            severity = related_value

            if related_text and severity is not None:
                if not severity.get("displayName"):
                    severity["displayName"] = related_text

                if not severity.get("text"):
                    severity["text"] = related_text

        elif relationship_type == "SEV":
            severity = related_value

    if reactions:
        entry_info["reactions"] = reactions

    if criticality:
        entry_info["criticality"] = criticality

    if allergy_status:
        entry_info["allergyStatus"] = allergy_status

    if severity:
        entry_info["severity"] = severity


def extract_sections(root):
    sections = []
    author_displays = _author_display_by_id(root)

    section_candidates = []

    section_candidates.extend(
        root.findall(".//hl7:structuredBody//hl7:section", NS)
    )

    if not section_candidates:
        section_candidates.extend(
            root.findall(".//hl7at:structuredBody//hl7:section", AT_NS)
        )

    for section in section_candidates:
        narrative_texts = collect_narrative_texts(section)
        section_title = section.find("hl7:title", NS)
        section_code = section.find("hl7:code", NS)
 
        section_code_obj = extract_code(section_code)
        section_code_value = None
 
        if section_code_obj:
            section_code_value = section_code_obj.get("code")
 
        template_ids = []
 
        for template in section.findall("hl7:templateId", NS):
            template_ids.append(
                {
                    "root": template.attrib.get("root"),
                    "extension": template.attrib.get("extension")
                }
            )
 
        entries = []
 
        # Wichtig:
        # Nur direkte entry-Knoten lesen.
        # Nicht ".//hl7:entry", sonst werden verschachtelte entryRelationship-
        # Entries als eigene Section Entries gezählt.
        for entry in section.findall("hl7:entry", NS):
            entry_info = extract_entry_summary(
                entry,
                section_code_value,
                narrative_texts,
                author_displays,
            )
 
            if entry_info:
                entries.append(entry_info)
 
        section_narrative_text = _extract_section_narrative_text(section)
        section_attachments = _extract_section_attachments(section)
        section_author_time = _extract_section_author_time(section)

        sections.append(
            {
                "title": text_or_none(section_title),
                "code": section_code_obj,
                "templateIds": template_ids,
                "entryCount": len(entries),
                "entries": entries,
                "narrativeText": section_narrative_text,
                "attachments": section_attachments,
                "authorTime": section_author_time,
            }
        )
 
    return sections

def extract_entry_summary(
    entry,
    section_code=None,
    narrative_texts=None,
    author_displays=None,
):
    """
    Extrahiert den klinischen Hauptknoten aus einem CDA <entry>.
 
    Wichtig:
    - Nicht rekursiv mit .// suchen, sonst werden entryRelationship-
      Observations statt der eigentlichen klinischen Statements gefunden.
    - Für Medication Section 10160-0 bevorzugt substanceAdministration.
    """
    if narrative_texts is None:
        narrative_texts = {}

    section_author_time = None

    if section_code == "10160-0":
        candidate_paths = [
            "hl7:substanceAdministration",
            "hl7:supply",
            "hl7:act",
            "hl7:observation",
            "hl7:procedure",
            "hl7:encounter",
            "hl7:organizer"
        ]
    else:
        candidate_paths = [
            "hl7:observation",
            "hl7:act",
            "hl7:substanceAdministration",
            "hl7:procedure",
            "hl7:encounter",
            "hl7:organizer",
            "hl7:supply"
        ]
 
    for path in candidate_paths:
        node = entry.find(path, NS)
 
        if node is None:
            continue
 
        code_node = node.find("hl7:code", NS)
        status_node = node.find("hl7:statusCode", NS)
        value_node = node.find("hl7:value", NS)
 
        template_ids = []
 
        for template in node.findall("hl7:templateId", NS):
            template_ids.append(
                {
                    "root": template.attrib.get("root"),
                    "extension": template.attrib.get("extension")
                }
            )
 
        effective_times = []
 
        for effective_time_node in node.findall("hl7:effectiveTime", NS):
            item = {
                "value": effective_time_node.attrib.get("value"),
                "xsiType": effective_time_node.attrib.get(
                    "{http://www.w3.org/2001/XMLSchema-instance}type"
                ),
                "operator": effective_time_node.attrib.get("operator"),
                "institutionSpecified": effective_time_node.attrib.get(
                    "institutionSpecified"
                )
            }
 
            low_node = effective_time_node.find("hl7:low", NS)
            high_node = effective_time_node.find("hl7:high", NS)
            period_node = effective_time_node.find("hl7:period", NS)
 
            if low_node is not None:
                item["low"] = low_node.attrib.get("value")
                if low_node.attrib.get("nullFlavor"):
                    item["lowNullFlavor"] = low_node.attrib.get("nullFlavor")
 
            if high_node is not None:
                item["high"] = high_node.attrib.get("value")
                if high_node.attrib.get("nullFlavor"):
                    item["highNullFlavor"] = high_node.attrib.get("nullFlavor")
 
            if period_node is not None:
                item["period"] = {
                    "value": period_node.attrib.get("value"),
                    "unit": period_node.attrib.get("unit")
                }
 
            effective_times.append(
                {k: v for k, v in item.items() if v is not None}
            )
 
        effective_raw = None
 
        if effective_times:
            effective_raw = (
                effective_times[0].get("value")
                or effective_times[0].get("low")
            )

        id_node = node.find("hl7:id", NS)

        entry_id = None

        if id_node is not None:
            entry_id = {
                "root": id_node.attrib.get("root"),
                "extension": id_node.attrib.get("extension")
            }
 
        entry_info = {
            "type": node.tag.split("}")[-1],
            "id": entry_id,
            "classCode": node.attrib.get("classCode"),
            "moodCode": node.attrib.get("moodCode"),
            "templateIds": template_ids,
            "code": extract_code(code_node),
            "statusCode": attr_or_none(status_node, "code"),
            "effectiveTime": effective_raw,
            "effectiveTimes": effective_times,
            "effectiveDateTime": cda_ts_to_fhir_datetime(
                effective_raw
            ),
            "value": extract_value(
                value_node,
                narrative_texts
            )
        }

        author_times = _extract_author_times(node)
        if author_times:
            entry_info["authorTimes"] = author_times

        author_display = _extract_author_display(node, author_displays)
        if not author_display and author_displays:
            author_ids = [
                id_node.attrib.get("extension") or id_node.attrib.get("root")
                for id_node in node.findall(
                    ".//hl7:assignedAuthor/hl7:id",
                    NS,
                )
            ]
            author_display = "; ".join(
                dict.fromkeys(
                    author_displays[author_id]
                    for author_id in author_ids
                    if author_id in author_displays
                )
            ) or None
        if author_display:
            entry_info["authorDisplay"] = author_display

        if section_author_time is not None:
            entry_info["sectionAuthorTime"] = section_author_time

        #
        # Organizer -> Component -> Observation
        #
        if node.tag.endswith("organizer"):

            participants = []
            for participant in node.findall("hl7:participant", NS):
                function_node = participant.find("hl7:functionCode", NS)
                if function_node is None:
                    function_node = participant.find(f"{{{SDTC_NS}}}functionCode")
                role_node = participant.find("hl7:participantRole", NS)
                role_id = role_node.find("hl7:id", NS) if role_node is not None else None
                if function_node is None and role_id is None:
                    continue
                participants.append({
                    "typeCode": participant.attrib.get("typeCode"),
                    "function": extract_code(function_node),
                    "identifier": {
                        "system": f"urn:oid:{role_id.attrib.get('root')}",
                        "value": role_id.attrib.get("extension"),
                    } if role_id is not None and role_id.attrib.get("extension") else None,
                })
            if participants:
                entry_info["participants"] = participants

            components = []

            for component in node.findall(
                "hl7:component",
                NS
            ):

                observation = component.find(
                    "hl7:observation",
                    NS
                )

                if observation is None:
                    continue

                observation_code = extract_code(
                    observation.find(
                        "hl7:code",
                        NS
                    )
                )

                observation_value = extract_value(
                    observation.find(
                        "hl7:value",
                        NS
                    ),
                    narrative_texts
                )

                observation_effective = None

                effective_node = observation.find(
                    "hl7:effectiveTime",
                    NS
                )

                if effective_node is not None:
                    observation_effective = (
                        effective_node.attrib.get("value")
                    )

                components.append(
                    {
                        "type": "observation",
                        "code": observation_code,
                        "value": observation_value,
                        "effectiveTime": observation_effective,
                        "effectiveDateTime": (
                            cda_ts_to_fhir_datetime(
                                observation_effective
                            )
                        )
                    }
                )

            entry_info["components"] = components
        #
        # Act -> nested Observation (Allergy / Condition)
        #
        if node.tag.endswith("act"):

            nested_observation = node.find(
                "hl7:entryRelationship/hl7:observation",
                NS
            )

            if nested_observation is not None:

                nested_code_node = nested_observation.find(
                    "hl7:code",
                    NS
                )

                nested_value_node = nested_observation.find(
                    "hl7:value",
                    NS
                )

                nested_status_node = nested_observation.find(
                    "hl7:statusCode",
                    NS
                )

                nested_effective_times = []

                for nested_effective_time_node in nested_observation.findall(
                    "hl7:effectiveTime",
                    NS
                ):
                    nested_item = {
                        "value": nested_effective_time_node.attrib.get("value"),
                        "xsiType": nested_effective_time_node.attrib.get(
                            "{http://www.w3.org/2001/XMLSchema-instance}type"
                        ),
                        "operator": nested_effective_time_node.attrib.get(
                            "operator"
                        ),
                        "institutionSpecified": nested_effective_time_node.attrib.get(
                            "institutionSpecified"
                        )
                    }

                    nested_low_node = nested_effective_time_node.find(
                        "hl7:low",
                        NS
                    )

                    nested_high_node = nested_effective_time_node.find(
                        "hl7:high",
                        NS
                    )

                    if nested_low_node is not None:
                        nested_item["low"] = nested_low_node.attrib.get(
                            "value"
                        )

                    if nested_high_node is not None:
                        nested_item["high"] = nested_high_node.attrib.get(
                            "value"
                        )

                    nested_effective_times.append(
                        {
                            k: v
                            for k, v in nested_item.items()
                            if v is not None
                        }
                    )

                nested_effective_raw = None

                if nested_effective_times:
                    nested_effective_raw = (
                        nested_effective_times[0].get("value")
                        or nested_effective_times[0].get("low")
                    )

                nested_text = None

                nested_text_reference_node = nested_observation.find(
                    "hl7:text/hl7:reference",
                    NS
                )

                if nested_text_reference_node is not None:
                    nested_text = resolve_reference_text(
                        nested_text_reference_node.attrib.get("value"),
                        narrative_texts
                    )

                entry_info["nestedObservation"] = {
                    "type": "observation",
                    "classCode": nested_observation.attrib.get(
                        "classCode"
                    ),
                    "moodCode": nested_observation.attrib.get(
                        "moodCode"
                    ),
                    "code": extract_code(
                        nested_code_node
                    ),
                    "statusCode": attr_or_none(
                        nested_status_node,
                        "code"
                    ),
                    "effectiveTime": nested_effective_raw,
                    "effectiveTimes": nested_effective_times,
                    "effectiveDateTime": cda_ts_to_fhir_datetime(
                        nested_effective_raw
                    ),
                    "text": nested_text,
                    "value": extract_value(
                        nested_value_node,
                        narrative_texts
                    )
                }

                _apply_allergy_details(entry_info, node, narrative_texts)
                _apply_allergy_details(entry_info, nested_observation, narrative_texts)

                logger.debug("FOUND NESTED OBSERVATION")

                logger.debug("%s", entry_info["nestedObservation"])

        elif node.tag.endswith("observation"):
            _apply_allergy_details(entry_info, node, narrative_texts)
 

        if node.tag.endswith("substanceAdministration"):
            consumable_node = node.find(
                "hl7:consumable/hl7:manufacturedProduct/hl7:manufacturedMaterial",
                NS
            )
 
            material_code_node = None
            material_name = None
 
            if consumable_node is not None:
                material_code_node = consumable_node.find("hl7:code", NS)
                name_node = consumable_node.find("hl7:name", NS)
                material_name = text_or_none(name_node)
                original_text_reference = None
                medication_text = None
            
                if material_code_node is not None:
                    original_text_ref_node = material_code_node.find(
                        "hl7:originalText/hl7:reference",
                        NS
                    )
            
                    if original_text_ref_node is not None:
                        original_text_reference = original_text_ref_node.attrib.get(
                            "value"
                        )
            
                        medication_text = resolve_reference_text(
                            original_text_reference,
                            narrative_texts
                        )
 

            dose_quantity_node = node.find("hl7:doseQuantity", NS)
            rate_quantity_node = node.find("hl7:rateQuantity", NS)
            route_code_node = node.find("hl7:routeCode", NS)
            administration_unit_code_node = node.find("hl7:administrationUnitCode", NS)
            quantity_node = None
            repeat_number_node = None
            text_node = node.find("hl7:text", NS)

            if dose_quantity_node is not None:
                entry_info["doseQuantity"] = _extract_quantity_summary(dose_quantity_node)

            if rate_quantity_node is not None:
                entry_info["rateQuantity"] = _extract_quantity_summary(rate_quantity_node)

            if route_code_node is not None:
                entry_info["routeCode"] = extract_code(route_code_node)

            if administration_unit_code_node is not None:
                entry_info["administrationUnitCode"] = extract_code(administration_unit_code_node)

            for relationship in node.findall("hl7:entryRelationship", NS):
                relationship_type = relationship.attrib.get("typeCode")

                if relationship_type == "REFR":
                    supply_node = relationship.find("hl7:supply", NS)
                    if supply_node is not None:
                        quantity_node = supply_node.find("hl7:quantity", NS)
                        repeat_number_node = supply_node.find("hl7:repeatNumber", NS)

                        if quantity_node is not None:
                            entry_info["quantity"] = _extract_quantity_summary(quantity_node)

                        if repeat_number_node is not None:
                            entry_info["originalRefills"] = repeat_number_node.attrib.get("value")

                if relationship_type == "COMP":
                    child_substance = relationship.find("hl7:substanceAdministration", NS)
                    if child_substance is not None:
                        child_code_node = child_substance.find("hl7:code", NS)
                        child_text_node = child_substance.find("hl7:text", NS)
                        child_text = _extract_node_text(child_text_node, narrative_texts)

                        if child_code_node is not None and child_code_node.attrib.get("code") == "76662-6" and child_text:
                            entry_info["directionsText"] = child_text

                if relationship_type == "SUBJ":
                    child_act = relationship.find("hl7:act", NS)
                    if child_act is not None:
                        child_code_node = child_act.find("hl7:code", NS)
                        child_text_node = child_act.find("hl7:text", NS)
                        child_text = _extract_node_text(child_text_node, narrative_texts)

                        if child_code_node is not None:
                            child_code = extract_code(child_code_node)
                            if child_code and child_code.get("code") == "48767-8" and child_text:
                                entry_info.setdefault("comments", []).append(child_text)

                        if child_text:
                            entry_info.setdefault("patientInstructions", []).append(child_text)

                if relationship_type == "PRCN":
                    criterion = relationship.find("hl7:criterion", NS)
                    if criterion is not None:
                        criterion_value = extract_value(
                            criterion.find("hl7:value", NS),
                            narrative_texts,
                        )
                        if criterion_value:
                            entry_info.setdefault("prnReasons", []).append(criterion_value)

            entry_relationships = _extract_medication_relationships(node, narrative_texts)
            if entry_relationships:
                entry_info["entryRelationships"] = entry_relationships

            if not entry_info.get("directionsText"):
                node_text_value = _extract_node_text(text_node, narrative_texts)
                if node_text_value:
                    entry_info["directionsText"] = node_text_value
 
            if material_code_node is not None or material_name:
                medication_code = extract_code(material_code_node)
 
                if medication_code is None:
                    medication_code = {}
 
                if material_name and not medication_code.get("displayName"):
                    medication_code["displayName"] = material_name
                
                if medication_text:
                    medication_code["displayName"] = medication_text
                    medication_code["originalText"] = medication_text

                if medication_code.get("originalText") and not entry_info.get("directionsText"):
                    entry_info["medicationNameOriginalText"] = medication_code["originalText"]
 
                entry_info["consumable"] = {
                    "code": medication_code
                }
 
            lot_number_node = consumable_node.find(
                "hl7:lotNumberText",
                NS
            ) if consumable_node is not None else None

            if lot_number_node is not None:
                entry_info["lotNumber"] = text_or_none(lot_number_node)

            manufacturer_name_node = consumable_node.find(
                "hl7:manufacturerOrganization/hl7:name",
                NS
            ) if consumable_node is not None else None

            if manufacturer_name_node is not None:
                manufacturer_name = text_or_none(manufacturer_name_node)
                if manufacturer_name:
                    entry_info["manufacturer"] = manufacturer_name

            if text_node is not None:
            
                text_value = text_or_none(text_node)
            
                reference_node = text_node.find(
                    "hl7:reference",
                    NS
                )
            
                if reference_node is not None:
            
                    reference_value = reference_node.attrib.get(
                        "value"
                    )
            
                    dosage_text = resolve_reference_text(
                        reference_value,
                        narrative_texts
                    )
            
                    if dosage_text:
                        entry_info["dosageText"] = dosage_text
            
                if text_value:
                    entry_info["text"] = text_value

            if not entry_info.get("authorTimes"):
                entry_info["authorTimes"] = _extract_author_times(node)

            if not entry_info.get("authorDisplay"):
                entry_info["authorDisplay"] = _extract_author_display(
                    node,
                    author_displays,
                )

        if node.tag.endswith("substanceAdministration"):
            nested_directions = entry_info.get("directionsText")
            if nested_directions:
                entry_info["dosageText"] = nested_directions

            if not entry_info.get("entryRelationships"):
                entry_info["entryRelationships"] = _extract_medication_relationships(
                    node,
                    narrative_texts,
                )
 
 
        return entry_info
 
    return None
def extract_code(element, narrative_texts=None):
    if element is None:
        return None

    if narrative_texts is None:
        narrative_texts = {}

    result = {
        "code": element.attrib.get("code"),
        "codeSystem": element.attrib.get("codeSystem"),
        "codeSystemName": element.attrib.get("codeSystemName"),
        "displayName": element.attrib.get("displayName"),
        "nullFlavor": element.attrib.get("nullFlavor"),
    }

    # PROC-CDA-01: Resolve narrative references so medication text survives when code is nullFlavor/UNK.
    original_text_ref_node = element.find(
        "hl7:originalText/hl7:reference",
        NS,
    )

    if original_text_ref_node is not None:
        resolved_text = resolve_reference_text(
            original_text_ref_node.attrib.get("value"),
            narrative_texts,
        )

        if resolved_text:
            result["originalText"] = resolved_text

            if not result.get("displayName"):
                result["displayName"] = resolved_text

    translations = []

    # PROC-CDA-02: Capture translation codings (for example SNOMED) for downstream FHIR coding.
    for translation_node in element.findall("hl7:translation", NS):
        translations.append(
            {
                "code": translation_node.attrib.get("code"),
                "codeSystem": translation_node.attrib.get("codeSystem"),
                "codeSystemName": translation_node.attrib.get("codeSystemName"),
                "displayName": translation_node.attrib.get("displayName"),
            }
        )

    if translations:
        result["translations"] = [
            {
                k: v
                for k, v in item.items()
                if v is not None
            }
            for item in translations
        ]

    return {
        k: v
        for k, v in result.items()
        if v is not None
    }

def extract_value(value_node, narrative_texts=None):
    if value_node is None:
        return None
 
    if narrative_texts is None:
        narrative_texts = {}
 
    value = {
        "xsiType": value_node.attrib.get(
            "{http://www.w3.org/2001/XMLSchema-instance}type"
        ),
        "code": value_node.attrib.get("code"),
        "codeSystem": value_node.attrib.get("codeSystem"),
        "codeSystemName": value_node.attrib.get("codeSystemName"),
        "displayName": value_node.attrib.get("displayName"),
        "value": value_node.attrib.get("value"),
        "unit": value_node.attrib.get("unit"),
        "nullFlavor": value_node.attrib.get("nullFlavor")
    }
 
    text_value = text_or_none(value_node)
 
    if text_value:
        value["text"] = text_value
 
    original_text_reference_node = value_node.find(
        "hl7:originalText/hl7:reference",
        NS
    )
 
    if original_text_reference_node is not None:
        reference_value = original_text_reference_node.attrib.get("value")
 
        resolved_text = resolve_reference_text(
            reference_value,
            narrative_texts
        )
 
        if resolved_text:
            value["originalText"] = resolved_text
 
            if not value.get("displayName"):
                value["displayName"] = resolved_text
 
            if not value.get("text"):
                value["text"] = resolved_text
 
    return {
        k: v
        for k, v in value.items()
        if v is not None
    }