"""sounddeviceとVoskをバックグラウンドで動かして命令を配信する。"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel

from backend.commands import (
    RECOGNITION_FORMS,
    canonical_commands,
    custom_recognition_forms,
)

LOGGER = logging.getLogger(__name__)
UNKNOWN_TOKEN = "[unk]"


def _parse_result(raw_result: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_result)
    except json.JSONDecodeError:
        return {"text": "", "result": []}
    return parsed if isinstance(parsed, dict) else {"text": "", "result": []}


def _average_confidence(result: Mapping[str, Any]) -> float | None:
    words = result.get("result")
    if not isinstance(words, list):
        return None
    confidences = [
        float(word["conf"])
        for word in words
        if isinstance(word, dict) and isinstance(word.get("conf"), (int, float))
    ]
    return sum(confidences) / len(confidences) if confidences else None


class VoiceRecognitionService:
    """最初の接続時にマイクを開始し、全WebSocketへ同じ結果を送る。"""

    def __init__(
        self,
        *,
        model_path: Path | None = None,
        device: int | str | None = None,
    ) -> None:
        self.model_path = model_path
        self.device = device
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = asyncio.Lock()
        self._configuration_lock = threading.Lock()
        self._recognition_forms = dict(RECOGNITION_FORMS)
        self._configuration_version = 0

    def configure_commands(self, assignments: Mapping[str, str] | None) -> None:
        """通常の5語、または画面で登録された5語へ認識候補を切り替える。"""
        recognition_forms = (
            dict(RECOGNITION_FORMS)
            if assignments is None
            else custom_recognition_forms(assignments)
        )
        with self._configuration_lock:
            if recognition_forms == self._recognition_forms:
                return
            self._recognition_forms = recognition_forms
            self._configuration_version += 1

    def _configuration(self) -> tuple[dict[str, str], int]:
        with self._configuration_lock:
            return (
                self._recognition_forms.copy(),
                self._configuration_version,
            )

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        subscriber: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=32)
        async with self._lock:
            self._subscribers.add(subscriber)
            if self._thread is None or not self._thread.is_alive():
                self._loop = asyncio.get_running_loop()
                self._stop_event.clear()
                self._thread = threading.Thread(
                    target=self._recognition_worker,
                    name="vosk-microphone",
                    daemon=True,
                )
                self._thread.start()
            else:
                subscriber.put_nowait(
                    {
                        "type": "status",
                        "microphone": "connected",
                        "message": "音声認識を共有しています",
                    }
                )
        return subscriber

    async def unsubscribe(
        self,
        subscriber: asyncio.Queue[dict[str, Any]],
    ) -> None:
        thread_to_join: threading.Thread | None = None
        async with self._lock:
            self._subscribers.discard(subscriber)
            if not self._subscribers and self._thread is not None:
                self._stop_event.set()
                thread_to_join = self._thread
                self._thread = None
        if thread_to_join is not None:
            await asyncio.to_thread(thread_to_join.join, 2.0)

    def _publish(self, event: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._broadcast, event)

    def _broadcast(self, event: dict[str, Any]) -> None:
        for subscriber in tuple(self._subscribers):
            if subscriber.full():
                try:
                    subscriber.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            subscriber.put_nowait(event)

    def _load_model(self) -> Model:
        if self.model_path is not None:
            LOGGER.info("Voskモデルを読み込みます: %s", self.model_path)
            return Model(str(self.model_path))
        LOGGER.info("Vosk日本語小型モデルを読み込みます")
        return Model(lang="ja")

    def _recognition_worker(self) -> None:
        audio_queue: queue.Queue[tuple[bytes, str | None]] = queue.Queue()
        self._publish(
            {
                "type": "status",
                "microphone": "connecting",
                "message": "Voskモデルとマイクを準備しています",
            }
        )

        try:
            SetLogLevel(-1)
            device_info = sd.query_devices(self.device, "input")
            sample_rate = int(device_info["default_samplerate"])
            block_size = max(1, round(sample_rate * 0.1))
            model = self._load_model()
            recognition_forms, configuration_version = self._configuration()
            grammar = json.dumps([*recognition_forms, UNKNOWN_TOKEN], ensure_ascii=False)
            recognizer = KaldiRecognizer(model, sample_rate, grammar)
            recognizer.SetWords(True)
            dispatched_commands: list[str] = []

            def publish_new_commands(
                commands: list[str],
                raw_text: str,
                *,
                partial: bool,
            ) -> None:
                nonlocal dispatched_commands
                common_prefix = 0
                for already_sent, recognized in zip(
                    dispatched_commands,
                    commands,
                    strict=False,
                ):
                    if already_sent != recognized:
                        break
                    common_prefix += 1

                for command in commands[common_prefix:]:
                    event: dict[str, Any] = {
                        "type": "command",
                        "command": command,
                        "raw": raw_text,
                        "partial": partial,
                    }
                    self._publish(event)
                    LOGGER.info(
                        "音声命令%s: command=%s raw=%r",
                        "（途中認識）" if partial else "",
                        command,
                        raw_text,
                    )
                if commands:
                    dispatched_commands = commands.copy()

            def audio_callback(
                indata: bytes,
                _frames: int,
                _time_info: Any,
                status: sd.CallbackFlags,
            ) -> None:
                audio_queue.put(
                    (bytes(indata), str(status) if status else None)
                )

            with sd.RawInputStream(
                samplerate=sample_rate,
                blocksize=block_size,
                device=self.device,
                dtype="int16",
                channels=1,
                callback=audio_callback,
            ):
                self._publish(
                    {
                        "type": "status",
                        "microphone": "connected",
                        "message": f"{device_info['name']} で認識中",
                    }
                )
                LOGGER.info(
                    "音声認識を開始しました: device=%s sample_rate=%d",
                    device_info["name"],
                    sample_rate,
                )

                while not self._stop_event.is_set():
                    latest_forms, latest_version = self._configuration()
                    if latest_version != configuration_version:
                        recognition_forms = latest_forms
                        configuration_version = latest_version
                        grammar = json.dumps(
                            [*recognition_forms, UNKNOWN_TOKEN],
                            ensure_ascii=False,
                        )
                        recognizer = KaldiRecognizer(model, sample_rate, grammar)
                        recognizer.SetWords(True)
                        dispatched_commands = []
                        LOGGER.info(
                            "音声認識候補を切り替えました: words=%s",
                            list(recognition_forms),
                        )

                    try:
                        pcm, audio_error = audio_queue.get(timeout=0.25)
                    except queue.Empty:
                        continue
                    if audio_error:
                        LOGGER.warning("マイク入力エラー: %s", audio_error)

                    if not recognizer.AcceptWaveform(pcm):
                        partial_result = _parse_result(
                            recognizer.PartialResult()
                        )
                        partial_text = str(
                            partial_result.get("partial", "")
                        ).strip()
                        partial_commands = canonical_commands(
                            partial_text,
                            recognition_forms,
                        )
                        if partial_commands:
                            publish_new_commands(
                                partial_commands,
                                partial_text,
                                partial=True,
                            )
                        continue

                    result = _parse_result(recognizer.Result())
                    raw_text = str(result.get("text", "")).strip()
                    commands = canonical_commands(raw_text, recognition_forms)
                    if not commands:
                        if raw_text:
                            LOGGER.info("命令以外の音声: %r", raw_text)
                        dispatched_commands = []
                        continue

                    confidence = _average_confidence(result)
                    publish_new_commands(
                        commands,
                        raw_text,
                        partial=False,
                    )
                    LOGGER.info(
                        "音声認識確定: commands=%s raw=%r confidence=%s",
                        commands,
                        raw_text,
                        confidence,
                    )
                    dispatched_commands = []
        except Exception as error:
            LOGGER.exception("音声認識を開始できませんでした")
            self._publish(
                {
                    "type": "status",
                    "microphone": "error",
                    "message": f"{type(error).__name__}: {error}",
                }
            )
        finally:
            self._publish(
                {
                    "type": "status",
                    "microphone": "disconnected",
                    "message": "音声認識を停止しました",
                }
            )
