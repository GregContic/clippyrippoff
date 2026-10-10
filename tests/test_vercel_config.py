import json
import unittest
from pathlib import Path


class TestVercelRouting(unittest.TestCase):
    def test_backend_rewrites_precede_spa_fallback(self):
        config_path = Path(__file__).parents[1] / "frontend" / "vercel.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        rewrites = config["rewrites"]

        self.assertEqual(rewrites[0], {
            "source": "/api/:path*",
            "destination": "https://clippyrippoff.onrender.com/api/:path*",
        })
        self.assertEqual(rewrites[1], {
            "source": "/media/:path*",
            "destination": "https://clippyrippoff.onrender.com/media/:path*",
        })
        self.assertEqual(rewrites[-1], {
            "source": "/(.*)",
            "destination": "/index.html",
        })

    def test_rewrites_do_not_depend_on_vercel_env_interpolation(self):
        config_path = Path(__file__).parents[1] / "frontend" / "vercel.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        destinations = [rewrite["destination"] for rewrite in config["rewrites"][:2]]

        self.assertTrue(all(destination.startswith("https://") for destination in destinations))
        self.assertTrue(all("$" not in destination for destination in destinations))
