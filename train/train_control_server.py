#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import errno
import hashlib
import json
import mimetypes
import os
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
ROOT = Path(__file__).resolve().parent

# ===== Easy settings =====
# Change these values for device B.
DEVICE_HOST = "192.168.4.1"  # Device B IP address
DEVICE_PORT = 8080

# SI units:
#   speed: m/s
#   acceleration/brake: m/s^2
DEFAULT_ACCELERATION_MPS2 = 0.7
DEFAULT_BRAKE_MPS2 = 0.7
DEFAULT_MAX_SPEED_MPS = 40
DEFAULT_RATE_HZ = 100.0
DEFAULT_STOP_SPEED_THRESHOLD_MPS = 0.02
DEFAULT_STOP_HOLD_SECONDS = 0.5
DEFAULT_START_DISTANCE_THRESHOLD_MM = 5

# Local pseudo demo only. These do not affect the [A...] command sent to device B.
LOCAL_DEMO_ACCELERATION_MPS2 = 6.7
LOCAL_DEMO_BRAKE_MPS2 = 9.4

# A -> B command wire format:
#   bracketed signed acceleration in mm/s^2.
#   examples: "[A100]", "[A-300]", "[A0]"
SEND_FORMAT = "bracketed_acceleration_mmps2"

# B -> A telemetry wire format:
#   "[D1022]"                                  -> 1022 mm before target
#   "[D-20]"                                   -> 20 mm beyond target
#   "[T1234]"                                  -> elapsed time 1234 ms
RECEIVE_FORMATS = ("bracketed_distance_mm", "bracketed_elapsed_ms")


@dataclass
class TrainState:
    positionMeters: float = 0.0
    speedMps: float = 0.0
    control: float = 0.0
    command: str = "stop"
    power: float = 0.0
    connectedToDevice: bool = False
    emergencyStop: bool = False
    elapsedSeconds: float | None = None
    distanceToTargetMm: int | None = None
    scoreDistanceMm: int | None = None
    runStarted: bool = False
    gameOver: bool = False


