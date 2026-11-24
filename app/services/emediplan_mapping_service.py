import hashlib
import io
import json
import logging
import os
import re
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import requests

try:
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException
except ImportError:  # pragma: no cover
    load_workbook = None
    InvalidFileException = ValueError

from config import (
    EMEDIPLAN_MAPPING_DATA_DIR,
    EMEDIPLAN_MAPPING_DOWNLOAD_TIMEOUT,
)
from terminology.emediplan_medication_map import (
    DEFAULT_PHARMACODE_XLSX,
    DEFAULT_PRODUCTNUMBER_XLSX,
    invalidate_medication_mapping_cache,
)

logger = logging.getLogger(__name__)

_INDEX_URL = "https://www.emediplan.ch/softwareanbieter"
_ALLOWED_HOSTS = {
    "emediplan.ch",
    "www.emediplan.ch",
    "static1.squarespace.com",
}
_MAX_WORKBOOK_BYTES = 50 * 1024 * 1024
_MAPPING_PATTERNS = {
    "pharmacode": re.compile(
        r"(?P<version>\d{8})__MappingPharmacodeToGtinToSwissmedicDescription\.xlsx$",
        re.IGNORECASE,
    ),
    "product_number": re.compile(
        r"(?P<version>\d{8})__MappingProductNumberToSwissmedicDescription\.xlsx$",
        re.IGNORECASE,
    ),
}
_REFRESH_LOCK = threading.Lock()


class EmediplanMappingRefreshError(RuntimeError):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


class _HrefParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self.hrefs.extend(
                value for name, value in attrs if name.lower() == "href" and value
            )


def _validate_source_url(url):
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise EmediplanMappingRefreshError(
            f"Unerlaubte eMediplan-Download-URL: {url}"
        ) from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or port not in (None, 443)
    ):
        raise EmediplanMappingRefreshError(
            f"Unerlaubte eMediplan-Download-URL: {url}"
        )


def discover_mapping_urls(html, page_url=_INDEX_URL):
    parser = _HrefParser()
    parser.feed(html)

    matches = {mapping_type: {} for mapping_type in _MAPPING_PATTERNS}
    for href in parser.hrefs:
        url = urljoin(page_url, href)
        filename = Path(unquote(urlsplit(url).path)).name
        for mapping_type, pattern in _MAPPING_PATTERNS.items():
            match = pattern.fullmatch(filename)
            if not match:
                continue
            _validate_source_url(url)
            version = match.group("version")
            try:
                datetime.strptime(version, "%Y%m%d")
            except ValueError as exc:
                raise EmediplanMappingRefreshError(
                    f"Ungültige eMediplan-Versionskennung: {version}"
                ) from exc
            matches[mapping_type].setdefault(version, set()).add(url)

    common_versions = (
        set(matches["pharmacode"]) & set(matches["product_number"])
    )
    if not common_versions:
        raise EmediplanMappingRefreshError(
            "Auf der eMediplan-Seite wurde kein vollständiges Mapping-Dateipaar gefunden"
        )

    version = max(common_versions)
    urls = {}
    for mapping_type in _MAPPING_PATTERNS:
        candidates = matches[mapping_type][version]
        if len(candidates) != 1:
            raise EmediplanMappingRefreshError(
                f"Mehrdeutiger Download-Link für {mapping_type} Version {version}"
            )
        urls[mapping_type] = candidates.pop()

    return version, urls


def _get_index_html(timeout):
    with requests.get(_INDEX_URL, timeout=timeout) as response:
        response.raise_for_status()
        _validate_source_url(response.url or _INDEX_URL)
        return response.text


def _download_workbook(url, timeout):
    _validate_source_url(url)
    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        final_url = response.url or url
        _validate_source_url(final_url)
        expected_filename = Path(unquote(urlsplit(url).path)).name
        final_filename = Path(unquote(urlsplit(final_url).path)).name
        if final_filename != expected_filename:
            raise EmediplanMappingRefreshError(
                "Der eMediplan-Download wurde auf eine unerwartete Datei umgeleitet"
            )
        length = response.headers.get("Content-Length")
        if length:
            try:
                if int(length) > _MAX_WORKBOOK_BYTES:
                    raise EmediplanMappingRefreshError(
                        "eMediplan-XLSX überschreitet die erlaubte Dateigröße"
                    )
            except ValueError as exc:
                raise EmediplanMappingRefreshError(
                    "Ungültige Content-Length beim eMediplan-Download"
                ) from exc

        content = bytearray()
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > _MAX_WORKBOOK_BYTES:
                raise EmediplanMappingRefreshError(
                    "eMediplan-XLSX überschreitet die erlaubte Dateigröße"
                )
        return bytes(content)


def _normalize_header(value):
    return (
        str(value or "")
        .strip()
        .lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
    )


