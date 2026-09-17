import unittest

from label_designer import MAX_PRINT_WIDTH_DOTS, mm_to_dots, render_labels


class LabelDesignerTests(unittest.TestCase):
    def test_default_label_matches_40_by_30_mm_media(self):
        image = render_labels("Prueba")[0]
        self.assertEqual(image.size, (mm_to_dots(40), mm_to_dots(30)))

    def test_label_cannot_exceed_print_head_width(self):
        too_wide_mm = (MAX_PRINT_WIDTH_DOTS + 1) / (203 / 25.4)
        with self.assertRaises(ValueError):
            render_labels("Prueba", width_mm=too_wide_mm, height_mm=30)

    def test_label_dimensions_must_be_positive(self):
        with self.assertRaises(ValueError):
            render_labels("Prueba", width_mm=40, height_mm=0)


if __name__ == "__main__":
    unittest.main()
