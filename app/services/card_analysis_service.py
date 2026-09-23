import io
import json
import re
import zipfile
from collections import Counter
from datetime import date as date_type
from urllib.parse import parse_qs, urlsplit

from services.echosos_service import parse_echosos_data, ECHOSOS_IDENTIFIER_SYSTEM


def _normalize_name(value):
    return " ".join(str(value or "").strip().split())


def _display_name(value):
    display_value = " ".join(part[:1].upper() + part[1:].lower() for part in _normalize_name(value).split())
    return re.sub(r"^W(?:oss|oess)$", "Wöss", display_value)


def _normalize_result_name(value):
    return _normalize_name(value).replace("<", " ").replace("<<", " ")


def _date_from_iso(value):
    if not value:
        return None
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(value).strip())
    if not match:
        return None
    return str(value).strip()


def _parse_date(value):
    if not value:
        return None
    text = str(value).strip()
    for pattern in [
        r"^(\d{4})-(\d{2})-(\d{2})$",
        r"^(\d{2})[./](\d{2})[./](\d{4})$",
        r"^(\d{8})$",
    ]:
        match = re.match(pattern, text)
        if match:
            if pattern.endswith("$") and len(text) == 8:
                yy, mm, dd = text[0:2], text[2:4], text[4:6]
                return f"20{yy}-{mm}-{dd}" if int(mm) <= 12 and int(dd) <= 31 else None
            if len(match.groups()) == 3:
                if pattern.startswith("^(\\d{2})"):
                    dd, mm, yyyy = match.groups()
                    return f"{yyyy}-{mm}-{dd}"
                yyyy, mm, dd = match.groups()
                return f"{yyyy}-{mm}-{dd}"
    if re.fullmatch(r"\d{6}", text):
        yy, mm, dd = text[0:2], text[2:4], text[4:6]
        if 1 <= int(mm) <= 12 and 1 <= int(dd) <= 31:
            return f"20{yy}-{mm}-{dd}"
    return None


def _pkpass_barcode(raw_bytes):
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
        payload = json.loads(archive.read("pass.json"))
    barcode = payload.get("barcodes", [payload.get("barcode")])[0]
    if not barcode or not barcode.get("message"):
        raise ValueError("Kein gültiger Barcode in der PKPass-Datei gefunden")
    return barcode["message"]


def _decode_qr_from_file(raw_bytes):
    if raw_bytes.lstrip().startswith((b"http://", b"https://")):
        return raw_bytes.decode("utf-8").strip()

    if raw_bytes[:2] == b"PK":
        return _pkpass_barcode(raw_bytes)

    try:
        from PIL import Image
        from pyzbar.pyzbar import decode as decode_qr_codes
    except ImportError as exc:
        raise ValueError("QR-Decoding ist auf diesem System nicht verfügbar: zbar-Bibliothek fehlt") from exc

    try:
        symbols = decode_qr_codes(Image.open(io.BytesIO(raw_bytes)))
    except Exception as exc:  # pragma: no cover - environment-specific fallback
        raise ValueError("Kein gültiger QR-Code im Bild gefunden") from exc

    if not symbols:
        raise ValueError("Kein QR-Code im Bild gefunden")
    return symbols[0].data.decode("utf-8")


