"""One session's cancellable experiment, without Streamlit calls in its worker."""

import asyncio
from collections import deque
from copy import deepcopy
import threading

from agent_view import attack_victims, format_live_decision
from llm_api import ServerConnectionError
from translations import TranslationBusyError, has_untranslated, translate_result


class ExperimentTask:
    def __init__(self, run_simulation, params):
        self.params = deepcopy(params)
        self._run_simulation = run_simulation
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.done = threading.Event()
        self._loop = self._task = None
        self._snapshot = None
        self._recent = deque(maxlen=10)
        self._decision_progress = None
        self._result = self._error = self._notice = None
        self._translation_progress = None
        self._thread = threading.Thread(target=self._run, name="sugarscape-experiment", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        with self._lock:
            if self._stop.is_set() or self.done.is_set():
                return
            self._stop.set()
            if self._loop is not None:
                try:
                    self._loop.call_soon_threadsafe(self._task.cancel)
                except RuntimeError:
                    # asyncio.run may have closed its loop just before _run's
                    # finally block; its completed result is already retained.
                    pass

    def state(self):
        with self._lock:
            return {"snapshot": self._snapshot, "recent": tuple(text for _, _, text in self._recent),
                    "decision_progress": self._decision_progress,
                    "result": self._result, "error": self._error, "notice": self._notice,
                    "translation_progress": self._translation_progress,
                    "stopping": self._stop.is_set(), "done": self.done.is_set()}

    def _on_snapshot(self, snapshot):
        agents = {agent["id"]: agent for agent in snapshot["agents"]}
        events = snapshot.get("events", [])
        victims = attack_victims(events)
        completed = {event["agent_id"]: f"Step {snapshot['step']} · " +
                     format_live_decision(event, agents[event["agent_id"]], victims)
                     for event in events if event["agent_id"] in agents}
        with self._lock:
            # Keep received prose in chronological order. Once actions settle,
            # update only this turn's retained entries with the final faces.
            self._snapshot = snapshot
            if any(step == snapshot["step"] for step, _, _ in self._recent):
                self._recent = deque((
                    (step, agent_id, completed.get(agent_id, text) if step == snapshot["step"] else text)
                    for step, agent_id, text in self._recent), maxlen=10)
            else:
                self._recent.extend((snapshot["step"], agent_id, text) for agent_id, text in completed.items())
            self._decision_progress = None

    def _on_decision(self, step, event):
        with self._lock:
            agents = self._snapshot["agents"] if self._snapshot else []
            agent = next((item for item in agents if item["id"] == event["agent_id"]), {"id": event["agent_id"]})
            self._recent.append((step, event["agent_id"], f"Step {step} · " +
                                 format_live_decision(event, agent)))
            received = (self._decision_progress[1] if self._decision_progress
                        and self._decision_progress[0] == step else 0)
            self._decision_progress = (step, received + 1, sum(agent["alive"] for agent in agents))

    def _on_translation(self, done, total):
        with self._lock:
            self._translation_progress = (done, total)

    async def _execute(self):
        with self._lock:
            self._loop, self._task = asyncio.get_running_loop(), asyncio.current_task()
            if self._stop.is_set():
                raise asyncio.CancelledError
        result = await self._run_simulation(
            params=self.params, on_decision=self._on_decision, on_snapshot=self._on_snapshot,
            stop_requested=self._stop.is_set)
        with self._lock:
            self._result = result
        if self._stop.is_set() or result["status"] not in ("completed", "completed_with_errors") or self.params["mock_mode"]:
            return
        self._on_translation(0, 0)
        try:
            cache = await translate_result(result, self.params, on_progress=self._on_translation)
            if has_untranslated(result, cache):
                self._notice = "一部を翻訳できませんでした。その箇所は原文で表示します。"
        except TranslationBusyError:
            self._notice = "別のウィンドウでこの実験を翻訳しています。完了後に表示を更新すると訳文を読めます。"
        except (OSError, ValueError):
            self._notice = "日本語訳を保存できませんでした。実験の記録は保存済みです。"

    def _run(self):
        try:
            asyncio.run(self._execute())
        except asyncio.CancelledError:
            self._notice = ("日本語への翻訳を停止しました。実験の記録と保存済みの訳文は残っています。"
                            if self._result else "開始準備を停止しました。")
        except ValueError:
            self._error = "設定に誤りがあります。URL・モデル・個体数・体力の設定を確認してください。"
        except ServerConnectionError:
            self._error = "接続できません"
        except Exception as error:
            if self._result is not None:
                self._notice = "日本語への翻訳を完了できませんでした。実験の記録は保存済みです。"
            else:
                self._error = f"実験を開始できませんでした（{type(error).__name__}）。保存先と接続設定を確認してください。"
        finally:
            with self._lock:
                self._loop = self._task = None
                self.params.pop("api_key", None)
                self.done.set()
