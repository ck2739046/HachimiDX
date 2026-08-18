import unittest

from src.services.model_inference_manage import ModelInferenceManage, evaluate_model_half


class TestModelInferencePolicy(unittest.TestCase):

    def test_status_matrix(self):
        cases = {
            (None, False): "not_converted",
            (None, True): "not_converted",
            (False, False): "compatible",
            (False, True): "upgrade_available",
            (True, True): "compatible",
            (True, False): "incompatible",
        }
        for (model_half, device_half), expected in cases.items():
            with self.subTest(model_half=model_half, device_half=device_half):
                result = evaluate_model_half(model_half, device_half)
                self.assertEqual(result.status, expected)

    def test_usable_statuses(self):
        self.assertFalse(evaluate_model_half(None, True).is_usable)
        self.assertTrue(evaluate_model_half(False, True).is_usable)
        self.assertTrue(evaluate_model_half(False, True).can_upgrade_to_half)
        self.assertFalse(evaluate_model_half(True, False).is_usable)

    def test_model_backend_rules_are_managed_by_model_inference_manage(self):
        self.assertEqual(ModelInferenceManage.get_model_group("ONNX Cuda"), "onnx")
        self.assertEqual(ModelInferenceManage.get_model_backend_id("TensorRT"), "tensorrt")


if __name__ == "__main__":
    unittest.main(verbosity=2)