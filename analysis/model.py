"""Transparent ridge-regression baseline and chronological backtest."""
import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from scrapers.names import parse_pumpkin_name

from .data import decimal, load_records

FEATURES = ["intercept", "year_decades", "mother_weight_delta", "mother_known",
            "father_weight_delta", "father_known", "grower_skill"]
LB_PER_KG = 2.2046226218


def make_features(year, mother_weight, father_weight, grower_prior_mean=None,
                  grower_prior_count=0, global_prior_mean=1000.0):
    skill = ((grower_prior_mean - global_prior_mean) * grower_prior_count /
             (grower_prior_count + 5)) if grower_prior_mean is not None and grower_prior_count else 0.0
    return [
        1.0, (year - 2013) / 10,
        (mother_weight - 1000) / 1000 if mother_weight is not None else 0.0,
        float(mother_weight is not None),
        (father_weight - 1000) / 1000 if father_weight is not None else 0.0,
        float(father_weight is not None), skill / 1000,
    ]


def feature_rows(records):
    by_year = defaultdict(list)
    for row in records:
        weight = decimal(row.get("weight_lbs"))
        if weight is not None and weight > 0:
            by_year[int(row["year"])].append((row, float(weight)))
    prior_weights = []
    grower_history = defaultdict(list)
    examples = []
    for year in sorted(by_year):
        global_prior = statistics.mean(prior_weights) if prior_weights else 1000.0
        for row, target in by_year[year]:
            mother = parse_pumpkin_name(row.get("mother", ""), reference_year=year)
            father = parse_pumpkin_name(row.get("father", ""), reference_year=year)
            mother_weight = float(mother.weight_lbs) if mother.weight_lbs else None
            father_weight = float(father.weight_lbs) if father.weight_lbs else None
            if father.kind == "self":
                father_weight = mother_weight
            history = grower_history[row.get("grower", "").casefold().strip()]
            features = make_features(year, mother_weight, father_weight,
                                     statistics.mean(history) if history else None,
                                     len(history), global_prior)
            examples.append({
                "record_id": row["record_id"], "year": year, "name": row["name"],
                "grower": row.get("grower", ""), "target_lbs": target,
                "mother_lbs": mother_weight, "father_lbs": father_weight,
                "grower_prior_count": len(history), "grower_prior_mean_lbs": statistics.mean(history) if history else None,
                "global_prior_mean_lbs": global_prior, "features": features,
            })
        for row, target in by_year[year]:
            prior_weights.append(target)
            grower_history[row.get("grower", "").casefold().strip()].append(target)
    return examples


