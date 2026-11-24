import json
import os
import re
from functools import lru_cache
from pathlib import Path

try:
    from openpyxl import load_workbook
except Exception:  # pragma: no cover
    load_workbook = None


COMPENDIUM_SEARCH_URL = "https://compendium.ch/de/search"


def _default_mapping_path(env_name, current_filename, legacy_filename):
    configured_path = os.getenv(env_name)
    if configured_path:
        return configured_path

    data_dirs = (
        "/app/terminology/data",
        os.path.join(os.path.dirname(__file__), "data"),
    )
    candidates = [
        *(os.path.join(directory, current_filename) for directory in data_dirs),
        *(os.path.join(directory, legacy_filename) for directory in data_dirs),
    ]
    return next((path for path in candidates if os.path.exists(path)), candidates[0])


DEFAULT_PHARMACODE_XLSX = _default_mapping_path(
    "EMEDIPLAN_PHARMACODE_XLSX",
    "MappingPharmacodeToGtinToSwissmedicDescription.xlsx",
    "20260901__MappingPharmacodeToGtinToSwissmedicDescription.xlsx",
)
DEFAULT_PRODUCTNUMBER_XLSX = _default_mapping_path(
    "EMEDIPLAN_PRODUCTNUMBER_XLSX",
    "MappingProductNumberToSwissmedicDescription.xlsx",
    "20260701__MappingProductNumberToSwissmedicDescription.xlsx",
)


def _clean(value):
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _normalize_header(header):
    if header is None:
        return ""

    return (
        str(header)
        .strip()
        .lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
    )


def _select_column(header_index, *candidates):
    for candidate in candidates:
        normalized = _normalize_header(candidate)

        if normalized in header_index:
            return header_index[normalized]

    return None


def _iter_rows_from_xlsx(path):
    if not path or not os.path.exists(path):
        return []

    if load_workbook is None:
        return []

    workbook = load_workbook(path, data_only=True, read_only=True)

    try:
        sheet = workbook.active
        rows = list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()

    if not rows:
        return []

    headers = rows[0]
    header_index = {
        _normalize_header(name): idx
        for idx, name in enumerate(headers)
        if _normalize_header(name)
    }

    return rows[1:], header_index