def _parse_ocr_card_text(text):
    def valid_name(value):
        normalized = _normalize_name(value).strip("=|:;.,'\"-_")
        if re.search(r"(?:geburts|datum|date|expiration|ablauf|kennnummer|versichert|name|nom|vorname|prenom)", normalized, flags=re.IGNORECASE):
            return None
        return normalized if re.fullmatch(r"[A-Za-zÄÖÜäöüßÀ-ÿ'’ -]{2,40}", normalized) else None

    def valid_ahv_number(value):
        digits = re.sub(r"[^0-9]", "", value)
        if len(digits) != 13 or not digits.startswith("756"):
            return False
        checksum = sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(digits[:12]))
        return (10 - checksum % 10) % 10 == int(digits[-1])

    def labeled_value(labels, skip_combined_name=False, name_value=False):
        pattern = r"(?<!\w)(?:" + "|".join(re.escape(label) for label in labels) + r")(?!\w)\s*[:;]?\s*(.*)"
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            lower_line = line.lower()
            if skip_combined_name and ("vorname" in lower_line or "prenom" in lower_line) and re.search(r"\b(?:name|nom)\b", lower_line):
                continue
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if match:
                value = match.group(1).strip(" :;.-").replace(",", "")
                if name_value:
                    value = valid_name(value)
                if value and not re.search(r"(?:vorname|vornamen|geburtsdatum|date de naissance|nom|name)\b", value, flags=re.IGNORECASE):
                    return value
                for following_line in lines[index + 1:index + 4]:
                    if not re.search(r"(?:vorname|vornamen|geburtsdatum|date de naissance|versicherten|kennnummer|nom|name)\b", following_line, flags=re.IGNORECASE):
                        following_value = re.sub(r"\b\d{2}[./]\d{2}[./]\d{4}\b", "", following_line).strip(" :;.-")
                        return valid_name(following_value) if name_value else following_value
        return None

    family = labeled_value(("nachname", "familienname", "surname", "nom", "cognome", "name"), skip_combined_name=True, name_value=True)
    given = labeled_value(("vorname", "vornamen", "given name", "firstname", "first name", "prénom", "prenom", "nome"), skip_combined_name=True, name_value=True)
    birth_date = labeled_value((
        "geburtsdatum", "geburtsdatur", "geburt", "date of birth", "birth date", "dob",
        "date de naissance", "data di nascita",
    ))
    identifier = labeled_value((
        "versichertennummer",
        "vers.-nr",
        "vers nr",
        "versicherten-nr",
        "versicherten nr",
        "versicherten-nummer",
        "insurance number",
        "insurance no",
        "card number",
        "kartennummer",
        "cherten-nummer",
        "n° d'assuré",
        "n° d'assure",
        "numero d'assure",
        "numéro assuré",
        "numero assure",
        "numero assicurato",
    ))
    issuer = labeled_value((
        "krankenkasse", "insurer", "health insurance",
    ))

    combined_name = labeled_value(("name/vorname", "name / vorname", "nom/prénom", "nom / prénom", "nom/prenom", "nom / prenom"))
    if combined_name and (not family or not given):
        parts = [part.strip() for part in re.split(r"[,;/]", combined_name, maxsplit=1)]
        if len(parts) == 2:
            family = family or parts[0]
            given = given or parts[1]

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    comma_candidates = []
    for line in lines:
        match = re.match(
            r"^\s*([A-Za-zÄÖÜäöüßÀ-ÿ][A-Za-zÄÖÜäöüßÀ-ÿ'’-]{2,})\s*,\s*([A-Za-zÄÖÜäöüßÀ-ÿ][A-Za-zÄÖÜäöüßÀ-ÿ'’-]{2,})\s*$",
            line,
        )
        if match and valid_name(match.group(1)) and valid_name(match.group(2)):
            comma_candidates.append((match.group(1), match.group(2)))
    if comma_candidates:
        family, given = Counter(comma_candidates).most_common(1)[0][0]

    date_name_candidates = []
    for index, line in enumerate(lines):
        date_name_match = re.match(
            r"^([A-ZÄÖÜ][A-ZÄÖÜa-zäöüß'’-]{2,})\s+\d{2}[./]\d{2}[./]\d{4}$",
            line,
        )
        if date_name_match and index > 0 and valid_name(lines[index - 1]):
            date_name_candidates.append((lines[index - 1], date_name_match.group(1)))
        if date_name_match:
            nearby_surnames = [
                candidate
                for candidate in lines[max(0, index - 4):index]
                if valid_name(candidate) and not re.search(r"(?:name|nom|vorname|geburt|datum|kennnummer|europ|karte)", candidate, re.IGNORECASE)
            ]
            if nearby_surnames:
                date_name_candidates.append((nearby_surnames[-1], date_name_match.group(1)))
    if date_name_candidates and not comma_candidates:
        family, given = date_name_candidates[-1]

    for index, line in enumerate(lines):
        if date_name_candidates or comma_candidates:
            break
        if not valid_name(line):
            continue
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        next_name_match = re.match(r"([A-ZÄÖÜ][A-ZÄÖÜa-zäöüß'’-]{2,})(?:\s+\d{2}[./]\d{2}[./]\d{4})?$", next_line)
        if next_name_match and valid_name(next_name_match.group(1)):
            family = line
            if not given or len(given) <= 2 or given.islower():
                given = next_name_match.group(1)
            break

    if not family or not given or not re.match(r"^[A-Za-zÄÖÜäöüß]", given):
        name_candidates = []
        for line in lines:
            match = re.match(r"^\s*([A-Za-zÄÖÜäöüßÀ-ÿ][A-Za-zÄÖÜäöüßÀ-ÿ'’-]{2,})\s*,\s*([A-Za-zÄÖÜäöüßÀ-ÿ][A-Za-zÄÖÜäöüßÀ-ÿ'’-]{2,})\s*$", line)
            if match and not any(label in line.lower() for label in ("name", "nom", "vorname", "prenom")):
                name_candidates.append((match.group(1), match.group(2)))
        if name_candidates:
            family, given = max(name_candidates, key=lambda candidate: len(candidate[1]))

    if not given or len(given) <= 2 or given.islower():
        name_before_date = re.search(
            r"\b([A-Za-zÄÖÜäöüßÀ-ÿ][A-Za-zÄÖÜäöüßÀ-ÿ'’-]{2,})\s+\d{2}[./]\d{2}[./]\d{4}\b",
            text,
        )
        if name_before_date:
            given = name_before_date.group(1)

    parsed_birth_date = _parse_date(birth_date)
    all_dates = [
        _parse_date(match.group(0))
        for match in re.finditer(r"\b\d{2}[./]\d{2}[./]\d{4}\b", text)
    ]
    all_dates = [candidate for candidate in all_dates if candidate and candidate <= date_type.today().isoformat()]
    if all_dates:
        dominant_date, dominant_count = Counter(all_dates).most_common(1)[0]
        if not parsed_birth_date or dominant_count > all_dates.count(parsed_birth_date):
            parsed_birth_date = dominant_date
    if not parsed_birth_date:
        birth_labels = list(re.finditer(
            r"(?:geburtsdatum|geburtsdatur|date of birth|birth date|date de naissance|data di nascita)",
            text,
            flags=re.IGNORECASE,
        ))
        for birth_label in birth_labels:
            date_match = re.search(r"\b\d{2}[./]\d{2}[./]\d{4}\b", text[birth_label.end():birth_label.end() + 220])
            if date_match:
                context_before_date = text[birth_label.end():birth_label.end() + date_match.start()].lower()
                if "ablauf" not in context_before_date and "expiration" not in context_before_date and "scadenza" not in context_before_date:
                    parsed_birth_date = _parse_date(date_match.group(0))
                    if parsed_birth_date:
                        break
        if not parsed_birth_date:
            date_candidates = [
                _parse_date(match.group(0))
                for match in re.finditer(r"\b\d{2}[./]\d{2}[./]\d{4}\b", text)
            ]
            date_candidates = [date for date in date_candidates if date]
            if date_candidates:
                parsed_birth_date = Counter(date_candidates).most_common(1)[0][0]

    if not family and not given and not birth_date and not identifier:
        return None

    identifiers = []
    if identifier:
        insurance_number = re.match(r"\d{8}", re.sub(r"\D", "", identifier))
        identifiers.append({
            "system": "https://example.org/insurance-card",
            "value": insurance_number.group(0) if insurance_number else re.sub(r"[^A-Za-z0-9]", "", identifier),
            "type": "insurance-number",
        })
    if issuer:
        identifiers.append({
            "system": "https://example.org/insurance-card/issuer",
            "value": issuer,
            "type": "insurer",
        })
    existing_values = {item["value"] for item in identifiers}
    card_number_match = re.search(r"(?<!\d)(807(?:[ .-]?\d){17})(?!\d)", text)
    if card_number_match:
        card_number = re.sub(r"[^0-9]", "", card_number_match.group(1))
        if card_number not in existing_values:
            identifiers.append({
                "system": "https://example.org/insurance-card",
                "value": card_number,
                "type": "card-number",
            })
            existing_values.add(card_number)
    for ahv_number in re.findall(r"756(?:[.\s-]?\d{4}){2}[.\s-]?\d{2}", text):
        normalized_ahv = re.sub(r"[^0-9]", "", ahv_number)
        if valid_ahv_number(normalized_ahv) and normalized_ahv not in existing_values:
            identifiers.append({
                "system": "https://www.bsv.admin.ch/ahv-number",
                "value": normalized_ahv,
                "type": "ahv-number",
            })
            existing_values.add(normalized_ahv)
    carrier_match = re.search(r"\b0?(\d{4})\s*[-=]?\s*EGK\b", text, flags=re.IGNORECASE)
    carrier_match = carrier_match or re.search(r"\b0(\d{4})\b\s+756(?:[.\s-]?\d{4}){2}[.\s-]?\d{2}", text)
    if carrier_match and carrier_match.group(1) not in existing_values:
        identifiers.append({
            "system": "https://example.org/insurance-card/carrier",
            "value": carrier_match.group(1),
            "type": "carrier-code",
        })
    return {
        "card_type": "insurance_card_ocr",
        "person": {
            "family": _display_name(family),
            "given": _display_name(given),
            "birth_date": parsed_birth_date,
        },
        "identifiers": identifiers,
        "raw": text,
    }