class TrainController:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.state = TrainState()
        self.started_at = time.monotonic()
        self.last_tick = time.monotonic()
        self.last_control_at = time.monotonic()
        self.last_telemetry_at = 0.0
        self.last_distance_at = 0.0
        self.clients: set[asyncio.StreamWriter] = set()
        self.device_writer: asyncio.StreamWriter | None = None
        self.command_seq = 0
        self.pseudo_next_change_at = time.monotonic() + 1.2
        self.pseudo_target_control = 0.7
        self.initial_distance_to_target_mm: int | None = None
        self.last_motion_at = 0.0
        self.uses_device_elapsed_time = False

    def receive_control(self, value: float) -> None:
        if self.state.emergencyStop or self.state.gameOver:
            return

        self.state.control = clamp(float(value), -1.0, 1.0)
        self.last_control_at = time.monotonic()

    def emergency_stop(self) -> None:
        self.state.emergencyStop = True
        self.state.control = -1.0
        self.state.command = "stop"
        self.state.power = 1.0

    def clear_emergency_stop(self) -> None:
        self.state.emergencyStop = False
        self.state.control = 0.0
        self.state.command = "keep"
        self.state.power = 0.0

    def reset(self) -> None:
        self.state = TrainState()
        self.started_at = time.monotonic()
        self.last_tick = time.monotonic()
        self.last_control_at = time.monotonic()
        self.last_telemetry_at = 0.0
        self.last_distance_at = 0.0
        self.command_seq = 0
        self.pseudo_next_change_at = time.monotonic() + 1.2
        self.pseudo_target_control = 0.7
        self.initial_distance_to_target_mm = None
        self.last_motion_at = 0.0
        self.uses_device_elapsed_time = False

    def receive_telemetry(self, data: Any) -> None:
        now = time.monotonic()

        if not isinstance(data, dict):
            return

        if "distanceToTargetMm" in data:
            self.receive_distance_to_target(int(data["distanceToTargetMm"]), now)

        if "elapsedTimeMs" in data:
            self.receive_elapsed_time_ms(int(data["elapsedTimeMs"]), now)

    def receive_elapsed_time_ms(self, elapsed_ms: int, now: float) -> None:
        self.state.elapsedSeconds = max(elapsed_ms, 0) / 1000.0
        self.last_telemetry_at = now
        self.uses_device_elapsed_time = True

    def receive_distance_to_target(self, distance_mm: int, now: float) -> None:
        previous_distance_mm = self.state.distanceToTargetMm
        previous_time = self.last_distance_at
        self.state.distanceToTargetMm = distance_mm
        self.state.positionMeters = clamp(
            self.args.target_position - (distance_mm / 1000.0),
            0.0,
            self.args.track_length,
        )

        speed_mps = self.state.speedMps
        if previous_distance_mm is not None and previous_time > 0:
            dt = max(now - previous_time, 0.001)
            signed_speed_mps = (previous_distance_mm - distance_mm) / 1000.0 / dt
            speed_mps = abs(signed_speed_mps)
            self.state.speedMps = clamp(speed_mps, 0.0, self.args.max_speed)

        self.update_game_result(distance_mm, speed_mps, now)
        self.last_distance_at = now
        self.last_telemetry_at = now

    def update_game_result(self, distance_mm: int, speed_mps: float, now: float) -> None:
        if self.initial_distance_to_target_mm is None:
            self.initial_distance_to_target_mm = distance_mm

        moved_mm = abs(distance_mm - self.initial_distance_to_target_mm)
        is_moving = speed_mps > self.args.stop_speed_threshold
        if moved_mm >= self.args.start_distance_threshold_mm or is_moving:
            self.state.runStarted = True

        if is_moving:
            self.last_motion_at = now
            return

        if (
            self.state.runStarted
            and not self.state.gameOver
            and self.last_motion_at > 0
            and now - self.last_motion_at >= self.args.stop_hold_time
        ):
            self.finish_run(distance_mm)

    def finish_run(self, distance_mm: int) -> None:
        self.state.gameOver = True
        self.state.scoreDistanceMm = distance_mm
        self.state.control = 0.0
        self.state.command = "keep"
        self.state.power = 0.0
        self.state.speedMps = 0.0

    def command_from_control(self) -> tuple[str, float]:
        if self.state.emergencyStop:
            return "stop", 1.0

        if self.state.gameOver:
            return "keep", 0.0

        now = time.monotonic()
        if self.args.control_source == "websocket" and now - self.last_control_at > self.args.control_timeout:
            return "brake", self.args.lost_input_brake

        if self.state.positionMeters >= self.args.target_position:
            return "brake", 1.0

        control = self.state.control
        if control > self.args.dead_zone:
            return "accelerate", min(control, 1.0)
        if control < -self.args.dead_zone:
            return "brake", min(abs(control), 1.0)
        return "keep", 0.0

    def update_pseudo_control(self, now: float) -> None:
        if self.args.control_source != "pseudo":
            return

        if self.args.pseudo_pattern == "wave":
            elapsed = now - self.started_at
            self.state.control = math.sin(elapsed * self.args.pseudo_frequency * math.tau)
            self.last_control_at = now
            return

        if now >= self.pseudo_next_change_at:
            self.pseudo_target_control = (os.urandom(1)[0] / 127.5) - 1.0
            self.pseudo_next_change_at = now + self.args.pseudo_min_interval + (
                (os.urandom(1)[0] / 255.0) * (self.args.pseudo_max_interval - self.args.pseudo_min_interval)
            )

        smoothing = clamp(self.args.pseudo_smoothing, 0.0, 1.0)
        self.state.control += (self.pseudo_target_control - self.state.control) * smoothing
        self.last_control_at = now

    def tick_local_demo(self, dt: float, now: float) -> None:
        command, power = self.state.command, self.state.power

        # Pseudo mode has no device [T...] telemetry, so advance its demo clock locally.
        if not self.state.gameOver:
            self.state.elapsedSeconds = max(now - self.started_at, 0.0)

        if command == "accelerate":
            self.state.speedMps += LOCAL_DEMO_ACCELERATION_MPS2 * power * dt
        elif command == "brake":
            self.state.speedMps -= LOCAL_DEMO_BRAKE_MPS2 * max(power, 0.15) * dt
        elif command == "stop":
            self.state.speedMps -= LOCAL_DEMO_BRAKE_MPS2 * dt

        self.state.speedMps = clamp(self.state.speedMps, 0.0, self.args.max_speed)
        self.state.positionMeters = clamp(
            self.state.positionMeters + self.state.speedMps * dt,
            0.0,
            self.args.track_length,
        )

        distance_mm = int(round((self.args.target_position - self.state.positionMeters) * 1000))
        self.state.distanceToTargetMm = distance_mm
        self.update_game_result(distance_mm, self.state.speedMps, now)

    async def run(self) -> None:
        while True:
            now = time.monotonic()
            dt = min(now - self.last_tick, 0.08)
            self.last_tick = now

            self.update_pseudo_control(now)
            command, power = self.command_from_control()
            connected_to_device = now - self.last_telemetry_at < self.args.telemetry_timeout

            if self.args.control_source == "pseudo":
                connected_to_device = False
            elif not connected_to_device:
                command = "brake"
                power = self.args.lost_telemetry_brake

            self.state.command = command
            self.state.power = power
            self.state.connectedToDevice = connected_to_device

            if self.args.control_source == "pseudo":
                self.tick_local_demo(dt, now)
            else:
                await self.send_device_command(command, power)

            await self.broadcast_state()
            await asyncio.sleep(1 / self.args.rate)

    def make_device_acceleration(self, command: str, power: float) -> float:
        """Convert the current command into signed acceleration for device B."""
        self.command_seq += 1
        if command == "accelerate":
            return self.args.acceleration * power
        if command == "brake":
            return -self.args.brake * max(power, 0.15)
        if command == "stop":
            return -self.args.brake
        return 0.0

    def encode_device_command(self, command: str, power: float) -> bytes:
        """Encode A -> B command.

        Wire format is bracketed signed acceleration in mm/s^2.
        Positive = accelerate, negative = brake, zero = keep speed.
        """
        accel_mps2 = self.make_device_acceleration(command, power)
        accel_mmps2 = int(round(accel_mps2 * 1000))
        return f"[A{accel_mmps2}]".encode()

    async def send_device_command(self, command: str, power: float) -> None:
        encoded = self.encode_device_command(command, power)

        if self.device_writer:
            try:
                self.device_writer.write(encoded)
                await self.device_writer.drain()
            except OSError:
                self.device_writer = None

    async def broadcast_state(self) -> None:
        message = {
            "type": "state",
            "controlSource": self.args.control_source,
            **asdict(self.state),
        }
        await broadcast_ws(self.clients, message)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


