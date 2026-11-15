import csv
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

FIELDS = [
    "source", "source_url", "name", "name_inferred", "year", "weight_lbs",
    "weight_kg", "grower", "city", "state", "country", "weighoff_site",
    "mother", "father", "ott", "estimated_weight_lbs", "pct_chart",
    "status", "color",
]


def clean(value):
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip(" .")


def number(value):
    value = clean(value).replace(",", "")
    try:
        return str(Decimal(value)) if value else ""
    except InvalidOperation:
        return ""


def parse_name(value):
    """Return (weight in pounds, grower label, year); preserve unparsed names."""
    match = re.match(r"^\s*(\d[\d,.]*)\s+(.+?)\s+(\d{4})(?:\s+.*)?$", clean(value))
    if not match:
        return "", "", ""
    return number(match.group(1)), clean(match.group(2)), match.group(3)


def write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
