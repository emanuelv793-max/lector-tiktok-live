import queue
import unittest

from app import clean_live_text, clean_username, emit_event


class InputSecurityTests(unittest.TestCase):
    def test_accepts_username_and_tiktok_url(self):
        self.assertEqual(clean_username("@emanuelv793"), "emanuelv793")
        self.assertEqual(
            clean_username("https://www.tiktok.com/@emanuelv793/live"),
            "emanuelv793",
        )

    def test_rejects_malformed_or_oversized_username(self):
        self.assertEqual(clean_username("../../programa.exe"), "")
        self.assertEqual(clean_username("nombre con espacios"), "")
        self.assertEqual(clean_username("a" * 25), "")

    def test_sanitizes_untrusted_live_text(self):
        text = clean_live_text("hola\u202eexe\n\t mundo", 20)
        self.assertNotIn("\u202e", text)
        self.assertNotIn("\n", text)
        self.assertEqual(text, "hola exe mundo")

    def test_limits_comment_length(self):
        self.assertEqual(len(clean_live_text("x" * 1000, 450)), 450)

    def test_event_flood_does_not_block(self):
        events = queue.Queue(maxsize=1)
        self.assertTrue(emit_event(events, "notice", "primero"))
        self.assertFalse(emit_event(events, "notice", "segundo"))


if __name__ == "__main__":
    unittest.main()