async def broadcast_ws(clients: set[asyncio.StreamWriter], payload: dict[str, Any]) -> None:
    if not clients:
        return

    data = encode_ws_frame(json.dumps(payload, separators=(",", ":")))
    stale: list[asyncio.StreamWriter] = []
    for writer in clients:
        try:
            writer.write(data)
            await writer.drain()
        except OSError:
            stale.append(writer)

    for writer in stale:
        clients.discard(writer)


async def read_http_request(reader: asyncio.StreamReader) -> tuple[str, str, dict[str, str], bytes]:
    raw = await reader.readuntil(b"\r\n\r\n")
    header_text = raw.decode("iso-8859-1")
    lines = header_text.split("\r\n")
    method, path, _ = lines[0].split(" ", 2)
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return method, path, headers, raw


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    controller: TrainController,
) -> None:
    try:
        method, path, headers, _ = await read_http_request(reader)
        clean_path = path.split("?", 1)[0]
        if clean_path == "/ws" and headers.get("upgrade", "").lower() == "websocket":
            await handle_websocket(reader, writer, headers, controller)
            return

        await serve_file(writer, method, clean_path)
    except (asyncio.IncompleteReadError, ConnectionError, OSError):
        pass
    finally:
        if not writer.is_closing():
            writer.close()
            await writer.wait_closed()


