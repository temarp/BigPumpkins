"""Example single-pair forecast from the saved baseline model."""
import argparse
import json
from pathlib import Path

from scrapers.names import parse_pumpkin_name

from .calibration import logit, sigmoid
from .model import FEATURES, LB_PER_KG, make_features, predict, probability_above


def forecast(model_path, mother_name, father_name, year, threshold_kg,
             grower_prior_mean_lbs=None, grower_prior_count=0):
    model = json.loads(Path(model_path).read_text(encoding="utf-8"))
    mother = parse_pumpkin_name(mother_name, reference_year=year)
    father = parse_pumpkin_name(father_name, reference_year=year)
    if mother.kind != "pumpkin" or father.kind not in ("pumpkin", "self", "open", "unknown"):
        raise ValueError("Mother must be a pumpkin; father must be a pumpkin, Self, Open or Unknown")
    for parent in (mother, father):
        if parent.year is not None and parent.year >= year:
            raise ValueError("Parent year must precede child year")
    mother_weight = float(mother.weight_lbs)
    father_weight = (mother_weight if father.kind == "self" else
                     float(father.weight_lbs) if father.weight_lbs is not None else None)
    features = make_features(year, mother_weight, father_weight,
                             grower_prior_mean_lbs, grower_prior_count,
                             model["global_mean_latest_lbs"])
    coefficients = [model["coefficients"][name] for name in FEATURES]
    predicted_lbs = predict(features, coefficients)
    residual_sd = model["residual_sd_lbs"]
    raw_probability = probability_above(predicted_lbs, threshold_kg * LB_PER_KG, residual_sd)
    calibration = model.get("calibration")
    calibrated = bool(calibration and abs(calibration["threshold_kg"] - threshold_kg) < 1e-9)
    probability = (sigmoid(calibration["intercept"] + calibration["slope"] * logit(raw_probability))
                   if calibrated else raw_probability)
    return {
        "mother": mother.raw, "father": father.raw, "year": year,
        "predicted_weight_kg": round(predicted_lbs / LB_PER_KG, 1),
        "prediction_interval_90_kg": [round(max(0, predicted_lbs - 1.645 * residual_sd) / LB_PER_KG, 1),
                                      round((predicted_lbs + 1.645 * residual_sd) / LB_PER_KG, 1)],
        "threshold_kg": threshold_kg,
        "probability_above_threshold": round(probability, 6),
        "raw_probability_above_threshold": round(raw_probability, 6),
        "calibration_applied": calibrated,
        "calibration_years": calibration["calibration_years"] if calibrated else None,
        "training_n": model["training_n"],
        "contributions_lbs": {name: round(x * coefficient, 1)
                              for name, x, coefficient in zip(FEATURES, features, coefficients)},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="reports/calibrated_model.json")
    parser.add_argument("--mother", required=True)
    parser.add_argument("--father", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--threshold-kg", type=float, default=1000)
    parser.add_argument("--grower-prior-mean-lbs", type=float)
    parser.add_argument("--grower-prior-count", type=int, default=0)
    args = parser.parse_args()
    if args.threshold_kg <= 0 or args.grower_prior_count < 0:
        parser.error("Threshold must be positive and grower count nonnegative")
    result = forecast(args.model, args.mother, args.father, args.year, args.threshold_kg,
                      args.grower_prior_mean_lbs, args.grower_prior_count)
    print(json.dumps(result, indent=2, ensure_ascii=False))
