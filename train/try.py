#!/usr/bin/env python3
"""Dry-run checker for pose -> control -> [A...] conversion.

This script does not send any TCP data. It only mirrors the pose math used by
script.js and then uses train_control_server.py's command encoder.
"""

from __future__ import annotations

import argparse
import asyncio
import errno
import time
from dataclasses import dataclass
from types import SimpleNamespace

from train_control_server import (
    DEFAULT_ACCELERATION_MPS2,
    DEFAULT_BRAKE_MPS2,
    DEFAULT_MAX_SPEED_MPS,
    TrainController,
    clamp,
    handle_client,
)


# Keep these values aligned with script.js.
CONTROL_DEAD_ZONE = 0.08
REQUIRED_VISIBILITY = 0.45
LANDMARK_MARGIN = 0.04
MISSING_POSE_CONTROL = -0.15


@dataclass
class Landmark:
    x: float
    y: float
    visibility: float = 1.0


@dataclass
class PoseResult:
    valid: bool
    reason: str
    raw_control: float | None
    control: float | None


def landmark_visible(landmark: Landmark | None) -> bool:
    return landmark is not None and landmark.visibility >= REQUIRED_VISIBILITY


def landmark_inside_frame(landmark: Landmark) -> bool:
    return (
        landmark.x >= LANDMARK_MARGIN
        and landmark.x <= 1 - LANDMARK_MARGIN
        and landmark.y >= LANDMARK_MARGIN
        and landmark.y <= 1 - LANDMARK_MARGIN
    )


def landmark_distance(a: Landmark, b: Landmark) -> float:
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def calculate_accordion_control(landmarks: list[Landmark | None]) -> PoseResult:
    left_shoulder = landmarks[11]
    right_shoulder = landmarks[12]
    left_wrist = landmarks[15]
    right_wrist = landmarks[16]

    required_landmarks = [left_shoulder, right_shoulder, left_wrist, right_wrist]
    if not all(landmark_visible(landmark) for landmark in required_landmarks):
        return PoseResult(False, "required landmark is not visible", None, None)

    assert left_shoulder is not None
    assert right_shoulder is not None
    assert left_wrist is not None
    assert right_wrist is not None

    if not all(landmark_inside_frame(landmark) for landmark in [left_wrist, right_wrist]):
        return PoseResult(False, "wrist is outside the frame", None, None)

    shoulder_width = landmark_distance(left_shoulder, right_shoulder)
    hand_span = landmark_distance(left_wrist, right_wrist)
    if shoulder_width < 0.04:
        return PoseResult(False, "shoulder width is too small", None, None)

    raw_control = (hand_span - shoulder_width) / shoulder_width
    if abs(raw_control) < CONTROL_DEAD_ZONE:
        return PoseResult(True, "inside dead zone", raw_control, 0.0)

    return PoseResult(True, "ok", raw_control, clamp(raw_control, -1.0, 1.0))


def build_pose(shoulder_width: float, hand_span: float, visibility: float) -> list[Landmark | None]:
    landmarks: list[Landmark | None] = [None] * 33
    shoulder_center_x = 0.5
    wrist_center_x = 0.5

    landmarks[11] = Landmark(shoulder_center_x - shoulder_width / 2, 0.42, visibility)
    landmarks[12] = Landmark(shoulder_center_x + shoulder_width / 2, 0.42, visibility)
    landmarks[15] = Landmark(wrist_center_x - hand_span / 2, 0.65, visibility)
    landmarks[16] = Landmark(wrist_center_x + hand_span / 2, 0.65, visibility)
    return landmarks


def make_controller() -> TrainController:
    args = SimpleNamespace(
        acceleration=DEFAULT_ACCELERATION_MPS2,
        brake=DEFAULT_BRAKE_MPS2,
        control_source="websocket",
        control_timeout=9999.0,
        dead_zone=CONTROL_DEAD_ZONE,
        lost_input_brake=0.35,
        target_position=150.0,
    )
    return TrainController(args)


def make_server_args(args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        host=args.host,
        port=args.port,
        acceleration=DEFAULT_ACCELERATION_MPS2,
        brake=DEFAULT_BRAKE_MPS2,
        control_source="websocket",
        control_timeout=9999.0,
        dead_zone=CONTROL_DEAD_ZONE,
        lost_input_brake=0.35,
        target_position=150.0,
        track_length=180.0,
        max_speed=DEFAULT_MAX_SPEED_MPS,
        rate=20.0,
    )


class DryRunController(TrainController):
    """Receives browser controls and prints the encoded [A...] command only."""

    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__(args)
        self.last_printed_wire: str | None = None
        self.last_printed_control: float | None = None
        self.last_printed_at = 0.0

    async def run(self) -> None:
        while True:
            now = time.monotonic()
            command, power = self.command_from_control()
            wire = self.encode_device_command(command, power).decode("utf-8")

            self.state.command = command
            self.state.power = power
            self.state.elapsedSeconds = now - self.started_at
            self.state.connectedToDevice = False

            should_print = (
                wire != self.last_printed_wire
                or self.last_printed_control is None
                or abs(self.state.control - self.last_printed_control) >= 0.05
                or now - self.last_printed_at >= 1.0
            )
            if should_print:
                print(
                    f"[dry-run] control={self.state.control:+.3f} "
                    f"command={command} power={power:.3f} wire={wire}"
                )
                self.last_printed_wire = wire
                self.last_printed_control = self.state.control
                self.last_printed_at = now

            await self.broadcast_state()
            await asyncio.sleep(1 / self.args.rate)