def _mapping_source_pairs():
    data_dir = Path(
        os.getenv("EMEDIPLAN_MAPPING_DATA_DIR", "/var/lib/omnilink/emediplan")
    )
    archive_dir = data_dir / "archive"
    current_manifest = data_dir / "current.json"
    active_version = None

    if current_manifest.is_file():
        try:
            manifest = json.loads(current_manifest.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("manifest must be an object")
            active_version = str(manifest["version"])
        except (
            OSError,
            KeyError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
        ) as exc:
            raise RuntimeError("eMediplan-Mapping current.json ist ungültig") from exc
        if not re.fullmatch(r"\d{8}", active_version):
            raise RuntimeError("eMediplan-Mapping-Version in current.json ist ungültig")

    versions = []
    if active_version and archive_dir.is_dir():
        versions = sorted(
            path.name
            for path in archive_dir.iterdir()
            if path.is_dir()
            and re.fullmatch(r"\d{8}", path.name)
            and path.name <= active_version
        )
    bundled_archive = archive_dir / "bundled"
    if bundled_archive.exists():
        bundled_pharmacode = bundled_archive / (
            "MappingPharmacodeToGtinToSwissmedicDescription.xlsx"
        )
        bundled_productnumber = bundled_archive / (
            "MappingProductNumberToSwissmedicDescription.xlsx"
        )
        if not bundled_pharmacode.is_file() or not bundled_productnumber.is_file():
            raise RuntimeError("Das eMediplan-Basisarchiv ist unvollständig")
    else:
        bundled_pharmacode = None
        bundled_productnumber = None

    if active_version and active_version not in versions:
        raise RuntimeError(
            f"Aktives eMediplan-Mapping-Archiv {active_version} fehlt"
        )

    sources = []
    if bundled_pharmacode and bundled_productnumber:
        sources.append((str(bundled_pharmacode), str(bundled_productnumber)))
    for version in versions:
        version_dir = archive_dir / version
        pharmacode_path = version_dir / (
            f"{version}__MappingPharmacodeToGtinToSwissmedicDescription.xlsx"
        )
        productnumber_path = version_dir / (
            f"{version}__MappingProductNumberToSwissmedicDescription.xlsx"
        )
        if (
            not pharmacode_path.is_file()
            or not productnumber_path.is_file()
            or not (version_dir / "manifest.json").is_file()
        ):
            raise RuntimeError(
                f"eMediplan-Mapping-Archiv {version} ist unvollständig"
            )
        sources.append((str(pharmacode_path), str(productnumber_path)))
    if not sources:
        raise RuntimeError("Kein persistentes eMediplan-Mapping-Archiv vorhanden")
    return sources


@lru_cache(maxsize=64)
def _load_mapping_files(pharmacode_path, productnumber_path):
    mapping = {
        "pharmacode": {},
        "product_number": {},
        "gtin": {},
    }

    parsed = _iter_rows_from_xlsx(pharmacode_path)

    if parsed:
        rows, header_index = parsed

        pharmacode_col = _select_column(header_index, "Pharmacode")
        gtin_col = _select_column(header_index, "GTIN")
        product_number_col = _select_column(
            header_index,
            "Swissmedic-Nr + Packungscode",
            "SwissmedicNr+Packungscode",
            "ProductNumber",
            "PrdNr",
        )
        description_col = _select_column(
            header_index,
            "Swissmedic Bezeichnung des Arzneimittels",
            "SwissmedicDescription",
            "Description",
        )
        form_col = _select_column(
            header_index,
            "Form",
            "DosageForm",
            "GalenicForm",
            "Darreichungsform",
        )
        ingredient_col = _select_column(
            header_index,
            "Ingredient",
            "ActiveIngredient",
            "Wirkstoff",
            "Substance",
        )
        strength_col = _select_column(
            header_index,
            "Strength",
            "Stength",
            "Starke",
            "Stärke",
            "DosageStrength",
        )
        atc_col = _select_column(header_index, "ATC")
        dispensing_category_col = _select_column(
            header_index,
            "Abgabekategorie",
            "DispensingCategory",
        )

        for row in rows:
            pharmacode = _clean(row[pharmacode_col]) if pharmacode_col is not None else None
            gtin = _clean(row[gtin_col]) if gtin_col is not None else None
            product_number = (
                _clean(row[product_number_col]) if product_number_col is not None else None
            )
            description = (
                _clean(row[description_col]) if description_col is not None else None
            )
            form = _clean(row[form_col]) if form_col is not None else None
            ingredient = _clean(row[ingredient_col]) if ingredient_col is not None else None
            strength = _clean(row[strength_col]) if strength_col is not None else None
            atc = _clean(row[atc_col]) if atc_col is not None else None
            dispensing_category = (
                _clean(row[dispensing_category_col])
                if dispensing_category_col is not None
                else None
            )

            row_data = {
                "gtin": gtin,
                "product_number": product_number,
                "description": description,
                "form": form,
                "ingredient": ingredient,
                "strength": strength,
                "atc": atc,
                "dispensing_category": dispensing_category,
            }

            if pharmacode:
                mapping["pharmacode"][pharmacode] = row_data

            if gtin:
                mapping["gtin"][gtin] = row_data

            if product_number:
                mapping["product_number"].setdefault(product_number, row_data)

    parsed = _iter_rows_from_xlsx(productnumber_path)

    if parsed:
        rows, header_index = parsed

        product_number_col = _select_column(
            header_index,
            "Swissmedic-Nr + Packungscode",
            "SwissmedicNr+Packungscode",
            "ProductNumber",
            "PrdNr",
        )
        description_col = _select_column(
            header_index,
            "Swissmedic Bezeichnung des Arzneimittels",
            "SwissmedicDescription",
            "Description",
        )
        gtin_col = _select_column(header_index, "GTIN")
        form_col = _select_column(
            header_index,
            "Form",
            "DosageForm",
            "GalenicForm",
            "Darreichungsform",
        )
        ingredient_col = _select_column(
            header_index,
            "Ingredient",
            "ActiveIngredient",
            "Wirkstoff",
            "Substance",
        )
        strength_col = _select_column(
            header_index,
            "Strength",
            "Stength",
            "Starke",
            "Stärke",
            "DosageStrength",
        )
        atc_col = _select_column(header_index, "ATC")
        dispensing_category_col = _select_column(
            header_index,
            "Abgabekategorie",
            "DispensingCategory",
        )

        for row in rows:
            product_number = (
                _clean(row[product_number_col]) if product_number_col is not None else None
            )
            description = (
                _clean(row[description_col]) if description_col is not None else None
            )
            gtin = _clean(row[gtin_col]) if gtin_col is not None else None
            form = _clean(row[form_col]) if form_col is not None else None
            ingredient = _clean(row[ingredient_col]) if ingredient_col is not None else None
            strength = _clean(row[strength_col]) if strength_col is not None else None
            atc = _clean(row[atc_col]) if atc_col is not None else None
            dispensing_category = (
                _clean(row[dispensing_category_col])
                if dispensing_category_col is not None
                else None
            )

            row_data = {
                "gtin": gtin,
                "product_number": product_number,
                "description": description,
                "form": form,
                "ingredient": ingredient,
                "strength": strength,
                "atc": atc,
                "dispensing_category": dispensing_category,
            }

            if product_number:
                mapping["product_number"][product_number] = row_data

            if gtin:
                mapping["gtin"].setdefault(gtin, row_data)

    return mapping


@lru_cache(maxsize=1)
def _load_mapping():
    mapping = {
        "pharmacode": {},
        "product_number": {},
        "gtin": {},
    }

    # Older publications are loaded first; the newest archive overrides them.
    for pharmacode_path, productnumber_path in _mapping_source_pairs():
        source_mapping = _load_mapping_files(pharmacode_path, productnumber_path)
        for identifier_type, entries in source_mapping.items():
            mapping[identifier_type].update(entries)

    return mapping


def invalidate_medication_mapping_cache():
    _load_mapping.cache_clear()
    _load_mapping_files.cache_clear()


def resolve_medication_identity(id_type, raw_id):
    med_id = _clean(raw_id)

    if not med_id:
        return {
            "id": None,
            "id_type": id_type,
            "display": None,
            "gtin": None,
            "product_number": None,
            "form": None,
            "ingredient": None,
            "strength": None,
            "atc": None,
            "dispensing_category": None,
            "source": None,
        }

    mapping = _load_mapping()

    if id_type == 3:
        found = mapping["pharmacode"].get(med_id) or {}
    elif id_type == 4:
        found = mapping["product_number"].get(med_id) or {}
    elif id_type == 2:
        found = mapping["gtin"].get(med_id) or {}
    else:
        found = {}

    resolved_id = med_id
    resolved_type = id_type

    # Prefer canonical GTIN if known.
    gtin = _clean(found.get("gtin"))
    if gtin:
        resolved_id = gtin
        resolved_type = 2

    source_reference = f"{COMPENDIUM_SEARCH_URL}?q={med_id}&type=Default"

    return {
        "id": resolved_id,
        "id_type": resolved_type,
        "display": _clean(found.get("description")),
        "gtin": gtin,
        "product_number": _clean(found.get("product_number")),
        "form": _clean(found.get("form")),
        "ingredient": _clean(found.get("ingredient")),
        "strength": _clean(found.get("strength")),
        "atc": _clean(found.get("atc")),
        "dispensing_category": _clean(found.get("dispensing_category")),
        "source": {
            "system": "https://compendium.ch",
            "reference": source_reference,
            "display": "Compendium",
        },
    }
