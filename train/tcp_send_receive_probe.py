#!/usr/bin/env python3
"""Small TCP probe for checking [A...] send and [D...]/[T...] receive.

This script does not start the game UI. It only connects to device B,
sends bracketed acceleration commands, and prints bracketed distance and
elapsed-time messages received from the device.
"""

from __future__ import annotations

import argparse
import socket
import time


# ===== Easy settings =====
DEVICE_HOST = "192.168.4.1"
DEVICE_PORT = 8080

# Acceleration commands in mm/s^2.
SEND_VALUES_MMPS2 = [50]
SEND_INTERVAL_SECONDS = 1.0
RECEIVE_TIMEOUT_SECONDS = 0.1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check TCP [A...] send and [D...]/[T...] receive")
    parser.add_argument("--host", default=DEVICE_HOST)
    parser.add_argument("--port", type=int, default=DEVICE_PORT)
    parser.add_argument("--interval", type=float, default=SEND_INTERVAL_SECONDS)
    parser.add_argument("--timeout", type=float, default=RECEIVE_TIMEOUT_SECONDS)
    parser.add_argument(
        "--values",
        default=",".join(str(value) for value in SEND_VALUES_MMPS2),
        help="Comma-separated acceleration values in mm/s^2, e.g. 100,0,-300,0",
    )
    return parser.parse_args()


def extract_telemetry_messages(buffer: str) -> tuple[list[tuple[str, int]], str]:
    messages: list[tuple[str, int]] = []

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
        buffer = buffer[end + 1 :]

        if not message.startswith(("[D", "[d", "[T", "[t")):
            print(f"[recv] ignored {message!r}")
            continue

        try:
            messages.append((message[1].upper(), int(message[2:-1])))
        except ValueError:
            print(f"[recv] invalid {message!r}")


def receive_available(sock: socket.socket, buffer: str) -> str:
    while True:
        try:
            data = sock.recv(4096)
        except socket.timeout:
            return buffer

        if not data:
            raise ConnectionError("device disconnected")

        buffer += data.decode("utf-8", errors="replace")
        messages, buffer = extract_telemetry_messages(buffer)
        now = time.strftime("%H:%M:%S")
        for kind, value in messages:
            if kind == "D":
                label = f"distance {value}mm" if value >= 0 else f"overshoot {abs(value)}mm"
                print(f"[{now}] recv [D{value}] -> {label}")
            elif kind == "T":
                print(f"[{now}] recv [T{value}] -> elapsed {value / 1000.0:.3f}s")


def main() -> None:
    args = parse_args()
    values = [int(value.strip()) for value in args.values.split(",") if value.strip()]
    if not values:
        raise SystemExit("at least one --values entry is required")

    print(f"[probe] connecting to {args.host}:{args.port}")
    print("[probe] press Ctrl+C to stop")

    buffer = ""
    index = 0
    with socket.create_connection((args.host, args.port), timeout=5.0) as sock:
        sock.settimeout(args.timeout)
        print("[probe] connected")

        while True:
            acceleration_mmps2 = values[index % len(values)]
            index += 1
            command = f"[A{acceleration_mmps2}]"
            sock.sendall(command.encode("utf-8"))
            print(f"[send] {command}")

            deadline = time.monotonic() + args.interval
            while time.monotonic() < deadline:
                buffer = receive_available(sock, buffer)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[probe] stopped")
    except OSError as error:
        print(f"[probe] connection error: {error}")
