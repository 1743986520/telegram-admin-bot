import os
import unittest

from web_verification import WebVerificationServer, _captcha_image, is_configured


class WebVerificationTests(unittest.TestCase):
    def test_captcha_image_is_png(self):
        self.assertTrue(_captcha_image("123456").startswith(b"\x89PNG"))

    def test_session_url_contains_opaque_token(self):
        old = {name: os.environ.get(name) for name in (
            "WEB_VERIFY_BASE_URL", "CF_TURNSTILE_SITE_KEY", "CF_TURNSTILE_SECRET_KEY", "TELEGRAM_BOT_USERNAME"
        )}
        try:
            os.environ["WEB_VERIFY_BASE_URL"] = "https://example.test"
            os.environ["CF_TURNSTILE_SITE_KEY"] = "site"
            os.environ["CF_TURNSTILE_SECRET_KEY"] = "secret"
            os.environ["TELEGRAM_BOT_USERNAME"] = "example_bot"
            server = WebVerificationServer(None, None)
            token = server.create_session(123, -100)
            self.assertIn("https://t.me/example_bot?startapp=", server.url(token))
            self.assertGreaterEqual(len(token), 32)
            self.assertEqual(server.sessions[token]["user_id"], 123)
        finally:
            for name, value in old.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_configuration_requires_all_secrets(self):
        old = {name: os.environ.get(name) for name in (
            "WEB_VERIFY_BASE_URL", "CF_TURNSTILE_SITE_KEY", "CF_TURNSTILE_SECRET_KEY"
        )}
        try:
            for name in old:
                os.environ.pop(name, None)
            self.assertFalse(is_configured())
        finally:
            for name, value in old.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
