"""スイカ割り用の5コマンドをマイクから継続認識して検証する。"""

from __future__ import annotations

import argparse
import json
import logging
import math
import queue
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel

from backend.commands import (
    COMMANDS,
    RECOGNITION_FORMS,
    canonical_commands,
)

UNKNOWN_TOKEN = "[unk]"
DBFS_FLOOR = -96.0


@dataclass
class SessionStats:
    started_at: float
    command_count: int = 0
    rejected_count: int = 0
    audio_error_count: int = 0
    last_command_at: float | None = None


def int_or_str(value: str) -> int | str:
    """デバイス番号ならint、デバイス名ならstrとして扱う。"""
    try:
        return int(value)
    except ValueError:
        return value


def dbfs(pcm: bytes) -> float:
    """16-bit mono PCMのRMSをdBFSへ変換する。"""
    samples = memoryview(pcm).cast("h")
    if not samples:
        return DBFS_FLOOR
    mean_square = sum(sample * sample for sample in samples) / len(samples)
    if mean_square == 0:
        return DBFS_FLOOR
    return max(DBFS_FLOOR, 20.0 * math.log10(math.sqrt(mean_square) / 32768.0))


def parse_vosk_result(raw_result: str) -> dict[str, Any]:
    try:
        result = json.loads(raw_result)
    except json.JSONDecodeError:
        return {"text": "", "result": []}
    return result if isinstance(result, dict) else {"text": "", "result": []}


def average_confidence(result: dict[str, Any]) -> float | None:
    words = result.get("result")
    if not isinstance(words, list):
        return None
    confidences = [
        float(word["conf"])
        for word in words
        if isinstance(word, dict) and isinstance(word.get("conf"), (int, float))
    ]
    return sum(confidences) / len(confidences) if confidences else None


def log_final_result(
    raw_result: str,
    stats: SessionStats,
    speech_started_at: float | None,
) -> None:
    result = parse_vosk_result(raw_result)
    text = str(result.get("text", "")).strip()
    commands = canonical_commands(text)
    now = time.monotonic()

    if commands:
        stats.command_count += len(commands)
        stats.last_command_at = now
        latency_ms = (
            (now - speech_started_at) * 1000.0
            if speech_started_at is not None
            else None
        )
        confidence = average_confidence(result)
        for command in commands:
            details = [f"command={command}", f"raw={text!r}"]
            if confidence is not None:
                details.append(f"confidence={confidence:.3f}")
            if latency_ms is not None:
                details.append(f"latency={latency_ms:.0f}ms")
            logging.info("[COMMAND] %s", " ".join(details))
        return

    if text or speech_started_at is not None:
        stats.rejected_count += 1
        logging.info("[REJECTED] raw=%r（ゲーム操作なし）", text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Voskでスイカ割り用音声コマンドを継続認識します。"
        ),
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="利用可能な音声デバイスを表示して終了する",
    )
    parser.add_argument(
        "--device",
        type=int_or_str,
        help=(
            "入力デバイスの番号、または名前の一部"
            "（省略時は既定のマイク）"
        ),
    )
    parser.add_argument(
        "--model",
        type=Path,
        help=(
            "展開済みVosk日本語モデルのパス"
            "（省略時は小型モデルを自動取得）"
        ),
    )
    parser.add_argument(
        "--status-interval",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="待機ログを出す間隔（既定: 5秒、0で無効）",
    )
    parser.add_argument(
        "--speech-threshold",
        type=float,
        default=-40.0,
        metavar="DBFS",
        help="発話開始とみなす音量（既定: -40 dBFS）",
    )
    parser.add_argument(
        "--show-vosk-logs",
        action="store_true",
        help="Vosk内部ログも表示する",
    )
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.status_interval < 0:
        parser.error("--status-interval は0以上にしてください")
    if not DBFS_FLOOR <= args.speech_threshold <= 0:
        parser.error(
            f"--speech-threshold は{DBFS_FLOOR}〜0の範囲にしてください"
        )
    if args.model is not None and not args.model.is_dir():
        parser.error(
            f"モデルのディレクトリが見つかりません: {args.model}"
        )


