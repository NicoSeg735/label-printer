import unittest

from label_designer import render_labels
from printer import encode_image_to_dothan_bin, has_durable_print_confirmation


class DothanProtocolTests(unittest.TestCase):
    def test_documented_profile_starts_with_initialization_and_ends_with_feed(self):
        image = render_labels("A", font_size=15)[0]
        packet = encode_image_to_dothan_bin(image, profile="dothan-v11").data
        self.assertTrue(packet.startswith(b"\x1b\x40\x1f\x20"))
        self.assertEqual(packet[-1], 0x0C)
        self.assertIn(b"\x1f\x27\x01\x28\x88", packet)

    def test_print_confirmation_requires_two_equal_changed_readings(self):
        before = {"lifetime_labels": 1, "lifetime_lines": 2, "lifetime_steps": 3}
        after = {"lifetime_labels": 2, "lifetime_lines": 4, "lifetime_steps": 6}
        self.assertTrue(has_durable_print_confirmation(before, after, after))
        self.assertFalse(has_durable_print_confirmation(before, after, before))


if __name__ == "__main__":
    unittest.main()