async def handle_websocket(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    headers: dict[str, str],
    controller: TrainController,
) -> None:
    key = headers.get("sec-websocket-key", "")
    accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
    )
    writer.write(response.encode())
    await writer.drain()
    controller.clients.add(writer)

    try:
        while True:
            message = await read_ws_text(reader)
            if message is None:
                break
            await handle_ws_message(message, controller)
    finally:
        controller.clients.discard(writer)


async def handle_ws_message(message: str, controller: TrainController) -> None:
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return

    msg_type = data.get("type")
    if msg_type == "control":
        controller.receive_control(float(data.get("control", 0.0)))
    elif msg_type == "emergency_stop":
        controller.emergency_stop()
    elif msg_type == "clear_emergency_stop":
        controller.clear_emergency_stop()
    elif msg_type == "reset":
        controller.reset()


async def read_ws_text(reader: asyncio.StreamReader) -> str | None:
    first = await reader.readexactly(2)
    opcode = first[0] & 0x0F
    masked = bool(first[1] & 0x80)
    length = first[1] & 0x7F

    if opcode == 0x8:
        return None
    if opcode != 0x1:
        return ""

    if length == 126:
        length = int.from_bytes(await reader.readexactly(2), "big")
    elif length == 127:
        length = int.from_bytes(await reader.readexactly(8), "big")

    mask = await reader.readexactly(4) if masked else b"\x00\x00\x00\x00"
    payload = await reader.readexactly(length)
    if masked:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return payload.decode("utf-8", errors="replace")


def encode_ws_frame(text: str) -> bytes:
    payload = text.encode("utf-8")
    length = len(payload)
    if length < 126:
        header = bytes([0x81, length])
    elif length < 65536:
        header = bytes([0x81, 126]) + length.to_bytes(2, "big")
    else:
        header = bytes([0x81, 127]) + length.to_bytes(8, "big")
    return header + payload


async def serve_file(writer: asyncio.StreamWriter, method: str, path: str) -> None:
    if method not in {"GET", "HEAD"}:
        await send_response(writer, 405, b"Method Not Allowed", "text/plain; charset=utf-8")
        return

    relative = "index.html" if path in {"", "/"} else path.lstrip("/")
    file_path = (ROOT / relative).resolve()
    if ROOT not in file_path.parents and file_path != ROOT:
        await send_response(writer, 403, b"Forbidden", "text/plain; charset=utf-8")
        return
    if not file_path.is_file():
        await send_response(writer, 404, b"Not Found", "text/plain; charset=utf-8")
        return

    body = b"" if method == "HEAD" else file_path.read_bytes()
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    await send_response(writer, 200, body, content_type, file_path.stat().st_size)


async def send_response(
    writer: asyncio.StreamWriter,
    status: int,
    body: bytes,
    content_type: str,
    content_length: int | None = None,
) -> None:
    reason = {
        200: "OK",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
    }.get(status, "OK")
    length = len(body) if content_length is None else content_length
    header = (
        f"HTTP/1.1 {status} {reason}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {length}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n\r\n"
    )
    writer.write(header.encode() + body)
    await writer.drain()


async def run_tcp_device(controller: TrainController, args: argparse.Namespace) -> None:
    while True:
        try:
            reader, writer = await asyncio.open_connection(args.device_host, args.device_port)
            controller.device_writer = writer
            buffer = ""
            print(f"[device] tcp connected {args.device_host}:{args.device_port}")
            while True:
                chunk = await reader.read(1024)
                if not chunk:
                    raise ConnectionError("device disconnected")
                buffer += chunk.decode("utf-8", errors="replace")
                messages, buffer = extract_wire_messages(buffer)
                for message in messages:
                    try:
                        payload = parse_wire_payload(message)
                    except ValueError:
                        print(f"[device] ignored invalid telemetry: {message!r}")
                        continue
                    controller.receive_telemetry(payload)
        except (OSError, ConnectionError) as error:
            controller.device_writer = None
            print(f"[device] reconnecting after error: {error}")
            await asyncio.sleep(args.reconnect_delay)


