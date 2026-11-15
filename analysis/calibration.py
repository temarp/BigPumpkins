"""Chronological odds-shift calibration for a specified weight threshold."""
import argparse
import csv
import json
import math
import statistics
from pathlib import Path

from .data import load_records
from .model import LB_PER_KG, FEATURES, feature_rows, fit, predict, probability_above


def sigmoid(value):
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    positive = math.exp(value)
    return positive / (1 + positive)


def logit(probability):
    p = min(1 - 1e-12, max(1e-12, probability))
    return math.log(p / (1 - p))


def fit_intercept(raw, labels):
    """Shift only log odds; leave ranking and high-risk spread unchanged."""
    target = sum(labels)
    low, high = -20.0, 20.0
    for _ in range(80):
        middle = (low + high) / 2
        expected = sum(sigmoid(middle + logit(p)) for p in raw)
        if expected < target:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def evaluate(probabilities, labels):
    n = len(labels)
    expected = sum(probabilities)
    expected_sd = math.sqrt(sum(p * (1 - p) for p in probabilities))
    return {
        "n": n, "events": sum(labels), "observed_rate": statistics.mean(labels),
        "expected_events": expected, "expected_events_sd": expected_sd,
        "event_gap_sd": (sum(labels) - expected) / expected_sd if expected_sd else 0,
        "mean_probability": statistics.mean(probabilities),
        "brier": statistics.mean((p - y) ** 2 for p, y in zip(probabilities, labels)),
        "log_loss": statistics.mean(-y * math.log(max(p, 1e-12)) - (1 - y) * math.log(max(1 - p, 1e-12))
                                    for p, y in zip(probabilities, labels)),
    }


def score_fold(examples, fit_before, score_year, threshold_lbs):
    training = [row for row in examples if 2017 <= row["year"] < fit_before]
    scoring = [row for row in examples if row["year"] == score_year]
    coefficients = fit(training)
    sigma = math.sqrt(statistics.mean((row["target_lbs"] - predict(row["features"], coefficients)) ** 2
                                      for row in training))
    raw = [probability_above(predict(row["features"], coefficients), threshold_lbs, sigma) for row in scoring]
    labels = [int(row["target_lbs"] > threshold_lbs) for row in scoring]
    return raw, labels


