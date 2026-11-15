"""Conservative parsing of pumpkin/seed labels found on both sites."""
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class PumpkinName:
    raw: str
    kind: str  # pumpkin, self, open, unknown, invalid
    weight_lbs: Decimal | None = None
    grower: str | None = None
    year: int | None = None
    year_inferred: bool = False
    flags: tuple[str, ...] = ()


_PREFIX = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(.*)$", re.I)
_YEAR = re.compile(r"\b((?:19|20)\d{2}|\d{2})\b")
_FLAGS = {"DMG", "EXH", "UOW", "EST", "SQ", "SQUASH"}
_SPECIAL = {
    "self": "self", "selfed": "self", "same": "self",
    "open": "open", "op": "open", "unknown": "unknown", "unk": "unknown",
    "n/a": "unknown", "na": "unknown", "?": "unknown", "": "unknown",
}


def parse_pumpkin_name(raw: str, *, reference_year: int | None = None) -> PumpkinName:
    """Extract weight, grower and year without inventing missing fields.

    A two-digit year is resolved only when the child's/reference year is known.
    For example, '24' with reference_year=2025 means 2024.
    """
    text = " ".join(str(raw or "").replace("\xa0", " ").split()).strip(" .")
    kind = _SPECIAL.get(text.casefold())
    if kind:
        return PumpkinName(text, kind)
    match = _PREFIX.match(text)
    if not match:
        return PumpkinName(text, "invalid")
    try:
        weight = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return PumpkinName(text, "invalid")
    if weight <= 0:
        return PumpkinName(text, "invalid")
    rest = match.group(2).strip()
    # Standalone trailing markers, not part of a grower's name.
    tokens = rest.split()
    flags = tuple(token.upper() for token in tokens if token.upper() in _FLAGS)
    rest = " ".join(token for token in tokens if token.upper() not in _FLAGS)
    years = list(_YEAR.finditer(rest))
    year = None
    inferred = False
    if years:
        selected = years[-1]
        year_text = selected.group(1)
        if len(year_text) == 4:
            year = int(year_text)
        elif reference_year is not None:
            options = [1900 + int(year_text), 2000 + int(year_text)]
            plausible = [candidate for candidate in options if candidate <= reference_year]
            if plausible:
                year = max(plausible)
                inferred = True
        rest = (rest[:selected.start()] + " " + rest[selected.end():]).strip()
    grower = " ".join(rest.split()).strip(" ,.-") or None
    return PumpkinName(text, "pumpkin", weight, grower, year, inferred, flags)
