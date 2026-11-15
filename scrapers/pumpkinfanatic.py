"""PumpkinFanatic detail, Top 500, and progeny pages."""
from urllib.parse import quote

from bs4 import BeautifulSoup, NavigableString

from .common import clean, number, parse_name

BASE = "https://tools.pumpkinfanatic.com"
TOP_URL = "https://www.pumpkinfanatic.com/tools/Top500Pumpkins.php"


def detail_url(name):
    return f"{BASE}/FruitDetail.php?FruitName={quote(name)}"


def progeny_url(name):
    return f"{BASE}/FruitProgeny.php?PN={quote(name)}"


def parse_top(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.tableborder")
    if table is None:
        raise ValueError("PumpkinFanatic Top 500 table missing")
    names = []
    for row in table.select("tr.trcenter"):
        link = row.select_one('a[href*="PumpkinsSeedGenetics.php?PN="]')
        if link:
            names.append(clean(link.get_text(" ", strip=True)))
    if not names:
        raise ValueError("PumpkinFanatic Top 500 table has no names")
    return list(dict.fromkeys(names))


def _labels(fieldset):
    values = {}
    for li in fieldset.select("li"):
        for label in li.find_all("b"):
            key = clean(label.get_text(" ", strip=True)).rstrip(":?")
            parts = []
            for sibling in label.next_siblings:
                if getattr(sibling, "name", None) == "b":
                    break
                if isinstance(sibling, NavigableString):
                    parts.append(str(sibling))
                elif getattr(sibling, "name", None) not in ("br", "input"):
                    parts.append(sibling.get_text(" ", strip=True))
            value = clean(" ".join(parts).split("......")[0])
            if value:
                values[key] = value
    return values


def parse_detail(html, source_url):
    soup = BeautifulSoup(html, "html.parser")
    fieldsets = soup.select("fieldset")
    if not fieldsets:
        raise ValueError(f"PumpkinFanatic detail missing: {source_url}")
    data = {}
    for fieldset in fieldsets:
        data.update(_labels(fieldset))
    name = data.get("Pumpkin name", "")
    if not name:
        raise ValueError(f"PumpkinFanatic pumpkin name missing: {source_url}")
    parsed_weight, _, parsed_year = parse_name(name)
    weight = number(data.get("Weight")) or parsed_weight
    year = data.get("Year Grown", "") or parsed_year
    if not year.isdigit():
        year = parsed_year
    return {
        "source": "pumpkinfanatic", "source_url": source_url, "name": name,
        "name_inferred": "0", "year": year, "weight_lbs": weight,
        "weight_kg": str(round(float(weight) * 0.45359237, 2)) if weight else "",
        "grower": clean(" ".join(filter(None, [data.get("First Name"), data.get("Last Name")]))),
        "city": data.get("City", ""), "state": data.get("State", ""),
        "country": data.get("Country", ""), "weighoff_site": data.get("Weighed At", ""),
        "mother": data.get("Seed", ""), "father": data.get("Pollinator", ""),
        "ott": number(data.get("OTT")),
        "estimated_weight_lbs": number(data.get("Estimated Weight")),
        "pct_chart": number(data.get("Percent Change in Weight")),
        "status": "DMG" if data.get("Pumpkin Damaged", "").lower() == "yes" else "",
        "color": data.get("Color", ""),
    }


def parse_progeny(html):
    soup = BeautifulSoup(html, "html.parser")
    result = []
    for fieldset in soup.select("fieldset"):
        legend = fieldset.find("legend")
        if not legend:
            continue
        heading = clean(legend.get_text(" ", strip=True))
        if not (heading.startswith("Planted Seed") or heading.startswith("Used to Pollinate")):
            continue
        for row in fieldset.select("table tr.trcenter"):
            cells = row.find_all("td", recursive=False)
            if len(cells) < 7:
                continue
            result.append({
                "name": clean(cells[0].get_text(" ", strip=True)),
                "mother": clean(cells[2].get_text(" ", strip=True)),
                "father": clean(cells[3].get_text(" ", strip=True)),
                "weight_lbs": number(cells[4].get_text(" ", strip=True)),
                "grower": clean(cells[6].get_text(" ", strip=True)),
                "relation": "mother" if heading.startswith("Planted Seed") else "father",
            })
    # Selfed fruit occurs in both tables.
    return list({(row["name"], row["mother"], row["father"]): row for row in result}.values())