def solve(matrix, vector):
    n = len(vector)
    a = [list(row) + [value] for row, value in zip(matrix, vector)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(a[row][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError("Singular regression matrix")
        a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        a[col] = [value / scale for value in a[col]]
        for row in range(n):
            if row == col:
                continue
            factor = a[row][col]
            a[row] = [left - factor * right for left, right in zip(a[row], a[col])]
    return [row[-1] for row in a]


def fit(examples, ridge=10.0):
    n = len(FEATURES)
    gram = [[0.0] * n for _ in range(n)]
    rhs = [0.0] * n
    for example in examples:
        x, y = example["features"], example["target_lbs"]
        for i in range(n):
            rhs[i] += x[i] * y
            for j in range(n):
                gram[i][j] += x[i] * x[j]
    for i in range(1, n):
        gram[i][i] += ridge
    return solve(gram, rhs)


def predict(features, coefficients):
    return sum(x * coefficient for x, coefficient in zip(features, coefficients))


def probability_above(prediction_lbs, threshold_lbs, residual_sd):
    if residual_sd <= 0:
        return float(prediction_lbs > threshold_lbs)
    return .5 * math.erfc((threshold_lbs - prediction_lbs) / (residual_sd * math.sqrt(2)))


def metrics(examples, coefficients, residual_sd, threshold_lbs):
    if not examples:
        return {}
    errors = [predict(row["features"], coefficients) - row["target_lbs"] for row in examples]
    probabilities = [probability_above(predict(row["features"], coefficients), threshold_lbs, residual_sd) for row in examples]
    actual = [float(row["target_lbs"] > threshold_lbs) for row in examples]
    return {
        "n": len(examples), "mae_lbs": statistics.mean(abs(e) for e in errors),
        "rmse_lbs": math.sqrt(statistics.mean(e * e for e in errors)),
        "bias_lbs": statistics.mean(errors),
        "p90_interval_coverage": statistics.mean(abs(e) <= 1.645 * residual_sd for e in errors),
        "threshold_prevalence": statistics.mean(actual),
        "brier": statistics.mean((p - a) ** 2 for p, a in zip(probabilities, actual)),
    }


def train(input_path, output_dir, holdout_start=2024, threshold_kg=1000):
    examples = feature_rows(load_records(input_path))
    train_rows = [row for row in examples if 2017 <= row["year"] < holdout_start]
    test_rows = [row for row in examples if row["year"] >= holdout_start]
    if len(train_rows) < 100 or not test_rows:
        raise ValueError("Need at least 100 training rows and a later-year holdout")
    coefficients = fit(train_rows)
    residuals = [row["target_lbs"] - predict(row["features"], coefficients) for row in train_rows]
    residual_sd = math.sqrt(statistics.mean(error * error for error in residuals))
    threshold_lbs = threshold_kg * LB_PER_KG
    train_metrics = metrics(train_rows, coefficients, residual_sd, threshold_lbs)
    test_metrics = metrics(test_rows, coefficients, residual_sd, threshold_lbs)
    constant = statistics.mean(row["target_lbs"] for row in train_rows)
    constant_test_mae = statistics.mean(abs(row["target_lbs"] - constant) for row in test_rows)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = output_dir / "training_dataset.csv"
    fields = ["record_id", "year", "name", "grower", "target_lbs", "mother_lbs", "father_lbs",
              "grower_prior_count", "grower_prior_mean_lbs", "global_prior_mean_lbs"] + FEATURES
    with dataset_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in examples:
            writer.writerow({**{field: row.get(field) for field in fields},
                             **dict(zip(FEATURES, row["features"]))})
    model = {
        "type": "ridge_baseline", "features": FEATURES,
        "coefficients": dict(zip(FEATURES, coefficients)), "residual_sd_lbs": residual_sd,
        "train_years": f"2017-{holdout_start - 1}", "test_years": f"{holdout_start}-{max(row['year'] for row in test_rows)}",
        "train_metrics": train_metrics, "test_metrics": test_metrics,
        "constant_baseline_test_mae_lbs": constant_test_mae,
        "threshold_kg": threshold_kg, "training_n": len(train_rows),
        "global_mean_latest_lbs": statistics.mean(row["target_lbs"] for row in examples),
    }
    (output_dir / "baseline_model.json").write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# Базовый прогноз веса потомка", "",
        f"Обучение: **{model['train_years']}** ({len(train_rows):,} плодов); "
        f"проверка на более поздних сезонах: **{model['test_years']}** ({len(test_rows):,}).", "",
        "Признаки: вес материнского семени, вес опылителя, год и средний вес предыдущих плодов того же выращивателя. "
        "Для `Self` вес отца равен весу матери. История выращивателя включает только предыдущие годы. "
        "OTT и % от таблицы веса не используются, поскольку они неизвестны до выращивания.", "",
        "| Показатель | Обучение | Поздние годы |", "|---|---:|---:|",
        f"| MAE, lb | {train_metrics['mae_lbs']:.1f} | {test_metrics['mae_lbs']:.1f} |",
        f"| RMSE, lb | {train_metrics['rmse_lbs']:.1f} | {test_metrics['rmse_lbs']:.1f} |",
        f"| Смещение, lb | {train_metrics['bias_lbs']:.1f} | {test_metrics['bias_lbs']:.1f} |",
        f"| Покрытие 90% прогнозного интервала | {train_metrics['p90_interval_coverage']:.1%} | {test_metrics['p90_interval_coverage']:.1%} |",
        f"| Доля > {threshold_kg:g} кг | {train_metrics['threshold_prevalence']:.1%} | {test_metrics['threshold_prevalence']:.1%} |",
        f"| Brier score для > {threshold_kg:g} кг | {train_metrics['brier']:.4f} | {test_metrics['brier']:.4f} |", "",
        f"Для сравнения: прогноз одной средней величиной ({constant:.1f} lb) даёт на поздних годах "
        f"MAE **{constant_test_mae:.1f} lb**.", "",
        f"Прогнозный интервал рассчитан как прогноз ±1.645 × {residual_sd:.1f} lb (ошибка на обучении). "
        "Проверка покрытия на поздних годах показывает, насколько этот интервал надёжен при временном сдвиге. "
        "Вероятность превышения порога рассчитана из нормального распределения ошибок; отдельная калибровка не проводилась.", "",
        "Коэффициенты и поправки (вес в фунтах):", "",
        *[f"- `{name}`: {value:+.2f}" for name, value in zip(FEATURES, coefficients)], "",
        "Ограничение: это описательная модель по участникам GPC, а не оценка генетического эффекта скрещивания. "
        "Особенно редкие тяжёлые плоды и новые выращиватели требуют отдельной проверки перед использованием вероятности в продукте.", "",
    ]
    (output_dir / "MODEL.md").write_text("\n".join(lines), encoding="utf-8")
    return model


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--holdout-start", type=int, default=2024)
    parser.add_argument("--threshold-kg", type=float, default=1000)
    args = parser.parse_args()
    result = train(args.input, args.output_dir, args.holdout_start, args.threshold_kg)
    print(json.dumps({"train": result["train_metrics"], "test": result["test_metrics"]}, indent=2))