def reliability_bins(raw, calibrated, labels, bins=10):
    order = sorted(range(len(raw)), key=lambda index: calibrated[index])
    result = []
    for bin_index in range(bins):
        group = order[len(order) * bin_index // bins:len(order) * (bin_index + 1) // bins]
        result.append({
            "bin": bin_index + 1, "count": len(group), "events": sum(labels[i] for i in group),
            "observed_rate": sum(labels[i] for i in group) / len(group),
            "raw_mean": statistics.mean(raw[i] for i in group),
            "calibrated_mean": statistics.mean(calibrated[i] for i in group),
        })
    return result


def calibrate(input_path, model_path, output_dir, threshold_kg=1000):
    model = json.loads(Path(model_path).read_text(encoding="utf-8"))
    if model["features"] != FEATURES:
        raise ValueError("Model feature layout changed")
    examples = feature_rows(load_records(input_path))
    threshold_lbs = threshold_kg * LB_PER_KG
    latest_year = max(row["year"] for row in examples)
    if latest_year < 2024:
        raise ValueError("Need data through at least 2024 for chronological calibration")
    first_test_year = max(2024, latest_year - 1)
    folds = {year: score_fold(examples, year, year, threshold_lbs)
             for year in range(2020, latest_year + 1)}
    if sum(sum(folds[year][1]) for year in range(2020, first_test_year)) < 20:
        raise ValueError("Too few threshold exceedances for calibration")
    test_raw, test_labels, test_adjusted = [], [], []
    per_year = {}
    for year in range(first_test_year, latest_year + 1):
        earlier_raw = sum((folds[previous][0] for previous in range(2020, year)), [])
        earlier_labels = sum((folds[previous][1] for previous in range(2020, year)), [])
        intercept, slope = fit_intercept(earlier_raw, earlier_labels), 1.0
        raw, labels = folds[year]
        adjusted = [sigmoid(intercept + slope * logit(p)) for p in raw]
        per_year[year] = {"raw": evaluate(raw, labels), "adjusted": evaluate(adjusted, labels),
                          "intercept": intercept, "slope": slope}
        test_raw.extend(raw)
        test_labels.extend(labels)
        test_adjusted.extend(adjusted)
    all_raw = sum((folds[year][0] for year in range(2020, latest_year + 1)), [])
    all_labels = sum((folds[year][1] for year in range(2020, latest_year + 1)), [])
    intercept, slope = fit_intercept(all_raw, all_labels), 1.0
    all_adjusted = [sigmoid(intercept + slope * logit(p)) for p in all_raw]
    final_training = [row for row in examples if 2017 <= row["year"] <= latest_year]
    final_coefficients = fit(final_training)
    final_sigma = math.sqrt(statistics.mean(
        (row["target_lbs"] - predict(row["features"], final_coefficients)) ** 2
        for row in final_training))
    result = {
        "method": "rolling_origin_odds_shift", "threshold_kg": threshold_kg,
        "calibration_years": f"2020-{latest_year}",
        "test_years": f"{first_test_year}-{latest_year} rolling",
        "intercept": intercept, "slope": slope, "per_year": per_year,
        "calibration_raw": evaluate(all_raw, all_labels),
        "calibration_adjusted": evaluate(all_adjusted, all_labels),
        "test_raw": evaluate(test_raw, test_labels), "test_adjusted": evaluate(test_adjusted, test_labels),
    }
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    bins = reliability_bins(test_raw, test_adjusted, test_labels)
    with (output_dir / "calibration_bins.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(bins[0]))
        writer.writeheader()
        writer.writerows(bins)
    calibrated_model = {**model, "coefficients": dict(zip(FEATURES, final_coefficients)),
                        "residual_sd_lbs": final_sigma, "train_years": f"2017-{latest_year}",
                        "training_n": len(final_training), "threshold_kg": threshold_kg,
                        "global_mean_latest_lbs": statistics.mean(row["target_lbs"] for row in examples),
                        "calibration": {key: result[key] for key in
                                        ("method", "threshold_kg", "calibration_years", "intercept", "slope")}}
    for stale_key in ("train_metrics", "test_metrics", "test_years", "constant_baseline_test_mae_lbs"):
        calibrated_model.pop(stale_key, None)
    calibrated_model["backtest_calibration"] = {
        "raw": result["test_raw"], "adjusted": result["test_adjusted"]}
    (output_dir / "calibrated_model.json").write_text(
        json.dumps(calibrated_model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    def row(title, item):
        return (f"| {title} | {item['events']}/{item['n']} | {item['expected_events']:.1f} | "
                f"{item['event_gap_sd']:+.1f} | {item['brier']:.5f} | {item['log_loss']:.5f} |")
    lines = [
        f"# Калибровка вероятности > {threshold_kg:g} кг", "",
        f"Проверка выполнена по времени на сезонах {first_test_year}–{latest_year}: "
        "для каждого года использованы только предыдущие сезоны. Базовая модель и калибратор обновлялись после каждого сезона. "
        "Калибратор обучался на прогнозах прошлых лет, для которых базовая модель видела только более ранние данные.", "",
        f"Для будущего сезона модель обучена до {latest_year} года включительно. Формула: "
        f"`sigmoid({intercept:.4f} + {slope:.4f} × logit(p_raw))`. "
        "Она сохраняет порядок пар по вероятности внутри одного года.", "",
        "| Выборка | Реальных событий | Ожидалось | Разница, σ | Brier ↓ | Log loss ↓ |",
        "|---|---:|---:|---:|---:|---:|",
        *[row(f"{year}, {stage}", per_year[year][key])
          for year in per_year for stage, key in (("до", "raw"), ("после", "adjusted"))],
        row("Все проверяемые годы, до", result["test_raw"]),
        row("Все проверяемые годы, после", result["test_adjusted"]), "",
        "Разница в σ — отклонение числа событий от суммы вероятностей, делённое на ожидаемое "
        "стандартное отклонение при независимых исходах. Общие условия выращивания могут нарушать "
        "предположение о независимости.", "",
        "## Проверка по группам риска", "",
        "| Дециль | Плодов | Событий | Наблюдаемая доля | Исходная оценка | После калибровки |",
        "|---|---:|---:|---:|---:|---:|",
        *[f"| {b['bin']} | {b['count']} | {b['events']} | {b['observed_rate']:.2%} | "
          f"{b['raw_mean']:.2%} | {b['calibrated_mean']:.2%} |" for b in bins], "",
        "Калибровка рассчитана только для указанного порога. Для другого веса нужна отдельная "
        "проверка; функция прогноза возвращает исходную оценку с `calibration_applied=false`. "
        "При смене сезона или состава участников частота редких событий может измениться. "
        "Даже после калибровки может оставаться систематическое расхождение; проверяйте число ожидаемых "
        "и реальных событий, а также Brier/log loss. Модель для будущего сезона ещё не имеет независимой проверки.", "",
    ]
    (output_dir / "CALIBRATION.md").write_text("\n".join(lines), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--model", default="reports/baseline_model.json")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--threshold-kg", type=float, default=1000)
    args = parser.parse_args()
    if args.threshold_kg <= 0:
        parser.error("Threshold must be positive")
    outcome = calibrate(args.input, args.model, args.output_dir, args.threshold_kg)
    print(json.dumps({"test_raw": outcome["test_raw"], "test_adjusted": outcome["test_adjusted"]}, indent=2))
