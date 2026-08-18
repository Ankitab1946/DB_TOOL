"""Workbook/header normalization and deterministic field derivations."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "prj_id": ("prjid", "prj id", "prj_id"),
    "prj_attribute_name": (
        "attribtue name to be viewed on historical and hitl",
        "attribute name to be viewed on historical and hitl",
        "prj attribute name",
        "attribute name",
    ),
    "prj_physical_attribute_name": (
        "prjphysical attribute name",
        "prj physical attribute name",
        "prj_physical_attribute_name",
    ),
    "section": ("section", "section to be used in both prjui", "section(to be used in both prjui)"),
    "sub_section": ("sub-section", "sub section", "sub-section to be showed in ui"),
    "data_type": ("data type", "data iype", "data type amount % ratio actual"),
    "calculated_or_reported": ("calculated or reported",),
    "calculation_logic": ("calculation logic", "calculation logic when attribute come under calculated or reported or calculated category"),
    "segment": ("segment", "segment where attribute needs to be captured used for scanning purpose"),
    "attribute_definition": ("attribute definition",),
    "attribute_description": (
        "attribute description",
        "attribute description proposed one-shot prompt based on which prjid will be mapped used in scanning",
    ),
    "display_order": ("display order", "display order to be used in showing prjui"),
    "tech_logic": ("tech description", "tech logic"),
    "display_name": ("display name", "attribute name"),
    "portfolio": ("portfolio", "portfolio/scope", "scope"),
}


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).replace("\ufeff", " ").replace("\xa0", " ")
    text = re.sub(r"[\r\n]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_pipe_values(value: object) -> str:
    """Normalize a pipe-separated multi-value field while preserving entry order.

    Example: ``" Assets | Liabilities | Assets "`` becomes
    ``"Assets|Liabilities"``. Empty pipe segments are ignored.
    """
    text = normalize_text(value)
    if not text:
        return ""
    values: list[str] = []
    seen: set[str] = set()
    for part in text.split("|"):
        item = normalize_text(part)
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            values.append(item)
    return "|".join(values)


def split_pipe_values(value: object) -> list[str]:
    normalized = normalize_pipe_values(value)
    return normalized.split("|") if normalized else []



def pair_pipe_values(section_value: object, subsection_value: object) -> list[tuple[str, str]]:
    """Return positional Section/Sub-Section pairs from pipe-separated values.

    ``"Total|Liabilities"`` and ``"Current|Current2"`` become::

        [("Total", "Current"), ("Liabilities", "Current2")]

    A single value on either side is broadcast across the multiple values on the
    other side. If both sides contain multiple values, their counts must match;
    otherwise the pairing would be ambiguous and a ``ValueError`` is raised.
    """
    sections = split_pipe_values(section_value)
    subsections = split_pipe_values(subsection_value)
    if not sections or not subsections:
        return []
    if len(sections) == len(subsections):
        return list(zip(sections, subsections))
    if len(sections) == 1:
        return [(sections[0], subsection) for subsection in subsections]
    if len(subsections) == 1:
        return [(section, subsections[0]) for section in sections]
    raise ValueError(
        "Section and Sub-Section pipe values must have matching counts, or one side must contain a single value. "
        f"Received {len(sections)} Section values and {len(subsections)} Sub-Section values."
    )

def normalize_header(value: object) -> str:
    text = normalize_text(value).lower()
    text = re.sub(r"[^a-z0-9%]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def detect_column_mapping(columns: Iterable[object]) -> dict[str, str]:
    normalized = {normalize_header(column): str(column) for column in columns}
    result: dict[str, str] = {}
    for target, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            key = normalize_header(alias)
            if key in normalized:
                result[target] = normalized[key]
                break
    return result


def portfolio_from_sheet_name(sheet_name: str) -> str:
    normalized = normalize_header(sheet_name)
    if "insurance" in normalized:
        return "Insurance"
    if "bank" in normalized:
        return "Banks"
    if "ukc" in normalized:
        return "UKC"
    if "corporate" in normalized or "general industries" in normalized:
        return "Corporate"
    return ""


def canonical_portfolio_label(portfolio: str) -> str:
    value = normalize_text(portfolio).lower()
    aliases = {
        "banks": "FI Banks",
        "fi banks": "FI Banks",
        "bank": "FI Banks",
        "insurance": "FI Insurance",
        "fi insurance": "FI Insurance",
        "corporate": "Corporate Corporate",
        "corporates": "Corporate Corporate",
        "corporate corporate": "Corporate Corporate",
        "ukc": "UKC UKC",
        "ukc ukc": "UKC UKC",
    }
    return aliases.get(value, normalize_text(portfolio))


def editable_from_mapping_type(value: str | None) -> str:
    normalized = normalize_text(value).lower()
    if normalized == "calculated":
        return "N"
    if normalized in {"reported", "repeated"}:
        return "Y"
    return "Y"


def mapping_type_from_value(value: str | None, original_type: str | None = None) -> str:
    normalized = normalize_text(value).lower()
    if normalized == "calculated":
        return "Calculated"
    if normalized == "reported":
        return "Reported"
    if normalized == "repeated":
        original = normalize_text(original_type).lower()
        return "Calculated" if original == "calculated" else "Reported"
    return normalize_text(value) or "Reported"


def generate_tech_logic(calculation_logic: str | None) -> str:
    """Keep PRJ references and arithmetic operators while removing descriptive labels."""
    text = normalize_text(calculation_logic)
    if not text or text.upper() == "NA":
        return "NA"
    first = re.search(r"\(?\bPRJ\d+\b\)?", text, flags=re.IGNORECASE)
    if not first:
        return "NA"
    expression = text[first.start():]
    tokens = re.findall(r"\(?\bPRJ\d+\b\)?|[=+\-*/]", expression, flags=re.IGNORECASE)
    if not tokens:
        return "NA"
    rendered: list[str] = []
    for token in tokens:
        if re.search(r"PRJ\d+", token, flags=re.IGNORECASE):
            prj = re.search(r"PRJ\d+", token, flags=re.IGNORECASE).group(0).upper()
            rendered.append(f"({prj})")
        else:
            rendered.append(token)
    return " ".join(rendered)


ABBREVIATIONS = {
    "buildings": "bldgs",
    "building": "bldg",
    "properties": "props",
    "property": "prop",
    "accumulated": "accum",
    "depreciation": "depr",
    "amortization": "amort",
    "liabilities": "liabs",
    "liability": "liab",
    "receivables": "recvbls",
    "receivable": "recvbl",
    "investments": "invst",
    "investment": "invst",
    "expenses": "exp",
    "expense": "exp",
    "revenue": "rev",
    "income": "inc",
}


def generate_physical_name(attribute_name: str) -> str:
    text = normalize_text(attribute_name).lower()
    parenthetical = re.findall(r"\(([^)]+)\)", text)
    text = re.sub(r"\([^)]+\)", " ", text)
    ordered = parenthetical + [text]
    words = re.findall(r"[a-z0-9]+", " ".join(ordered))
    stop = {"and", "the", "of", "for", "to"}
    normalized = [ABBREVIATIONS.get(word, word) for word in words if word not in stop]
    return " ".join(normalized)[:500]


def ensure_int(value: object, default: int = 0) -> int:
    if value is None or normalize_text(value) == "":
        return default
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default
