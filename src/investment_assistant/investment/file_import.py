"""File-to-CSV conversion helpers for investment holdings.

The converter is intentionally conservative: it only normalizes uploaded files
into the existing holdings CSV contract, then delegates validation to the same
deterministic loader used by the rest of the MVP.
"""

from __future__ import annotations

import base64
import binascii
import csv
import html as html_lib
import io
import re
import zlib
from collections.abc import Mapping, Sequence
from html.parser import HTMLParser

from investment_assistant.investment.loader import validate_holdings_payload

_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp932", "shift_jis", "euc_jp")
_PDF_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
_PDF_LITERAL_RE = re.compile(rb"\((?:\\.|[^\\()])*\)", re.DOTALL)
_PDF_HEX_RE = re.compile(rb"(?<!<)<([0-9A-Fa-f\s]+)>(?!>)")


def convert_holding_file_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Convert an uploaded CSV/HTML/PDF holdings file into validated CSV text."""

    filename = str(payload.get("filename") or "uploaded").strip() or "uploaded"
    content_type = str(payload.get("content_type") or "").strip()
    raw = _payload_bytes(payload)
    detected_format = _detect_format(filename, content_type, raw)
    warnings: list[dict[str, object]] = []
    encoding: str | None = None

    if detected_format in {"csv", "tsv", "text"}:
        csv_text, encoding = _decode_text(raw)
        if detected_format == "tsv":
            warnings.append(_warning("tsv_converted", "TSV input was normalized as CSV."))
    elif detected_format == "html":
        html_text, encoding = _decode_text(raw)
        csv_text = _csv_from_html(html_text, warnings)
    elif detected_format == "pdf":
        pdf_text = _extract_pdf_text(raw)
        warnings.append(
            _warning(
                "pdf_text_best_effort",
                "PDF text extraction is best-effort. Review the converted CSV before analysis.",
            )
        )
        csv_text = _csv_from_text(pdf_text, warnings)
    else:
        raise ValueError(f"Unsupported holdings file type: {filename or content_type}")

    validation = validate_holdings_payload({"csv_text": csv_text})
    validation_warnings = validation.get("warnings")
    input_warnings = list(warnings)
    if isinstance(validation_warnings, list):
        input_warnings.extend(item for item in validation_warnings if isinstance(item, dict))

    return {
        "available": True,
        "filename": filename,
        "content_type": content_type,
        "detected_format": detected_format,
        "detected_encoding": encoding,
        "csv_text": csv_text,
        "validation": validation,
        "valid": validation.get("valid") is True,
        "count": validation.get("count", 0),
        "holdings": validation.get("holdings", []),
        "warnings": warnings,
        "input_warnings": input_warnings,
        "auto_trading": False,
        "call_real_api": False,
    }


def _payload_bytes(payload: Mapping[str, object]) -> bytes:
    raw_base64 = payload.get("content_base64")
    if isinstance(raw_base64, str) and raw_base64.strip():
        try:
            return base64.b64decode(raw_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("content_base64 must be valid base64") from exc

    text = payload.get("text")
    if isinstance(text, str) and text:
        return text.encode("utf-8")

    csv_text = payload.get("csv_text")
    if isinstance(csv_text, str) and csv_text:
        return csv_text.encode("utf-8")

    raise ValueError("content_base64, text, or csv_text is required")


def _detect_format(filename: str, content_type: str, raw: bytes) -> str:
    lowered_name = filename.lower()
    lowered_type = content_type.lower()
    sniff = raw[:256].lstrip().lower()
    if (
        lowered_name.endswith(".pdf")
        or lowered_type == "application/pdf"
        or raw.startswith(b"%PDF")
    ):
        return "pdf"
    if (
        lowered_name.endswith((".html", ".htm"))
        or "html" in lowered_type
        or sniff.startswith((b"<!doctype html", b"<html"))
    ):
        return "html"
    if lowered_name.endswith(".tsv") or "tab-separated-values" in lowered_type:
        return "tsv"
    if lowered_name.endswith(".csv") or "csv" in lowered_type:
        return "csv"
    if sniff.startswith(b"<"):
        return "html"
    return "text"


def _decode_text(data: bytes) -> tuple[str, str]:
    for encoding in _TEXT_ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def _csv_from_html(text: str, warnings: list[dict[str, object]]) -> str:
    parser = _HtmlTableParser()
    parser.feed(text)
    for index, table in enumerate(parser.tables, start=1):
        candidate = _csv_from_table(table)
        if candidate and _valid_holding_csv(candidate):
            warnings.append(
                _warning(
                    "html_table_converted",
                    f"HTML table #{index} was converted to holdings CSV.",
                )
            )
            return candidate

    fallback_text = _html_to_text(text)
    return _csv_from_text(fallback_text, warnings)


def _csv_from_table(table: Sequence[Sequence[str]]) -> str | None:
    rows = [[cell.strip() for cell in row] for row in table if any(cell.strip() for cell in row)]
    for header_index in range(max(0, min(3, len(rows) - 1))):
        candidate = _rows_to_csv(rows[header_index], rows[header_index + 1 :])
        if _valid_holding_csv(candidate):
            return candidate
    return None


def _csv_from_text(text: str, warnings: list[dict[str, object]]) -> str:
    cleaned = text.strip().lstrip("\ufeff")
    if _valid_holding_csv(cleaned):
        return cleaned

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    for start in range(min(10, len(lines))):
        candidate = "\n".join(lines[start:])
        if _valid_holding_csv(candidate):
            warnings.append(
                _warning(
                    "text_table_converted",
                    "Delimited text was converted to holdings CSV.",
                )
            )
            return candidate

    raise ValueError(
        "Could not find a holdings table. Include asset_type, ticker_or_fund_code, "
        "name, quantity, and avg_cost columns."
    )


def _rows_to_csv(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(list(header))
    width = len(header)
    for row in rows:
        cells = list(row[:width])
        if len(cells) < width:
            cells.extend([""] * (width - len(cells)))
        if any(str(cell).strip() for cell in cells):
            writer.writerow(cells)
    return output.getvalue()


def _valid_holding_csv(text: str) -> bool:
    return validate_holdings_payload({"csv_text": text}).get("valid") is True


def _html_to_text(text: str) -> str:
    parser = _HtmlTextParser()
    parser.feed(text)
    parser.close()
    return "\n".join(line for line in parser.lines if line.strip())


def _extract_pdf_text(data: bytes) -> str:
    chunks = [data]
    for match in _PDF_STREAM_RE.finditer(data):
        stream = match.group(1).strip(b"\r\n")
        chunks.append(stream)
        try:
            chunks.append(zlib.decompress(stream))
        except zlib.error:
            continue

    strings: list[str] = []
    for chunk in chunks:
        strings.extend(_decode_pdf_literal(item) for item in _PDF_LITERAL_RE.findall(chunk))
        strings.extend(_decode_pdf_hex(item) for item in _PDF_HEX_RE.findall(chunk))

    extracted = "\n".join(item.strip() for item in strings if item.strip())
    if extracted:
        return extracted
    text, _encoding = _decode_text(data)
    return text


def _decode_pdf_literal(token: bytes) -> str:
    body = token[1:-1]
    out = bytearray()
    index = 0
    while index < len(body):
        value = body[index]
        if value != 0x5C:  # backslash
            out.append(value)
            index += 1
            continue
        index += 1
        if index >= len(body):
            break
        escaped = body[index]
        index += 1
        if escaped in b"nrtbf":
            escaped_chars = {
                ord("n"): 10,
                ord("r"): 13,
                ord("t"): 9,
                ord("b"): 8,
                ord("f"): 12,
            }
            out.append(escaped_chars[escaped])
        elif escaped in b"\r\n":
            if escaped == 13 and index < len(body) and body[index] == 10:
                index += 1
        elif 48 <= escaped <= 55:
            octal = bytes([escaped])
            for _ in range(2):
                if index < len(body) and 48 <= body[index] <= 55:
                    octal += bytes([body[index]])
                    index += 1
            out.append(int(octal, 8))
        else:
            out.append(escaped)
    return _decode_pdf_text_bytes(bytes(out))


def _decode_pdf_hex(token: bytes) -> str:
    cleaned = re.sub(rb"\s+", b"", token)
    if len(cleaned) % 2:
        cleaned += b"0"
    try:
        return _decode_pdf_text_bytes(bytes.fromhex(cleaned.decode("ascii")))
    except ValueError:
        return ""


def _decode_pdf_text_bytes(data: bytes) -> str:
    if data.startswith(b"\xfe\xff"):
        try:
            return data[2:].decode("utf-16-be")
        except UnicodeDecodeError:
            return ""
    text, _encoding = _decode_text(data)
    return text


def _warning(code: str, message: str, *, level: str = "info") -> dict[str, object]:
    return {"level": level, "code": code, "message": message}


class _HtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_stack: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table_stack.append([])
        elif tag == "tr" and self._table_stack:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(html_lib.unescape(" ".join(self._cell).strip()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table_stack:
            self._table_stack[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._table_stack:
            self.tables.append(self._table_stack.pop())


class _HtmlTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self._parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"br", "p", "div", "li", "tr", "td", "th", "h1", "h2", "h3"}:
            self._flush()

    def close(self) -> None:
        self._flush()
        super().close()

    def _flush(self) -> None:
        if self._parts:
            self.lines.append(" ".join(self._parts))
            self._parts = []
