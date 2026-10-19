"""Reading translations must not alter the experiment or repeat completed requests."""

from copy import deepcopy
import fcntl
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_simulation import Response, reply
from translations import (FILENAME, LOCK_FILENAME, TranslationBusyError, has_untranslated, load_translations, translate_result,
                          translated_fields)


class TranslationSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return next(self.responses)


def response(fields, finish="stop"):
    return Response(200, json.dumps({"model": "translation-model", "choices": [
        {"message": {"content": json.dumps(fields, ensure_ascii=False)}, "finish_reason": finish}]}))


class TranslationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.result = {"run_id": "test-run", "output_dir": str(self.root), "config": {"mock_mode": False},
                       "logs": [{"step": 1, "events": [{"agent_id": 0, "message": "Hello", "thought": "I am worried"}]}]}
        self.connection = {"base_url": "http://localhost:1234/v1", "model": "alias", "api_key": "private-key"}

    async def test_recovered_parse_error_prose_is_translated_without_rewriting_execution(self):
        event = self.result["logs"][0]["events"][0]
        event.update(agent_id=2, decision_source="fallback", error_kind="parse_error", message="", thought="",
                     summary="", memory="", executed_action="Stay", message_status="not_requested",
                     raw_response=reply("x+1, y-1", message="Moving east.", thoughts="I see food.",
                                        summary="Food is nearby.", memory="Look east."))
        original = deepcopy(self.result)
        japanese = {"message": "東へ向かいます。", "thought": "食べ物が見える。", "summary": "近くに食べ物がある。", "memory": "東を見る。"}
        session = TranslationSession([response(japanese)])
        with patch("translations.aiohttp.ClientSession", return_value=session):
            cache = await translate_result(self.result, self.connection)
        self.assertEqual(self.result, original)
        self.assertEqual(len(session.requests), 1)
        self.assertEqual(json.loads(session.requests[0][1]["json"]["messages"][1]["content"]),
                         {"message": "Moving east.", "thought": "I see food.", "summary": "Food is nearby.", "memory": "Look east."})
        self.assertEqual(translated_fields(cache, 1, event), (japanese, True))


    async def test_success_is_saved_and_reused_without_changing_original(self):
        original = deepcopy(self.result)
        (self.root / "run.json").write_text(json.dumps(self.result))
        before = (self.root / "run.json").read_bytes()
        session = TranslationSession([response({"message": "こんにちは", "thought": "不安だ"})])
        with patch("translations.aiohttp.ClientSession", return_value=session):
            cache = await translate_result(self.result, self.connection)
        self.assertFalse(has_untranslated(self.result, cache))
        self.assertEqual(self.result, original)
        self.assertEqual((self.root / "run.json").read_bytes(), before)
        self.assertNotIn("private-key", (self.root / FILENAME).read_text())
        url, request = session.requests[0]
        self.assertEqual(url, "http://localhost:1234/v1/chat/completions")
        self.assertEqual(request["json"]["model"], "alias")
        self.assertEqual(request["json"]["temperature"], 0)
        self.assertEqual(request["headers"]["Authorization"], "Bearer private-key")
        fields, translated = translated_fields(load_translations(self.result), 1, self.result["logs"][0]["events"][0])
        self.assertTrue(translated)
        self.assertEqual(fields["thought"], "不安だ")
        with patch("translations.aiohttp.ClientSession", side_effect=AssertionError("No repeated call")):
            await translate_result(self.result, self.connection)

    async def test_partial_failure_keeps_success_and_only_retries_missing_translation(self):
        self.result["logs"][0]["events"].append({"agent_id": 1, "message": "Help", "thought": "Hungry"})
        session = TranslationSession([response({"message": "こんにちは", "thought": "不安だ"}), Response(503, "busy")])
        with patch("translations.aiohttp.ClientSession", return_value=session):
            cache = await translate_result(self.result, self.connection)
        self.assertEqual(cache["status"], "partial")
        second = self.result["logs"][0]["events"][1]
        self.assertEqual(translated_fields(cache, 1, second), ({"message": "Help", "thought": "Hungry"}, False))
        session = TranslationSession([response({"message": "助けて", "thought": "おなかがすいた"})])
        self.connection["model"] = "different-alias"
        with patch("translations.aiohttp.ClientSession", return_value=session):
            cache = await translate_result(self.result, self.connection)
        self.assertEqual(len(session.requests), 1)
        self.assertEqual(cache["status"], "completed")
        self.assertEqual(cache["entries"]["1:0"]["connection"]["requested_model"], "alias")
        self.assertEqual(cache["entries"]["1:1"]["connection"]["requested_model"], "different-alias")

    async def test_translation_uses_selected_request_controls(self):
        for protocol in ("openai", "chat_template"):
            with self.subTest(protocol=protocol), tempfile.TemporaryDirectory() as directory:
                result = {**self.result, "output_dir": directory}
                options = {"send_temperature": False, "send_top_p": False, "reasoning_mode": "on",
                           "reasoning_format": protocol, "reasoning_effort": "low",
                           "max_tokens_parameter": "max_completion_tokens"}
                session = TranslationSession([response({"message": "こんにちは", "thought": "不安だ"})])
                with patch("translations.aiohttp.ClientSession", return_value=session):
                    cache = await translate_result(result, {**self.connection, **options})
                self.assertEqual(cache["status"], "completed")
                payload = session.requests[0][1]["json"]
                for name in ("temperature", "top_p", "max_tokens"):
                    self.assertNotIn(name, payload)
                self.assertEqual(payload["max_completion_tokens"], 8192)
                if protocol == "openai":
                    self.assertEqual(payload["reasoning_effort"], "low")
                    self.assertNotIn("chat_template_kwargs", payload)
                else:
                    self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": True, "reasoning_effort": "low"})
                    self.assertNotIn("reasoning_effort", payload)
                self.assertEqual({key: cache["last_connection"][key] for key in options}, options)

    async def test_another_window_cannot_duplicate_translation_or_overwrite_cache(self):
        with (self.root / LOCK_FILENAME).open("a") as other_window:
            fcntl.flock(other_window.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch("translations.aiohttp.ClientSession", side_effect=AssertionError("No duplicate request")):
                with self.assertRaises(TranslationBusyError):
                    await translate_result(self.result, self.connection)
            self.assertFalse((self.root / FILENAME).exists())
        # The lock file may remain after closing; the OS lock has been released.
        with patch("translations.aiohttp.ClientSession", return_value=TranslationSession([
                response({"message": "こんにちは", "thought": "不安"})])):
            self.assertEqual((await translate_result(self.result, self.connection))["status"], "completed")

    async def test_invalid_or_truncated_translation_falls_back_to_original(self):
        for reply in (response({"message": "こんにちは"}), response({"message": "", "thought": "不安"}),
                      response({"message": "こんにちは", "thought": "不安"}, finish="length")):
            with patch("translations.aiohttp.ClientSession", return_value=TranslationSession([reply])):
                cache = await translate_result(self.result, self.connection)
            self.assertEqual(cache["status"], "partial")
            self.assertFalse(translated_fields(cache, 1, self.result["logs"][0]["events"][0])[1])

    async def test_source_changes_and_foreign_run_cannot_reuse_old_translation(self):
        with patch("translations.aiohttp.ClientSession", return_value=TranslationSession([
                response({"message": "こんにちは", "thought": "不安"})])):
            cache = await translate_result(self.result, self.connection)
        changed = {**self.result["logs"][0]["events"][0], "message": "Different"}
        self.assertFalse(translated_fields(cache, 1, changed)[1])
        self.result["run_id"] = "different-run"
        self.assertEqual(load_translations(self.result)["entries"], {})

    async def test_mock_and_sample_are_always_offline(self):
        with patch("translations.aiohttp.ClientSession", side_effect=AssertionError("No network")):
            self.result["config"]["mock_mode"] = True
            await translate_result(self.result, self.connection)
            self.result["config"]["mock_mode"] = False
            self.result["demo_notice"] = "Sample"
            await translate_result(self.result, self.connection)
        self.assertFalse((self.root / FILENAME).exists())


if __name__ == "__main__":
    unittest.main()
