import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import aiohttp

from llm_api import ServerConnectionError, ensure_server_reachable
from main import main
from test_simulation import Response


class ConnectionStartGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_transport_failure_stops_before_recording_or_taking_a_turn(self):
        for failure in (aiohttp.ClientConnectionError("offline"), TimeoutError()):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as directory, \
                    patch.object(aiohttp.ClientSession, "head", side_effect=failure), \
                    patch.object(aiohttp.ClientSession, "post") as generation, \
                    patch("main.ModelIdentity.capture") as identity, \
                    patch("main.Simulation.step") as step:
                snapshot, decision = Mock(), Mock()
                with self.assertRaisesRegex(ServerConnectionError, "^接続できません$"):
                    await main(params={"output_dir": directory}, on_snapshot=snapshot, on_decision=decision)
                self.assertEqual(list(Path(directory).iterdir()), [])
                for callback in (identity, step, generation, snapshot, decision):
                    callback.assert_not_called()

    async def test_head_reaches_the_configured_endpoint_without_generation(self):
        # HEAD need not be implemented by an otherwise working chat API.
        for status in (200, 401, 404, 405, 501):
            with self.subTest(status=status):
                session = Mock()
                session.head.return_value = Response(status, "")
                await ensure_server_reachable(session, base_url="https://example.invalid/v1/", timeout=120)
                args, kwargs = session.head.call_args
                self.assertEqual(args, ("https://example.invalid/v1/chat/completions",))
                self.assertEqual(kwargs["timeout"].total, 5)
                self.assertFalse(kwargs["allow_redirects"])
                session.post.assert_not_called()
                session.get.assert_not_called()

    async def test_preflight_respects_a_shorter_configured_timeout(self):
        session = Mock()
        session.head.return_value = Response(405, "")
        await ensure_server_reachable(session, base_url="http://localhost:8080/v1", timeout=1)
        self.assertEqual(session.head.call_args.kwargs["timeout"].total, 1)

    async def test_mock_run_needs_no_connection(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(aiohttp.ClientSession, "head") as head:
            result = await main(params={"output_dir": directory, "mock_mode": True, "num_steps": 1})
            self.assertEqual(result["status"], "completed")
            head.assert_not_called()

    async def test_start_can_be_cancelled_while_checking_connection(self):
        waiting = asyncio.Event()

        async def wait_for_server(*args, **kwargs):
            waiting.set()
            await asyncio.Event().wait()

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(aiohttp.ClientSession, "_request", side_effect=wait_for_server):
            task = asyncio.create_task(main(params={"output_dir": directory}))
            await asyncio.wait_for(waiting.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
