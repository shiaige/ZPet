"""Manual sender — same protocol as zpet-sender.exe, for testing or as a
fallback if the exe is missing: `python zpet_send.py <state>` (payload on stdin).
"""
import socket
import sys

PORT = 57891


def main():
    state = sys.argv[1] if len(sys.argv) > 1 else "idle"
    payload = sys.stdin.buffer.read(48 * 1024)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(state.encode("ascii") + b"\x1f" + payload, ("127.0.0.1", PORT))
    s.close()


if __name__ == "__main__":
    main()