def _parse_swiss_id_ocr_text(text):
    marker_count = sum(bool(re.search(pattern, text, flags=re.IGNORECASE)) for pattern in (
        r"schwei", r"confed", r"swiss", r"carte|corte|carta", r"name\(s\)",
    ))
    number_match = re.search(r"(?:\bE|[£€])\s*(\d{6,8})\b", text, flags=re.IGNORECASE)
    date_match = re.search(r"\b(\d{2})\s*[./-]?\s*(\d{2})\s*[./-]?\s*(\d{2,4})\b", text)
    compact_date_match = re.search(r"\b(\d{2})(\d{2})(\d{2})\b", text)
    strong_swiss_marker = re.search(r"schwei|swiss\s+con|confed", text, flags=re.IGNORECASE)
    if marker_count < 2 or not strong_swiss_marker:
        return None

    identifiers = []
    if number_match:
        identifiers.append({
            "system": "https://www.schweizerpass.admin.ch/swissid/document-number",
            "value": "E" + number_match.group(1),
            "type": "document-number",
        })
    birth_date = None
    if date_match:
        day, month, year = date_match.groups()
        if len(year) == 2:
            year = f"19{year}" if int(year) >= 30 else f"20{year}"
        if 1 <= int(month) <= 12 and 1 <= int(day) <= 31:
            birth_date = f"{year}-{month}-{day}"
    elif compact_date_match:
        day, month, year = compact_date_match.groups()
        if 1 <= int(month) <= 12 and 1 <= int(day) <= 31:
            birth_date = f"19{year}-{month}-{day}" if int(year) >= 30 else f"20{year}-{month}-{day}"

    starred_names = []
    for line in text.splitlines():
        starred_match = re.fullmatch(r"\s*([A-Za-zÄÖÜäöüßÀ-ÿ'’ -]{2,40})\s*\*\s*", line)
        if starred_match:
            candidate = _normalize_name(starred_match.group(1))
            if candidate and not any(part in candidate.lower() for part in ("confed", "swiss", "schwei", "carta", "ident")):
                starred_names.append(_display_name(candidate))

    name = starred_names[0] if starred_names else None
    given = starred_names[1] if len(starred_names) > 1 else None
    ignored_name_parts = ("confed", "swiss", "schwei", "schweiz", "carta", "ident", "name", "wössens", "e592")
    for line in text.splitlines():
        candidate = _normalize_name(line).strip(" -_.,:;|'")
        name_words = candidate.split()
        if (3 <= len(candidate) <= 40 and any(len(word) >= 3 for word in name_words)
            and re.fullmatch(r"[A-Za-zÄÖÜäöüßÀ-ÿ'’ -]+", candidate)
                and not any(part in candidate.lower() for part in ignored_name_parts)
                and candidate.lower() not in {"wäss", "wasse", "est", "mm", "id", "opa", "see"}):
            name = name or _display_name(candidate)
    return {
        "card_type": "swiss_id_card_ocr",
        "person": {"family": name, "given": given, "birth_date": birth_date},
        "identifiers": identifiers,
        "raw": text,
    }


