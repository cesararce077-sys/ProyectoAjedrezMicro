#!/usr/bin/env python3
"""
Raspberry Pi chess -> Arduino NeoPixel chessboard sender

- Mantains a chess game state (python-chess)
- Sends the current position to an Arduino over Serial as a FEN string (newline-terminated)
- Optional: send legal-move highlight squares after selecting a piece

Arduino side (your sketch) already accepts full FEN or placement-only.
This script sends FULL FEN by default (safe for future expansion).
"""

import time
from dataclasses import dataclass
from typing import Iterable, Optional, List

import serial  # pip install pyserial
import chess   # pip install python-chess
import sys


if sys.platform.startswith("win"):
    SERIAL_PORT = "COM3"       # change to your Windows COM port
else:
    SERIAL_PORT = "/dev/ttyACM0"  # Raspberry Pi / Linux


# -------------------- Serial transport --------------------

@dataclass
class ArduinoLink:
    port: str = "/dev/ttyACM0"
    baud: int = 115200
    timeout: float = 1.0
    write_delay: float = 0.02  # small delay helps some USB-serial setups

    def __post_init__(self):
        self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
        # Give Arduino time to reset after serial open (common on Uno)
        time.sleep(2.0)
        self.flush_input()

    def flush_input(self):
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass

    def send_line(self, line: str) -> None:
        if not line.endswith("\n"):
            line += "\n"
        self.ser.write(line.encode("utf-8"))
        self.ser.flush()
        if self.write_delay:
            time.sleep(self.write_delay)

    def read_line(self) -> str:
        try:
            return self.ser.readline().decode("utf-8", errors="ignore").strip()
        except Exception:
            return ""


# -------------------- Chess -> Arduino messages --------------------

def send_fen(link: ArduinoLink, board: chess.Board) -> None:
    """
    Send full FEN. Arduino sketch parses placement field fine either way.
    """
    fen = board.fen()  # e.g. "rnbqkbnr/pppppppp/8/... w KQkq - 0 1"
    link.send_line(fen)


def send_highlight_squares(link: ArduinoLink, squares: Iterable[chess.Square]) -> None:
    """
    OPTIONAL: If you later extend Arduino to parse highlight commands.
    Format example: "HIGHLIGHT:e4,d5,a1"
    """
    names = [chess.square_name(sq) for sq in squares]
    payload = "HIGHLIGHT:" + ",".join(names)
    link.send_line(payload)


def clear_highlights(link: ArduinoLink) -> None:
    """
    OPTIONAL: If you later extend Arduino to parse "CLEARHIGHLIGHT".
    """
    link.send_line("CLEARHIGHLIGHT")


# -------------------- Example "game loop" --------------------

def pick_move_cli(board: chess.Board) -> chess.Move:
    """
    Minimal CLI: user types UCI like 'e2e4' or SAN like 'Nf3'.
    """
    while True:
        txt = input("Move (UCI 'e2e4' or SAN 'Nf3'): ").strip()
        if not txt:
            continue

        # Try UCI first
        try:
            move = chess.Move.from_uci(txt.lower())
            if move in board.legal_moves:
                return move
        except ValueError:
            pass

        # Try SAN
        try:
            move = board.parse_san(txt)
            if move in board.legal_moves:
                return move
        except ValueError:
            pass

        print("Illegal/invalid move. Try again.")


def main():
    # ---- Configure your serial port here ----
    # On Raspberry Pi it is often /dev/ttyACM0 or /dev/ttyUSB0
    link = ArduinoLink(port=SERIAL_PORT, baud=115200)

    board = chess.Board()  # start position

    # Initial render
    send_fen(link, board)
    print("Sent initial FEN.")
    print("Arduino says:", link.read_line())

    # Simple CLI-driven chess game
    while not board.is_game_over():
        print("\n", board, "\n")
        print("FEN:", board.fen())

        # Example: "overlayed piece selection" support
        # If you have a selected square (e.g., from a GUI or sensors),
        # you can highlight its legal destinations like this:
        #
        # selected = chess.parse_square("e2")
        # legal_dests = [m.to_square for m in board.legal_moves if m.from_square == selected]
        # send_highlight_squares(link, legal_dests)

        move = pick_move_cli(board)
        board.push(move)

        # Update LEDs with new position
        send_fen(link, board)
        # Optional: clear highlights after move
        # clear_highlights(link)

        # Read Arduino response (your sketch prints OK/ERR)
        resp = link.read_line()
        if resp:
            print("Arduino:", resp)

    print("\nGame over:", board.result(), board.outcome())


if __name__ == "__main__":
    main()
