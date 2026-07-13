import unittest

from settings import DEFAULT_FEATURES, get_group_features, set_group_feature


class SettingsTests(unittest.TestCase):
    def test_new_group_uses_all_enabled_defaults(self):
        features = get_group_features({})
        self.assertEqual(features, DEFAULT_FEATURES)
        self.assertTrue(features["welcome"])
        self.assertTrue(features["ad_detection"])
        self.assertTrue(features["ad_notify_admins"])

    def test_set_group_feature_updates_only_requested_feature(self):
        groups = {"-100": {"title": "test"}}
        set_group_feature(groups, -100, "welcome", False)
        self.assertFalse(groups["-100"]["features"]["welcome"])
        self.assertTrue(groups["-100"]["features"]["ad_detection"])

    def test_invalid_stored_values_use_defaults(self):
        features = get_group_features(
            {"features": {"welcome": False, "ad_detection": "no", "custom": True}}
        )
        self.assertFalse(features["welcome"])
        self.assertTrue(features["ad_detection"])
        self.assertNotIn("custom", features)

    def test_new_feature_defaults_on_for_old_groups(self):
        features = get_group_features({"features": {"ad_detection": False}})
        self.assertFalse(features["ad_detection"])
        self.assertTrue(features["ad_delete"])
        self.assertTrue(features["ad_mute"])


if __name__ == "__main__":
    unittest.main()