def extract_wire_messages(buffer: str) -> tuple[list[str], str]:
    messages: list[str] = []

    while True:
        start = buffer.find("[")
        if start < 0:
            return messages, ""
        if start > 0:
            buffer = buffer[start:]

        end = buffer.find("]")
        if end < 0:
            return messages, buffer[-4096:]

        message = buffer[: end + 1]
        if message.startswith(("[D", "[d", "[T", "[t")):
            messages.append(message)
        buffer = buffer[end + 1 :]


def parse_wire_payload(data: bytes | str) -> Any:
    text = data.decode("utf-8", errors="replace").strip() if isinstance(data, bytes) else data.strip()
    bracketed = parse_bracketed_message(text)
    if bracketed is None:
        raise ValueError(f"unsupported telemetry format: {text!r}")
    return bracketed


def parse_bracketed_message(text: str) -> dict[str, Any] | None:
    if not (text.startswith("[") and text.endswith("]")):
        return None

    body = text[1:-1].strip()
    if len(body) < 2:
        raise ValueError(f"invalid bracketed message: {text!r}")

    command = body[0].upper()
    value = int(body[1:].strip())
    if command == "D":
        return {"distanceToTargetMm": value}
    if command == "T":
        return {"elapsedTimeMs": value}
    raise ValueError(f"unknown bracketed message command: {command!r}")


async def main_async(args: argparse.Namespace) -> None:
    controller = TrainController(args)
    server = await asyncio.start_server(
        lambda reader, writer: handle_client(reader, writer, controller),
        args.host,
        args.port,
    )

    print(f"[server] http://{args.host}:{args.port}/")
    print(f"[server] websocket ws://{args.host}:{args.port}/ws")

    tasks = [asyncio.create_task(controller.run())]
    if args.control_source == "pseudo":
        print("[device] tcp skipped in pseudo mode")
    else:
        print(f"[device] tcp target {args.device_host}:{args.device_port}")
        tasks.append(asyncio.create_task(run_tcp_device(controller, args)))

    try:
        async with server:
            await server.serve_forever()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Python backend for the train-stop UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5173")))
    parser.add_argument("--control-source", choices=["websocket", "pseudo"], default="websocket")
    parser.add_argument("--pseudo-pattern", choices=["random", "wave"], default="random")
    parser.add_argument("--pseudo-frequency", type=float, default=0.12)
    parser.add_argument("--pseudo-min-interval", type=float, default=0.8)
    parser.add_argument("--pseudo-max-interval", type=float, default=2.4)
    parser.add_argument("--pseudo-smoothing", type=float, default=0.04)
    parser.set_defaults(device_host=DEVICE_HOST)
    parser.set_defaults(device_port=DEVICE_PORT)
    parser.add_argument("--track-length", type=float, default=180.0)
    parser.add_argument("--target-position", type=float, default=150.0)
    parser.add_argument("--max-speed", type=float, default=DEFAULT_MAX_SPEED_MPS, help="Maximum speed in m/s")
    parser.set_defaults(acceleration=DEFAULT_ACCELERATION_MPS2)
    parser.set_defaults(brake=DEFAULT_BRAKE_MPS2)
    parser.add_argument("--dead-zone", type=float, default=0.08)
    parser.add_argument("--control-timeout", type=float, default=0.35)
    parser.add_argument("--telemetry-timeout", type=float, default=0.7)
    parser.add_argument("--stop-speed-threshold", type=float, default=DEFAULT_STOP_SPEED_THRESHOLD_MPS)
    parser.add_argument("--stop-hold-time", type=float, default=DEFAULT_STOP_HOLD_SECONDS)
    parser.add_argument("--start-distance-threshold-mm", type=int, default=DEFAULT_START_DISTANCE_THRESHOLD_MM)
    parser.add_argument("--lost-input-brake", type=float, default=0.35)
    parser.add_argument("--lost-telemetry-brake", type=float, default=1.0)
    parser.add_argument("--reconnect-delay", type=float, default=1.0)
    parser.add_argument("--rate", type=float, default=DEFAULT_RATE_HZ)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\n[server] stopped")
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            print(f"[server] port {args.port} is already in use.")
            print(f"[server] stop the existing server or run with: python3 train_control_server.py --port {args.port + 1}")
            return
        raise


if __name__ == "__main__":
    main()
