"""GPC pumpkin results, one public HTML table per season."""
import re

from bs4 import BeautifulSoup

from .common import clean, number

URL = "https://www.bigpumpkins.com/WeighoffResultsGPC.aspx?c=P&y={year}"


def parse_results(html, year, source_url):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.ReportResults")
    if table is None:
        raise ValueError(f"GPC results table missing: {source_url}")
    headers = [clean(cell.get_text(" ", strip=True)) for cell in table.select("thead th")]
    required = {"Place", "Weight (lbs)", "Weight (kg)", "Seed (Mother)", "Pollinator (Father)"}
    if not required.issubset(headers):
        raise ValueError(f"GPC columns changed: {headers}")
    rows = []
    for tr in table.select("tbody tr"):
        cells = [clean(td.get_text(" ", strip=True)) for td in tr.find_all("td", recursive=False)]
        if len(cells) != len(headers):
            continue
        item = dict(zip(headers, cells))
        weight = number(item["Weight (lbs)"])
        if not weight or float(weight) <= 0:
            continue
        grower = item.get("Grower Name", "")
        surname = clean(grower.split(",", 1)[0]) if "," in grower else ""
        name = f"{weight.rstrip('0').rstrip('.') if '.' in weight else weight} {surname} {year}" if surname else ""
        place = item.get("Place", "")
        rows.append({
            "source": "bigpumpkins_gpc", "source_url": source_url,
            "name": name, "name_inferred": "1" if name else "0", "year": str(year),
            "weight_lbs": weight, "weight_kg": number(item.get("Weight (kg)")),
            "grower": grower, "city": item.get("City", ""),
            "state": item.get("State/Prov", ""), "country": item.get("Country", ""),
            "weighoff_site": item.get("GPC Site", ""),
            "mother": item.get("Seed (Mother)", ""),
            "father": item.get("Pollinator (Father)", ""),
            "ott": number(item.get("OTT")),
            "estimated_weight_lbs": number(item.get("Est. Weight")),
            "pct_chart": number(item.get("Pct. Chart")),
            "status": place if re.search(r"[A-Za-z]", place) else "",
        })
    if not rows:
        raise ValueError(f"GPC results table has no pumpkin rows: {source_url}")
    return rows
