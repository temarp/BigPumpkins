import csv
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from scrapers.names import parse_pumpkin_name


def decimal(value):
    try:
        return Decimal(str(value).replace(",", "")) if str(value).strip() else None
    except InvalidOperation:
        return None


def load_records(path):
    with open(path, encoding="utf-8-sig", newline="") as stream:
        records = list(csv.DictReader(stream))
    for i, row in enumerate(records, 1):
        row["record_id"] = f"{row.get('year', '')}:{i}"
    return records


def resolve_parents(records):
    """Match a seed name to an earlier measured fruit only when unambiguous.

    First require exact weight and year. Without a year, require exact weight,
    an exact normalized grower token, and exactly one earlier candidate.
    """
    by_weight_year = defaultdict(list)
    by_weight = defaultdict(list)
    for row in records:
        weight = decimal(row.get("weight_lbs"))
        try:
            year = int(row["year"])
        except (ValueError, KeyError):
            continue
        if weight is not None:
            by_weight_year[(weight, year)].append(row)
            by_weight[weight].append(row)
    links = {}
    for row in records:
        try:
            child_year = int(row["year"])
        except (ValueError, KeyError):
            continue
        for role in ("mother", "father"):
            parsed = parse_pumpkin_name(row.get(role, ""), reference_year=child_year)
            if parsed.kind == "self" and role == "father":
                links[(row["record_id"], role)] = links.get((row["record_id"], "mother"))
                continue
            if parsed.kind != "pumpkin" or parsed.weight_lbs is None:
                continue
            if parsed.year:
                candidates = [r for r in by_weight_year[(parsed.weight_lbs, parsed.year)] if int(r["year"]) < child_year]
            else:
                candidates = [r for r in by_weight[parsed.weight_lbs] if int(r["year"]) < child_year]
            if parsed.grower:
                token = parsed.grower.casefold().replace(" ", "")
                named = [r for r in candidates if token in (r.get("grower", "") + " " + r.get("name", "")).casefold().replace(" ", "")]
                candidates = named
            if len(candidates) == 1:
                links[(row["record_id"], role)] = candidates[0]["record_id"]
    return links
