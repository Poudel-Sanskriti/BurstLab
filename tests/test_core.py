import unittest
from io import BytesIO
from PIL import Image
from backend.worker.core import render_qr
from backend.models import RunConfig


class QRTests(unittest.TestCase):
    def test_real_deterministic_png(self):
        first = render_qr("https://example.com/a")
        self.assertEqual(first, render_qr("https://example.com/a"))
        self.assertNotEqual(first.checksum, render_qr("https://example.com/b").checksum)
        image = Image.open(BytesIO(first.content))
        self.assertEqual(image.format, "PNG")
        self.assertEqual(image.width, image.height)

    def test_payload_limits(self):
        for payload in ("", " ", "a" * 513, "🙂" * 129):
            with self.assertRaises(ValueError):
                render_qr(payload)

    def test_run_bounds(self):
        for config in ({"count": 101}, {"delay_ms": 1001}, {"rate": 0}, {"unknown": 1}):
            with self.assertRaises(ValueError):
                RunConfig(**config)


if __name__ == "__main__":
    unittest.main()
