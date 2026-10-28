"""Regression checks for push delivery and the test runner, without network or DB."""
import base64
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid
from app import push
from app.logic.push_targets import PushSession
from app.models import PushSubscription
import brain


class ProjectSafetyTests(unittest.TestCase):
    def test_llm_tool_request_and_response_without_provider(self):
        output = SimpleNamespace(type="function_call", name="extract_intent", arguments=json.dumps(
            {"intent": "create", "items": [{"type": "task", "text": "Check", "time": "09:00"}],
             "confidence": 0.9, "layer": "llm"}))
        response = SimpleNamespace(output=[output], output_text="")
        with patch.dict(os.environ, {"YANDEX_API_KEY": "fake", "YANDEX_FOLDER_ID": "fake"}), \
                patch.object(brain.client.responses, "create", return_value=response) as create:
            result = brain.parse_user_input("Check 09:00")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.intent, "create")
        self.assertEqual(result.items[0].time, "09:00")
        # С 27.10 без tools: YandexGPT отвечает JSON текстом по русскому промпту с календарём
        self.assertNotIn("tools", create.call_args.kwargs)
        self.assertIn("Календарь", create.call_args.kwargs["instructions"])
        self.assertFalse(create.call_args.kwargs["store"])

    def test_push_marks_only_successful_responses_as_delivered(self):
        public = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip("=")
        sub = PushSubscription(endpoint="https://fcm.googleapis.com/fcm/send/test",
                               p256dh=encode(public), auth=encode(b"x" * 16))
        for status, expected in [(None, None), (201, True), (404, False), (410, False), (500, None)]:
            with self.subTest(status=status):
                answer = SimpleNamespace(status_code=status) if status is not None else None
                with patch("app.push.webpush", return_value=answer):
                    self.assertIs(push.send(sub, "{}", Vapid()), expected)

    def test_push_session_cannot_disable_transport_protection(self):
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
        with patch("socket.getaddrinfo", return_value=addresses), \
                patch("requests.Session.request") as request, PushSession() as session:
            session.request("POST", "https://fcm.googleapis.com/test", timeout=3,
                            verify=False, allow_redirects=True,
                            proxies={"https": "http://127.0.0.1:1234"})
            self.assertFalse(request.call_args.kwargs["allow_redirects"])
            self.assertTrue(request.call_args.kwargs["verify"])
            self.assertEqual(request.call_args.kwargs["proxies"], {})
            self.assertEqual(request.call_args.kwargs["timeout"], 3)

    def test_runner_fails_when_legacy_check_only_prints_failure(self):
        for output, expected in [(b"FAIL scenario\n", 1), (b"BAD scenario\n", 1),
                                 (b"fails: 2\n", 1), (b"fails: 0\n", 0)]:
            with self.subTest(output=output), TemporaryDirectory() as directory:
                result = subprocess.CompletedProcess([], 0, stdout=output, stderr=b"")
                with patch.dict(os.environ, {"AUDIT_OUT_DIR": directory}), \
                        patch.object(sys, "argv", ["audit_run_tests.py", "test_chat_safety.py"]), \
                        patch("subprocess.run", return_value=result), \
                        self.assertRaises(SystemExit) as exit_result:
                    runpy.run_path(str(ROOT / "audit_run_tests.py"), run_name="__main__")
                self.assertEqual(exit_result.exception.code, expected)
                rows = json.loads((Path(directory) / "backend-status.json").read_text(encoding="utf-8"))
                self.assertEqual(rows[0]["reported_failure"], bool(expected))


if __name__ == "__main__":
    unittest.main()