def _validate_workbook(content, mapping_type):
    if not content or not zipfile.is_zipfile(io.BytesIO(content)):
        raise EmediplanMappingRefreshError(
            f"Die eMediplan-Datei {mapping_type} ist keine gültige XLSX-Datei"
        )
    if load_workbook is None:
        raise EmediplanMappingRefreshError(
            "openpyxl fehlt; eMediplan-XLSX kann nicht validiert werden", 503
        )

    workbook = None
    try:
        workbook = load_workbook(
            io.BytesIO(content), data_only=True, read_only=True
        )
        rows = workbook.active.iter_rows(values_only=True)
        headers = next(rows, None)
        if not headers:
            raise EmediplanMappingRefreshError(
                f"Die eMediplan-Datei {mapping_type} enthält keine Kopfzeile"
            )
        columns = {_normalize_header(value) for value in headers}

        if mapping_type == "pharmacode":
            required = {"pharmacode", "gtin"}
            key_columns = {"pharmacode"}
        else:
            required = {"prdnr", "swissmedicbezeichnungdesarzneimittels"}
            key_columns = {"prdnr"}

        # Product-number exports may use one of the legacy header labels.
        if mapping_type == "product_number":
            has_product_number = bool(
                columns
                & {
                    "prdnr",
                    "productnumber",
                    "swissmedicnr+packungscode",
                }
            )
            required = {"swissmedicbezeichnungdesarzneimittels"}
            if not has_product_number:
                raise EmediplanMappingRefreshError(
                    "Die Produktnummern-XLSX enthält keine erkannte Produktnummern-Spalte"
                )
            key_columns = columns & {
                "prdnr",
                "productnumber",
                "swissmedicnr+packungscode",
            }

        if not required.issubset(columns):
            missing = ", ".join(sorted(required - columns))
            raise EmediplanMappingRefreshError(
                f"Pflichtspalten in {mapping_type}-XLSX fehlen: {missing}"
            )

        item_count = sum(
            1
            for row in rows
            if any(
                index < len(row) and row[index] not in (None, "")
                for index, header in enumerate(headers)
                if _normalize_header(header) in key_columns
            )
        )
        if item_count == 0:
            raise EmediplanMappingRefreshError(
                f"Die eMediplan-Datei {mapping_type} enthält keine Datensätze"
            )
        return item_count
    except EmediplanMappingRefreshError:
        raise
    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        SyntaxError,
        zipfile.BadZipFile,
        InvalidFileException,
    ) as exc:
        raise EmediplanMappingRefreshError(
            f"Die eMediplan-Datei {mapping_type} konnte nicht gelesen werden: {exc}"
        ) from exc
    finally:
        if workbook is not None:
            workbook.close()


def _sha256(content):
    return hashlib.sha256(content).hexdigest()


