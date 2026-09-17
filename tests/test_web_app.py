import io
import unittest

from PIL import Image

import web_app


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.client = web_app.app.test_client()
        web_app.preview_jobs.clear()
        web_app.source_images.clear()

    def test_text_preview_returns_a_printable_page(self):
        response = self.client.post(
            "/api/preview/text",
            json={"text": "6 x 100 crol", "width_mm": 40, "height_mm": 30, "media": "labels"},
        )
        self.assertEqual(response.status_code, 200)
        preview = response.get_json()
        self.assertEqual(preview["pages"], 1)
        image_response = self.client.get(f"/api/previews/{preview['preview_id']}/1")
        self.assertEqual(image_response.status_code, 200)
        self.assertEqual(image_response.mimetype, "image/png")

    def test_uploaded_photo_can_be_converted_to_a_thermal_preview(self):
        original = Image.new("RGB", (100, 80), "navy")
        content = io.BytesIO()
        original.save(content, "PNG")
        content.seek(0)
        uploaded = self.client.post(
            "/api/images/upload",
            data={"image": (content, "entrenamiento.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(uploaded.status_code, 200)
        image_id = uploaded.get_json()["image_id"]
        preview = self.client.post(
            "/api/preview/image",
            json={
                "image_id": image_id,
                "width_mm": 40,
                "height_mm": 30,
                "media": "labels",
                "fit": "cover",
                "effect": "dither",
                "contrast": 1.2,
            },
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.get_json()["pages"], 1)

