import queue
import unittest

from app import clean_live_text, clean_username, emit_event, prepare_comment_for_speech


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

    def test_keeps_a_single_emoji_for_speech(self):
        self.assertEqual(prepare_comment_for_speech("Me gusta 😂"), "Me gusta 😂")

    def test_removes_multiple_emojis_but_keeps_words(self):
        self.assertEqual(
            prepare_comment_for_speech("Hola 😂😂, buen directo ❤️"),
            "Hola, buen directo",
        )

    def test_treats_flag_and_family_as_single_emojis(self):
        self.assertEqual(prepare_comment_for_speech("España 🇪🇸"), "España 🇪🇸")
        self.assertEqual(prepare_comment_for_speech("Familia 👨‍👩‍👧‍👦"), "Familia 👨‍👩‍👧‍👦")
        self.assertEqual(
            prepare_comment_for_speech("Saludos 🇪🇸 👨‍👩‍👧‍👦"),
            "Saludos",
        )

    def test_only_multiple_emojis_produces_no_speech(self):
        self.assertEqual(prepare_comment_for_speech("🔥🔥🔥"), "")


if __name__ == "__main__":
    unittest.main()
