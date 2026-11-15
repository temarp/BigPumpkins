import json
import tempfile
import unittest
from pathlib import Path

from analysis.calibration import fit_intercept, logit, sigmoid
from analysis.model import FEATURES
from analysis.predict import forecast


class CalibrationTests(unittest.TestCase):
    def test_odds_shift_matches_observed_event_count(self):
        raw = [0.01, 0.02, 0.05, 0.10, 0.20]
        labels = [0, 0, 0, 0, 1]
        shift = fit_intercept(raw, labels)
        self.assertAlmostEqual(sum(sigmoid(shift + logit(p)) for p in raw), 1, places=7)
        self.assertLess(sigmoid(shift + logit(raw[0])), sigmoid(shift + logit(raw[-1])))

    def test_forecast_applies_only_matching_threshold(self):
        model = {
            "coefficients": dict(zip(FEATURES, [1000, 0, 0, 0, 0, 0, 0])),
            "residual_sd_lbs": 400, "global_mean_latest_lbs": 700,
            "training_n": 100,
            "calibration": {"threshold_kg": 1000, "intercept": 1.0,
                            "slope": 1.0, "calibration_years": "2020-2025"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            path.write_text(json.dumps(model), encoding="utf-8")
            matching = forecast(path, "1000 Mother 2024", "Self", 2025, 1000)
            other = forecast(path, "1000 Mother 2024", "Self", 2025, 900)
        self.assertTrue(matching["calibration_applied"])
        self.assertGreater(matching["probability_above_threshold"],
                           matching["raw_probability_above_threshold"])
        self.assertFalse(other["calibration_applied"])
        self.assertEqual(other["probability_above_threshold"],
                         other["raw_probability_above_threshold"])


if __name__ == "__main__":
    unittest.main()