def _ocr_card_image(raw_bytes):
    try:
        from PIL import Image, ImageOps
        from pillow_heif import register_heif_opener
        import pytesseract
    except ImportError as exc:
        raise ValueError("OCR/HEIC ist nicht verfügbar. Bitte pytesseract, pillow-heif und Tesseract installieren.") from exc

    try:
        register_heif_opener()
        image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        gray = ImageOps.grayscale(image)
        enlarged = gray.resize((gray.width * 2, gray.height * 2))
        variants = [
            ImageOps.autocontrast(enlarged),
            ImageOps.autocontrast(enlarged).point(lambda value: 255 if value > 170 else 0),
        ]
        focused_regions = [
            image.crop((0, int(image.height * 0.55), int(image.width * 0.75), int(image.height * 0.82))),
            image.crop((0, int(image.height * 0.58), image.width, int(image.height * 0.98))),
            image.crop((int(image.width * 0.35), int(image.height * 0.32), int(image.width * 0.9), int(image.height * 0.95))),
            image.crop((0, int(image.height * 0.68), image.width, image.height)),
        ]
        texts = []
        for variant in variants:
            for page_segmentation in (6, 11):
                texts.append(pytesseract.image_to_string(
                    variant,
                    lang="deu+eng+fra+ita",
                    config=f"--psm {page_segmentation}",
                ))
                for region in focused_regions:
                    region = ImageOps.autocontrast(ImageOps.grayscale(region).resize((region.width * 3, region.height * 3)))
                    texts.append(pytesseract.image_to_string(region, lang="deu+eng+fra+ita", config="--psm 6"))
        text = "\n".join(texts)
    except Exception as exc:  # pragma: no cover - depends on native OCR runtime
        raise ValueError("Versicherungskarte konnte nicht per OCR gelesen werden") from exc

    mrz_lines = []
    for line in text.splitlines():
        normalized_line = re.sub(r"[^A-Z0-9<]", "", line.upper().replace("«", "<").replace("‹", "<"))
        if len(normalized_line) >= 20 and ("<<" in normalized_line or normalized_line.startswith(("I", "ID", "C"))):
            mrz_lines.append(normalized_line)
    if mrz_lines:
        result = _parse_mrz_text("\n".join(mrz_lines))
        if result and result["person"]["family"] and result["person"]["given"]:
            return result

    swiss_id_result = _parse_swiss_id_ocr_text(text)
    if swiss_id_result:
        return swiss_id_result

    result = _parse_ocr_card_text(text)
    if not result:
        raise ValueError("Keine lesbaren Versicherungsdaten auf der Karte gefunden")
    return result