async def serve_dry_run(args: argparse.Namespace) -> None:
    server_args = make_server_args(args)
    controller = DryRunController(server_args)
    server = await asyncio.start_server(
        lambda reader, writer: handle_client(reader, writer, controller),
        server_args.host,
        server_args.port,
    )

    print("dry-run server: no TCP data is sent")
    print(f"[server] http://{server_args.host}:{server_args.port}/")
    print(f"[server] websocket ws://{server_args.host}:{server_args.port}/ws")
    print("[check] move your arms in the browser; generated [A...] is printed here")

    task = asyncio.create_task(controller.run())
    try:
        async with server:
            await server.serve_forever()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def encode_control(control: float) -> tuple[str, float, str]:
    controller = make_controller()
    controller.receive_control(control)
    command, power = controller.command_from_control()
    encoded = controller.encode_device_command(command, power).decode("utf-8")
    return command, power, encoded


def print_result(name: str, result: PoseResult, missing_pose_control: float) -> None:
    effective_control = result.control
    note = result.reason
    if effective_control is None:
        effective_control = missing_pose_control
        note = f"{result.reason}; script.js fallback control {missing_pose_control:+.2f}"

    command, power, encoded = encode_control(effective_control)
    raw_text = "None" if result.raw_control is None else f"{result.raw_control:+.3f}"
    control_text = "None" if result.control is None else f"{result.control:+.3f}"

    print(
        f"{name:8} "
        f"valid={str(result.valid):5} "
        f"raw={raw_text:>7} "
        f"pose_control={control_text:>7} "
        f"effective_control={effective_control:+.3f} "
        f"command={command:10} "
        f"power={power:.3f} "
        f"wire={encoded:>7} "
        f"note={note}"
    )


def run_preset(name: str, missing_pose_control: float) -> None:
    presets = {
        "open": (0.20, 0.40, 1.0),
        "neutral": (0.20, 0.21, 1.0),
        "close": (0.20, 0.08, 1.0),
        "missing": (0.20, 0.40, 0.0),
    }
    shoulder_width, hand_span, visibility = presets[name]
    result = calculate_accordion_control(build_pose(shoulder_width, hand_span, visibility))
    print_result(name, result, missing_pose_control)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check pose -> control -> [A...] without sending TCP data."
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start a browser dry-run server. Camera pose is used, but TCP data is not sent.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5174)
    parser.add_argument(
        "--preset",
        choices=["all", "open", "neutral", "close", "missing"],
        default="all",
        help="Pose preset to test. Default: all",
    )
    parser.add_argument(
        "--shoulder-width",
        type=float,
        help="Normalized shoulder width for a custom pose, e.g. 0.20",
    )
    parser.add_argument(
        "--hand-span",
        type=float,
        help="Normalized wrist-to-wrist span for a custom pose, e.g. 0.40",
    )
    parser.add_argument(
        "--visibility",
        type=float,
        default=1.0,
        help="Landmark visibility for a custom pose. Default: 1.0",
    )
    parser.add_argument(
        "--control",
        type=float,
        help="Bypass pose math and directly encode this control value (-1.0 to 1.0).",
    )
    parser.add_argument(
        "--missing-pose-control",
        type=float,
        default=MISSING_POSE_CONTROL,
        help="Fallback control used when pose is invalid. Matches script.js default.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.serve:
        try:
            asyncio.run(serve_dry_run(args))
        except KeyboardInterrupt:
            print("\n[dry-run] stopped")
        except OSError as error:
            if error.errno == errno.EADDRINUSE:
                print(f"[server] port {args.port} is already in use.")
                print(f"[server] run with another port: python try.py --serve --port {args.port + 1}")
                return
            raise
        return

    print("dry-run only: no TCP data is sent")
    print(
        f"settings: acceleration={DEFAULT_ACCELERATION_MPS2} m/s^2, "
        f"brake={DEFAULT_BRAKE_MPS2} m/s^2, dead_zone={CONTROL_DEAD_ZONE}"
    )

    if args.control is not None:
        control = clamp(args.control, -1.0, 1.0)
        command, power, encoded = encode_control(control)
        print(
            f"direct   effective_control={control:+.3f} "
            f"command={command:10} power={power:.3f} wire={encoded}"
        )
        return

    if args.shoulder_width is not None or args.hand_span is not None:
        if args.shoulder_width is None or args.hand_span is None:
            raise SystemExit("--shoulder-width and --hand-span must be used together")
        result = calculate_accordion_control(
            build_pose(args.shoulder_width, args.hand_span, args.visibility)
        )
        print_result("custom", result, args.missing_pose_control)
        return

    preset_names = ["open", "neutral", "close", "missing"] if args.preset == "all" else [args.preset]
    for preset_name in preset_names:
        run_preset(preset_name, args.missing_pose_control)


if __name__ == "__main__":
    main()
