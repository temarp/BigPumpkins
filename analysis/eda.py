"""Reproducible EDA for the collected GPC CSV."""
import argparse
import csv
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from scrapers.names import parse_pumpkin_name

from .data import decimal, load_records, resolve_parents


def quantile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def write_table(path, fields, rows):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def analyze(input_path, output_dir):
    records = load_records(input_path)
    if not records:
        raise ValueError("Input CSV is empty")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    links = resolve_parents(records)
    measured = [(row, float(value)) for row in records if (value := decimal(row.get("weight_lbs"))) and value > 0]
    values = [value for _, value in measured]
    by_year = defaultdict(list)
    for row, weight in measured:
        by_year[row["year"]].append(weight)
    yearly = [
        {"year": year, "count": len(weights), "median_lbs": round(statistics.median(weights), 1),
         "p90_lbs": round(quantile(weights, .9), 1), "max_lbs": round(max(weights), 1)}
        for year, weights in sorted(by_year.items())
    ]
    write_table(output_dir / "yearly.csv", list(yearly[0]), yearly)
    boundaries = [0, 250, 500, 750, 1000, 1250, 1500, 1750, 2000, 2250, 2500, 2750, 3000, 3500]
    histogram = [
        {"range_lbs": f"[{left}, {right})", "count": sum(left <= value < right for value in values)}
        for left, right in zip(boundaries, boundaries[1:])
    ]
    histogram.append({"range_lbs": ">=3500", "count": sum(value >= 3500 for value in values)})
    write_table(output_dir / "histogram.csv", ["range_lbs", "count"], histogram)
    outliers = []
    for year, weights in by_year.items():
        if len(weights) < 20:
            continue
        q1, q3 = quantile(weights, .25), quantile(weights, .75)
        lower, upper = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
        outliers.extend(
            {"record_id": row["record_id"], "year": year, "name": row["name"],
             "weight_lbs": weight, "reason": "low" if weight < lower else "high"}
            for row, weight in measured if row["year"] == year and (weight < lower or weight > upper)
        )
    write_table(output_dir / "outliers.csv", ["record_id", "year", "name", "weight_lbs", "reason"], outliers)
    fields = ["name", "weight_lbs", "weight_kg", "grower", "city", "state", "country",
              "weighoff_site", "mother", "father", "ott", "estimated_weight_lbs", "pct_chart", "color"]
    fill = {}
    for field in fields:
        count = sum(bool(row.get(field, "").strip()) and
                    (field not in {"ott", "estimated_weight_lbs"} or decimal(row[field]) != 0)
                    for row in records)
        fill[field] = (count, 100 * count / len(records))
    parent_stats = {}
    parent_recognition = {}
    for role in ("mother", "father"):
        kinds = Counter(parse_pumpkin_name(row.get(role, ""), reference_year=int(row["year"])).kind for row in records)
        parent_stats[role] = kinds
        filled = sum(bool(row.get(role, "").strip()) for row in records)
        parent_recognition[role] = (filled - kinds["invalid"]) / filled if filled else 0
    matched = Counter(role for (_, role), parent_id in links.items() if parent_id)
    child_sets = defaultdict(set)
    for (child_id, _), parent_id in links.items():
        if parent_id:
            child_sets[parent_id].add(child_id)
    children = {parent_id: len(child_ids) for parent_id, child_ids in child_sets.items()}
    status = Counter(row.get("status", "") or "normal" for row in records)
    record_fields = [key for key in records[0] if key != "record_id"]
    duplicate_rows = sum(count - 1 for count in Counter(tuple(row.get(key, "") for key in record_fields) for row in records).values())
    unit_mismatches = sum(abs(float(row["weight_kg"]) - float(row["weight_lbs"]) * .45359237) > 1
                          for row in records if decimal(row.get("weight_kg")) is not None)
    lines = [
        "# EDA: результаты GPC", "",
        f"Источник: `{input_path}`. Записей: **{len(records):,}**, с положительным весом: **{len(values):,}**.", "",
        "## Вес", "",
        f"Медиана: **{statistics.median(values):,.1f} lb** ({statistics.median(values) * .45359237:,.1f} кг). "
        f"P10/P90: **{quantile(values,.1):,.1f}/{quantile(values,.9):,.1f} lb**. "
        f"Минимум/максимум: **{min(values):,.1f}/{max(values):,.1f} lb**.", "",
        "| Диапазон, lb | Число |", "|---|---:|",
        *[f"| {item['range_lbs']} | {item['count']} |" for item in histogram], "",
        "## По годам", "", "| Год | Записей | Медиана, lb | P90, lb | Макс., lb |", "|---|---:|---:|---:|---:|",
        *[f"| {r['year']} | {r['count']} | {r['median_lbs']} | {r['p90_lbs']} | {r['max_lbs']} |" for r in yearly], "",
        "## Заполненность", "", "| Поле | Заполнено | Доля |", "|---|---:|---:|",
        *[f"| {field} | {count:,} | {pct:.1f}% |" for field, (count, pct) in fill.items()], "",
        "## Родители и потомки", "",
        f"Мать: распознано как обозначение тыквы **{parent_stats['mother']['pumpkin']:,}**; "
        f"однозначно найдено в этом наборе **{matched['mother']:,}**. "
        f"Отец: распознано **{parent_stats['father']['pumpkin']:,}**; "
        f"однозначно найдено **{matched['father']:,}**. "
        f"Самоопыление (Self): **{parent_stats['father']['self']:,}**; "
        f"открытое опыление (Open): **{parent_stats['father']['open']:,}**.", "",
        f"Тыкв с хотя бы одним найденным потомком: **{len(children):,}**; "
        f"медиана числа связанных потомков: **{statistics.median(children.values()) if children else 0:g}**. "
        "Это нижняя оценка: GPC не содержит всех потомков, а неоднозначные имена не связываются автоматически.", "",
        "## Качество данных", "",
        f"Распознано непустых обозначений родителей: мать **{parent_recognition['mother']:.1%}**, "
        f"отец **{parent_recognition['father']:.1%}** (включая Self/Open/Unknown). "
        "Год указан или однозначно выводится не у всех обозначений.", "",
        f"Полностью повторяющихся строк: **{duplicate_rows}**; "
        f"расхождений между lb и kg более 1 кг: **{unit_mismatches}**; "
        f"плодов легче 1 lb: **{sum(value < 1 for value in values)}**.", "",
        f"Потенциальных выбросов по правилу 1.5×IQR внутри года: **{len(outliers):,}**. "
        "Они сохранены, поскольку могут быть реальными рекордами; список в `outliers.csv`.", "",
        "Статусы: " + ", ".join(f"{key}={value:,}" for key, value in status.most_common()) + ".", "",
        "Ограничения: выборка состоит из опубликованных результатов GPC; она не представляет все выращенные тыквы. "
        "Название плода в BigPumpkins восстановлено из веса, фамилии и года и может быть неоднозначным. "
        "OTT и процент от расчётного веса измеряются после выращивания, поэтому их нельзя использовать для прогноза до скрещивания.", "",
    ]
    (output_dir / "EDA.md").write_text("\n".join(lines), encoding="utf-8")
    return len(records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    print(f"Analyzed {analyze(args.input, args.output_dir)} rows")