def load_model(model_path: Path | None) -> Model:
    if model_path is not None:
        logging.info("[SETUP] モデルを読み込みます: %s", model_path)
        return Model(str(model_path))
    logging.info(
        "[SETUP] 日本語小型モデルを読み込みます"
        "（初回のみ約48MBを ~/.cache/vosk へ取得します）"
    )
    return Model(lang="ja")


def run(args: argparse.Namespace) -> None:
    device_info = sd.query_devices(args.device, "input")
    sample_rate = int(device_info["default_samplerate"])
    block_size = max(1, round(sample_rate * 0.1))

    model = load_model(args.model)
    grammar = json.dumps([*RECOGNITION_FORMS, UNKNOWN_TOKEN], ensure_ascii=False)
    recognizer = KaldiRecognizer(model, sample_rate, grammar)
    recognizer.SetWords(True)

    audio_queue: queue.Queue[tuple[bytes, float, str | None]] = queue.Queue()

    def audio_callback(
        indata: bytes,
        _frames: int,
        _time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        audio_queue.put(
            (bytes(indata), time.monotonic(), str(status) if status else None)
        )

    stats = SessionStats(started_at=time.monotonic())
    last_loud_audio_at = stats.started_at
    speech_started_at: float | None = None
    last_partial = ""
    next_status_at = stats.started_at + args.status_interval
    peak_dbfs = DBFS_FLOOR

    logging.info(
        "[START] device=%s sample_rate=%dHz commands=%s",
        device_info["name"],
        sample_rate,
        ", ".join(COMMANDS),
    )
    logging.info(
        "[START] 話した後に少し黙ってください。終了は Ctrl+C です。"
    )

    try:
        with sd.RawInputStream(
            samplerate=sample_rate,
            blocksize=block_size,
            device=args.device,
            dtype="int16",
            channels=1,
            callback=audio_callback,
        ):
            while True:
                pcm, captured_at, audio_error = audio_queue.get()
                if audio_error is not None:
                    stats.audio_error_count += 1
                    logging.warning("[AUDIO ERROR] %s", audio_error)

                current_dbfs = dbfs(pcm)
                peak_dbfs = max(peak_dbfs, current_dbfs)
                if current_dbfs >= args.speech_threshold:
                    last_loud_audio_at = captured_at
                    if speech_started_at is None:
                        speech_started_at = captured_at

                if recognizer.AcceptWaveform(pcm):
                    log_final_result(
                        recognizer.Result(),
                        stats,
                        speech_started_at,
                    )
                    speech_started_at = None
                    last_partial = ""
                else:
                    partial = str(
                        parse_vosk_result(recognizer.PartialResult()).get(
                            "partial", ""
                        )
                    ).strip()
                    if partial and partial != last_partial:
                        logging.info("[PARTIAL] raw=%r", partial)
                        last_partial = partial

                now = time.monotonic()
                if args.status_interval > 0 and now >= next_status_at:
                    logging.info(
                        "[IDLE] commandなし=%.1fs 大きな音なし=%.1fs "
                        "直近peak=%.1fdBFS",
                        now - (stats.last_command_at or stats.started_at),
                        now - last_loud_audio_at,
                        peak_dbfs,
                    )
                    peak_dbfs = DBFS_FLOOR
                    next_status_at = now + args.status_interval
    except KeyboardInterrupt:
        logging.info("[STOP] Ctrl+Cを受け取りました")
        log_final_result(recognizer.FinalResult(), stats, speech_started_at)
    finally:
        elapsed = time.monotonic() - stats.started_at
        logging.info(
            "[SUMMARY] duration=%.1fs commands=%d rejected=%d audio_errors=%d",
            elapsed,
            stats.command_count,
            stats.rejected_count,
            stats.audio_error_count,
        )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    parser = build_parser()
    args = parser.parse_args()
    validate_args(parser, args)

    if args.list_devices:
        print(sd.query_devices())
        return 0

    if not args.show_vosk_logs:
        SetLogLevel(-1)

    try:
        run(args)
    except Exception as error:
        logging.error("[ERROR] %s: %s", type(error).__name__, error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