def _read_active_version(data_dir):
    pointer = data_dir / "current.json"
    if not pointer.is_file():
        return None
    try:
        manifest = json.loads(pointer.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be an object")
        version = str(manifest["version"])
    except (
        OSError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
    ) as exc:
        raise EmediplanMappingRefreshError(
            "Das aktive eMediplan-Mapping-Manifest ist ungültig", 503
        ) from exc
    if not re.fullmatch(r"\d{8}", version):
        raise EmediplanMappingRefreshError(
            "Das aktive eMediplan-Mapping-Manifest enthält eine ungültige Version",
            503,
        )
    return version


def _write_json_atomically(path, payload):
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as target:
            temporary_path = Path(target.name)
            json.dump(payload, target, ensure_ascii=False, indent=2)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _ensure_bundled_archive(data_dir):
    archive_root = data_dir / "archive"
    archive_root.mkdir(parents=True, exist_ok=True)
    baseline_path = archive_root / "bundled"
    filenames = {
        "pharmacode": (
            "MappingPharmacodeToGtinToSwissmedicDescription.xlsx",
            Path(DEFAULT_PHARMACODE_XLSX),
        ),
        "product_number": (
            "MappingProductNumberToSwissmedicDescription.xlsx",
            Path(DEFAULT_PRODUCTNUMBER_XLSX),
        ),
    }

    if baseline_path.exists():
        baseline_files_exist = all(
            (baseline_path / filename).is_file()
            for filename, _ in filenames.values()
        )
        if not baseline_files_exist or not (baseline_path / "manifest.json").is_file():
            raise EmediplanMappingRefreshError(
                "Das eMediplan-Basisarchiv ist unvollständig", 503
            )
        return

    if not any(path.is_file() for _, path in filenames.values()):
        return
    if not all(path.is_file() for _, path in filenames.values()):
        raise EmediplanMappingRefreshError(
            "Die gebündelten eMediplan-XLSX-Dateien sind unvollständig", 503
        )

    files = {}
    for mapping_type, (filename, source_path) in filenames.items():
        content = source_path.read_bytes()
        item_count = _validate_workbook(content, mapping_type)
        files[mapping_type] = {
            "filename": filename,
            "content": content,
            "items": item_count,
            "sha256": _sha256(content),
        }

    with tempfile.TemporaryDirectory(
        dir=data_dir, prefix=".emediplan-baseline-"
    ) as temporary_dir:
        stage_dir = Path(temporary_dir) / "bundled"
        stage_dir.mkdir()
        for file_data in files.values():
            (stage_dir / file_data["filename"]).write_bytes(file_data["content"])
        baseline_manifest = {
            "version": "bundled",
            "source": "application-image",
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "files": {
                mapping_type: {
                    "filename": file_data["filename"],
                    "sha256": file_data["sha256"],
                    "size_bytes": len(file_data["content"]),
                    "items": file_data["items"],
                }
                for mapping_type, file_data in files.items()
            },
        }
        (stage_dir / "manifest.json").write_text(
            json.dumps(baseline_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(stage_dir, baseline_path)


def refresh_emediplan_mappings(data_dir=None, timeout=None):
    """Discover, validate, archive, and activate one matching monthly XLSX pair."""
    data_dir = Path(data_dir or EMEDIPLAN_MAPPING_DATA_DIR)
    timeout = timeout or EMEDIPLAN_MAPPING_DOWNLOAD_TIMEOUT

    if not _REFRESH_LOCK.acquire(blocking=False):
        raise EmediplanMappingRefreshError(
            "Ein eMediplan-Mapping-Refresh läuft bereits", 503
        )
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        active_version = _read_active_version(data_dir)
        if active_version and not (
            data_dir / "archive" / active_version
        ).is_dir():
            raise EmediplanMappingRefreshError(
                f"Aktives eMediplan-Archiv {active_version} fehlt", 503
            )
        html = _get_index_html(timeout)
        version, urls = discover_mapping_urls(html)
        if active_version and version < active_version:
            raise EmediplanMappingRefreshError(
                f"eMediplan-Version {version} ist älter als die aktive Version "
                f"{active_version}",
                503,
            )

        downloaded = {}
        for mapping_type, url in urls.items():
            content = _download_workbook(url, timeout)
            item_count = _validate_workbook(content, mapping_type)
            filename = Path(unquote(urlsplit(url).path)).name
            downloaded[mapping_type] = {
                "content": content,
                "filename": filename,
                "url": url,
                "items": item_count,
                "sha256": _sha256(content),
            }

        _ensure_bundled_archive(data_dir)
        archive_root = data_dir / "archive"
        archive_root.mkdir(parents=True, exist_ok=True)
        archive_path = archive_root / version
        archive_manifest = {
            "version": version,
            "source": _INDEX_URL,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "files": {
                mapping_type: {
                    "filename": file_data["filename"],
                    "url": file_data["url"],
                    "sha256": file_data["sha256"],
                    "size_bytes": len(file_data["content"]),
                    "items": file_data["items"],
                }
                for mapping_type, file_data in downloaded.items()
            },
        }

        if archive_path.exists():
            manifest_path = archive_path / "manifest.json"
            try:
                existing_manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
                if not isinstance(existing_manifest, dict):
                    raise ValueError("manifest must be an object")
                if existing_manifest.get("version") != version:
                    raise ValueError("manifest version does not match archive")
                existing_files = existing_manifest.get("files")
                if not isinstance(existing_files, dict):
                    raise ValueError("manifest has no file map")
            except (
                OSError,
                TypeError,
                UnicodeDecodeError,
                ValueError,
            ) as exc:
                raise EmediplanMappingRefreshError(
                    f"eMediplan-Archiv {version} ist beschädigt", 503
                ) from exc
            existing_hashes = {
                key: value.get("sha256")
                for key, value in existing_files.items()
                if isinstance(value, dict)
            }
            new_hashes = {
                key: value["sha256"]
                for key, value in archive_manifest["files"].items()
            }
            if existing_hashes != new_hashes:
                raise EmediplanMappingRefreshError(
                    f"eMediplan-Version {version} wurde mit anderen Datei-Inhalten "
                    "bereits archiviert",
                    503,
                )
        else:
            with tempfile.TemporaryDirectory(
                dir=data_dir, prefix=".emediplan-refresh-"
            ) as temporary_dir:
                stage_dir = Path(temporary_dir) / version
                stage_dir.mkdir()
                for file_data in downloaded.values():
                    (stage_dir / file_data["filename"]).write_bytes(
                        file_data["content"]
                    )
                (stage_dir / "manifest.json").write_text(
                    json.dumps(archive_manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                os.replace(stage_dir, archive_path)

        activated = active_version != version
        if activated:
            _write_json_atomically(
                data_dir / "current.json",
                {
                    "version": version,
                    "archive": f"archive/{version}",
                    "activated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            invalidate_medication_mapping_cache()

        result = {
            "version": version,
            "updated": activated,
            "archive": f"archive/{version}",
            "files": {
                mapping_type: {
                    "filename": file_data["filename"],
                    "sha256": file_data["sha256"],
                    "size_bytes": len(file_data["content"]),
                    "items": file_data["items"],
                }
                for mapping_type, file_data in downloaded.items()
            },
        }
        logger.info("eMediplan-Mappings aktualisiert: %s", result)
        return result
    except EmediplanMappingRefreshError:
        raise
    except requests.RequestException as exc:
        logger.exception("eMediplan-Mapping-Download fehlgeschlagen")
        raise EmediplanMappingRefreshError(
            f"eMediplan-Download fehlgeschlagen: {exc}"
        ) from exc
    finally:
        _REFRESH_LOCK.release()
