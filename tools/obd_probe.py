#!/usr/bin/env python3
"""Probe an ELM327 TCP adapter (host:port). Run on the same LAN as the vehicle.

Examples:
  python3 tools/obd_probe.py 192.168.8.169
  python3 tools/obd_probe.py 192.168.8.169 -p 35000 --quick
"""

from __future__ import annotations

import argparse
import socket
import sys
import time


def read_until(sock: socket.socket, max_wait: float = 25.0) -> str:
    sock.settimeout(0.35)
    buf = b""
    end = time.monotonic() + max_wait
    while time.monotonic() < end:
        try:
            chunk = sock.recv(16384)
            if not chunk:
                break
            buf += chunk
            if b">" in buf:
                time.sleep(0.12)
                try:
                    sock.settimeout(0.15)
                    more = sock.recv(8192)
                    if more:
                        buf += more
                except socket.timeout:
                    pass
                break
        except socket.timeout:
            if buf and b">" in buf:
                break
            continue
    return buf.decode("ascii", errors="replace")


def cmd(sock: socket.socket, line: str, timeout: float) -> str:
    sock.sendall((line + "\r").encode())
    return read_until(sock, timeout)


def main() -> int:
    p = argparse.ArgumentParser(description="ELM327 OBD-II TCP probe")
    p.add_argument("host", help="Adapter IP or hostname")
    p.add_argument(
        "-p",
        "--port",
        type=int,
        default=35000,
        help="TCP port (default 35000)",
    )
    p.add_argument("--quick", action="store_true", help="Skip long PID sweep")
    args = p.parse_args()
    port = args.port

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(15)
    try:
        sock.connect((args.host, port))
    except OSError as e:
        print(f"CONNECT {args.host}:{port} FAILED: {e}", file=sys.stderr)
        return 1

    print(f"=== {args.host}:{port} ===\n")

    cmd(sock, "ATZ", 3)
    time.sleep(1.0)
    read_until(sock, 2)
    for c in ("ATE0", "ATL0", "ATS0", "ATH0", "ATSP0"):
        cmd(sock, c, 5)

    for label, line, tmo in [
        ("ATI", "ATI", 5),
        ("AT DP", "AT DP", 5),
        ("AT RV", "AT RV", 5),
    ]:
        print(f"--- {label} ---")
        print(cmd(sock, line, tmo).replace("\r", "\n").strip())
        print()

    if args.quick:
        sock.close()
        return 0

    # Supported PIDs bitmaps (mode 01)
    for label, obd in [
        ("PID support 01-20", "0100"),
        ("PID support 21-40", "0120"),
        ("PID support 41-60", "0140"),
        ("PID support 61-80", "0160"),
        ("PID support 81-A0", "0180"),
        ("PID support A1-C0", "01A0"),
    ]:
        print(f"--- {label} ({obd}) ---")
        print(cmd(sock, obd, 25).replace("\r", "\n").strip())
        print()

    samples = [
        ("0101", "Monitor status / MIL / DTC count"),
        ("0104", "Engine load %"),
        ("0105", "Coolant temp"),
        ("010B", "Intake MAP kPa"),
        ("010C", "RPM"),
        ("010D", "Speed km/h"),
        ("010E", "Timing advance"),
        ("010F", "Intake air temp"),
        ("0111", "Throttle position %"),
        ("011F", "Run time since start s"),
        ("0121", "Distance w/ MIL on km"),
        ("012F", "Fuel tank level %"),
        ("0142", "Control module V"),
        ("0146", "Ambient air temp"),
        ("015C", "Engine oil temp (if supported)"),
        ("015E", "Engine fuel rate (if supported)"),
    ]
    for obd, desc in samples:
        print(f"--- {obd} — {desc} ---")
        print(cmd(sock, obd, 15).replace("\r", "\n").strip())
        print()

    print("--- Mode 03 — Stored DTCs ---")
    print(cmd(sock, "03", 25).replace("\r", "\n").strip())
    print()

    sock.close()
    print("=== done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
