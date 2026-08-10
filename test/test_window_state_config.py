import unittest

from pydantic import ValidationError

from src.core.schemas.settings_model import MainAppWindowState, SettingsModel


class TestWindowStateConfig(unittest.TestCase):

    def test_window_state_defaults_to_none(self):
        settings = SettingsModel()

        self.assertTrue(settings.main_app_remember_window_state)
        self.assertIsNone(settings.main_app_window_state)

    def test_valid_window_state_round_trips(self):
        state_data = {
            "x": -1600,
            "y": 120,
            "width": 1320,
            "height": 930,
            "ui_scale": 85,
        }

        settings = SettingsModel(main_app_window_state=state_data)

        self.assertEqual(settings.main_app_window_state, MainAppWindowState(**state_data))
        self.assertEqual(
            settings.model_dump(mode="json")["main_app_window_state"],
            state_data,
        )

    def test_window_state_rejects_out_of_range_values(self):
        invalid_states = (
            {"x": 0, "y": 0, "width": 1239, "height": 930, "ui_scale": 100},
            {"x": 0, "y": 0, "width": 1320, "height": 899, "ui_scale": 100},
            {"x": 0, "y": 0, "width": 1320, "height": 930, "ui_scale": 49},
            {"x": 0, "y": 0, "width": 1320, "height": 930, "ui_scale": 201},
        )

        for state in invalid_states:
            with self.subTest(state=state), self.assertRaises(ValidationError):
                SettingsModel(main_app_window_state=state)

    def test_legacy_settings_without_window_state_still_load(self):
        legacy_data = SettingsModel().model_dump(mode="json")
        legacy_data.pop("main_app_remember_window_state")
        legacy_data.pop("main_app_window_state")

        settings = SettingsModel(**legacy_data)

        self.assertTrue(settings.main_app_remember_window_state)
        self.assertIsNone(settings.main_app_window_state)


if __name__ == "__main__":
    unittest.main(verbosity=2)
