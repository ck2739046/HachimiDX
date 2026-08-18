import unittest

from pydantic import ValidationError

from src.core.schemas.settings_model import SettingsModel
from src.services.settings_manage import SettingsManage


class TestSettingsExtraKeys(unittest.TestCase):

    def test_settings_model_rejects_extra_keys(self):
        with self.assertRaises(ValidationError):
            SettingsModel(unexpected_key=True)

    def test_check_data_silently_removes_extra_keys(self):
        input_data = SettingsModel().model_dump(mode="json")
        input_data["unexpected_key"] = True

        has_changes, need_backup, normalized = SettingsManage._check_data(input_data)

        self.assertTrue(has_changes)
        self.assertFalse(need_backup)
        self.assertNotIn("unexpected_key", normalized)
        self.assertEqual(normalized, SettingsModel().model_dump(mode="json"))


if __name__ == "__main__":
    unittest.main(verbosity=2)