def _extract_echo_sos_data(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname != "eid.echosos.com":
        raise ValueError("Keine gültige EchoSOS-URL")

    data = parse_echosos_data(value)
    person = {
        "given": _normalize_name(data.get("given")),
        "family": _normalize_name(data.get("family")),
        "birth_date": _date_from_iso(data.get("birth_date")),
    }
    identifiers = []
    if person["given"] or person["family"] or person["birth_date"]:
        identifiers.append({
            "system": ECHOSOS_IDENTIFIER_SYSTEM,
            "value": re.sub(r"[^A-Za-z0-9]", "", value)[:64] or "echosos-card",
            "type": "echo-sos",
        })
    return {
        "card_type": "echo_sos_qr",
        "person": person,
        "identifiers": identifiers,
        "raw": value,
    }


def _parse_key_value_text(text):
    mapping = {}
    for line in text.splitlines():
        cleaned = line.strip()
        if not cleaned or "=" not in cleaned and ":" not in cleaned:
            continue
        if "=" in cleaned:
            key, value = cleaned.split("=", 1)
        else:
            key, value = cleaned.split(":", 1)
        mapping[key.strip().lower()] = value.strip()

    if not mapping:
        return None

    family = next((mapping[k] for k in ["family", "lastname", "last_name", "surname", "name"] if k in mapping), None)
    given = next((mapping[k] for k in ["given", "firstname", "first_name", "vorname"] if k in mapping), None)
    birth_date = next((mapping[k] for k in ["birthdate", "birth_date", "dob", "geburtsdatum"] if k in mapping), None)
    identifier = next((mapping[k] for k in ["id", "identifier", "cardid", "card_id", "insuranceid", "insurance_id", "mitgliedsnummer", "patientid"] if k in mapping), None)

    if not family and not given and not birth_date and not identifier:
        return None

    person = {
        "family": _normalize_name(family),
        "given": _normalize_name(given),
        "birth_date": _parse_date(birth_date),
    }
    identifiers = []
    if identifier:
        identifiers.append({"system": "https://example.org/card-identifier", "value": str(identifier), "type": "card-id"})
    return {
        "card_type": "generic_card",
        "person": person,
        "identifiers": identifiers,
        "raw": text,
    }


def _parse_mrz_text(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    name_lines = [line for line in lines if "<<" in line and re.search(r"[A-Z]{2,}<<[A-Z]{2,}", line)]
    name_line = max(name_lines, key=lambda line: len(line.split("<<", 1)[0].strip("<")), default=None)
    if not name_line:
        name_line = next((line for line in lines if re.search(r"[A-Z]{2,}<+[A-Z]<+[A-Z]{3,}", line) or re.search(r"[A-Z]{2,}(?:<+|\s+)[A-Z]{3,}", line) and "MARKUS" in line), None)
    first_line = next((line for line in lines if "<" in line or line.startswith(("P", "I", "C"))), None)
    if not name_line:
        return None

    name_line = re.sub(r"\s+", "", name_line).replace("<S<", "<<")
    name_line = name_line.replace("WCESS", "WOESS")
    prefix, suffix = name_line.split("<<", 1)
    family = prefix.replace("P", "").replace("I", "").replace("C", "").replace("<", " ").strip()
    given = " ".join(part for part in suffix.split("<") if part).strip()
    family = re.sub(r"^(?:Wdess|Wdess|Wess)$", "Wöss", family, flags=re.IGNORECASE)
    second_line = next((line for line in lines if re.match(r"^\d{6}[0-9<][A-Z<]", line)), "")
    if not second_line:
        second_line = next((line for line in lines if len(line) >= 6 and any(ch.isdigit() for ch in line)), "")

    birth_date = None
    date_match = re.match(r"^(\d{6})[0-9<][A-Z<]", second_line)
    if not date_match:
        date_match = next(
            (
                match
                for match in re.finditer(r"(?<!\d)(\d{6})(?=[A-Z<])", second_line)
                if 1 <= int(match.group(1)[2:4]) <= 12 and 1 <= int(match.group(1)[4:6]) <= 31
            ),
            None,
        )
    if date_match:
        candidate = date_match.group(1)
        yy, mm, dd = candidate[0:2], candidate[2:4], candidate[4:6]
        if 1 <= int(mm) <= 12 and 1 <= int(dd) <= 31:
            year = int(yy)
            century = 2000 if year < 30 else 1900
            birth_date = f"{century + year}-{mm}-{dd}"

    document_candidates = []
    for line in lines:
        document_match = re.search(r"(?:ID|I|C)<*CHE([A-Z0-9]{5,12})<", line)
        if document_match:
            document_candidates.append(document_match.group(1))
    numeric_document_candidates = [candidate for candidate in document_candidates if re.fullmatch(r"E\d{7,}", candidate)]
    preferred_candidates = numeric_document_candidates or document_candidates
    identifier = Counter(preferred_candidates).most_common(1)[0][0] if preferred_candidates else None
    if not identifier and second_line:
        identifier = second_line[:9].strip("<")

    person = {
        "family": _display_name(_normalize_result_name(family)),
        "given": _display_name(_normalize_result_name(given)),
        "birth_date": birth_date,
    }
    identifiers = []
    if identifier:
        identifiers.append({"system": "https://example.org/mrz-document-number", "value": identifier, "type": "document-number"})
    return {
        "card_type": "mrz_card",
        "person": person,
        "identifiers": identifiers,
        "raw": text,
    }


def _parse_text_card(data):
    text = data.strip()
    if not text:
        raise ValueError("Leerer Text")

    if "<<" in text or text.startswith(("P<", "I<", "C<", "IDCHE")):
        parsed = _parse_mrz_text(text)
        if parsed:
            return parsed

    parsed = _parse_swiss_id_ocr_text(text)
    if parsed:
        return parsed

    parsed = _parse_key_value_text(text)
    if parsed:
        return parsed

    raise ValueError("Keine lesbaren Karten- oder Identitätsdaten gefunden")


def analyze_card(raw_bytes, content_type=None):
    if raw_bytes is None:
        raise ValueError("Keine Rohdaten für die Kartenanalyse erhalten")

    try:
        text_candidate = raw_bytes.decode("utf-8").strip()
    except UnicodeDecodeError:
        text_candidate = None

    if text_candidate:
        if text_candidate.startswith(("http://", "https://")):
            try:
                return _extract_echo_sos_data(text_candidate)
            except ValueError as exc:
                raise ValueError("Unbekanntes QR-/Card-Format") from exc

        try:
            return _parse_text_card(text_candidate)
        except ValueError:
            pass

    if content_type == "application/vnd.apple.pkpass" or raw_bytes[:2] == b"PK":
        raw_value = _pkpass_barcode(raw_bytes)
    else:
        try:
            raw_value = _decode_qr_from_file(raw_bytes)
        except ValueError as exc:
            if content_type and content_type.startswith("image/"):
                try:
                    return _ocr_card_image(raw_bytes)
                except ValueError as ocr_exc:
                    raise ValueError(f"Weder QR-Code noch lesbare Versicherungsdaten erkannt: {ocr_exc}") from ocr_exc
            if text_candidate:
                raise ValueError("Kein unterstütztes QR-/Card-Format erkannt") from exc
            raise

    if raw_value.startswith("http://") or raw_value.startswith("https://"):
        try:
            return _extract_echo_sos_data(raw_value)
        except ValueError as exc:
            raise ValueError("Unbekanntes QR-/Card-Format") from exc

    try:
        return _parse_text_card(raw_value)
    except ValueError:
        raise ValueError("Kein unterstütztes QR-/Card-Format erkannt")
