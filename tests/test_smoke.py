"""Fast smoke tests for CleanConnect. Run: python -m unittest discover -s tests"""
import unittest
from io import BytesIO
from PIL import Image

from models.waste_classifier import extract_features, WASTE_CLASSES
import app as cleanconnect


class FeaturePipelineTests(unittest.TestCase):
    def test_feature_vector_is_finite_and_stable_shape(self):
        image = Image.new("RGB", (120, 80), color=(40, 160, 80))
        first = extract_features(image)
        second = extract_features(image)
        self.assertEqual(first.shape, second.shape)
        self.assertTrue((first == second).all())
        self.assertTrue(__import__("numpy").isfinite(first).all())

    def test_expected_waste_classes_exist(self):
        self.assertEqual(len(WASTE_CLASSES), 6)
        self.assertIn("Mixed Waste", WASTE_CLASSES)


class ApplicationSmokeTests(unittest.TestCase):
    def setUp(self):
        cleanconnect.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = cleanconnect.app.test_client()

    def test_home_page_returns_success(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_health_endpoint_is_structured(self):
        response = self.client.get("/api/health")
        self.assertIn(response.status_code, (200, 503))
        data = response.get_json()
        self.assertIn(data["database"], ("ready", "error"))
        self.assertIn(data["ml_model"], ("ready", "not_trained", "load_error"))

    def test_admin_ml_insights_requires_authentication(self):
        response = self.client.get("/admin/ml-insights")
        self.assertIn(response.status_code, (302, 401))


if __name__ == "__main__":
    unittest.main()
