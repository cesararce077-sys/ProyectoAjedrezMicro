#!/usr/bin/env python3
"""
Raspberry Pi chess -> Arduino NeoPixel chessboard sender (GUI mejorada)

- Mantiene el estado de la partida con python-chess.
- Muestra un tablero gráfico con Tkinter.
- El usuario mueve haciendo clic en las casillas.
- Resalta:
    * Casilla seleccionada (azul)
    * Movimientos legales sin captura (verde)
    * Movimientos legales con captura (amarillo)
    * Casillas no disponibles (rojo) mientras hay selección
- Etiquetas de filas y columnas (A..H, 8..1) alrededor del tablero.
- Modos de juego:
    * 2 jugadores
    * Jugador vs máquina (humano = blancas, máquina = negras)
- Tras cada movimiento válido, envía la FEN actual al Arduino vía Serial.
- No cambia la lógica/protocolo del Arduino: solo se envía la FEN (una línea por posición).
"""

import time
from dataclasses import dataclass
from typing import Iterable, Set

import serial          # pip install pyserial
import chess           # pip install python-chess
import sys
import glob
import random
import tkinter as tk
from tkinter import messagebox


# -------------------- Detección básica del puerto serie --------------------

if sys.platform.startswith("win"):
    SERIAL_PORT = "COM3"      # ajusta al COM real en Windows
else:
    # Raspberry Pi / Linux: intenta encontrar /dev/ttyACM* o /dev/ttyUSB*
    candidates = glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
    if not candidates:
        raise RuntimeError(
            "No se encontró ningún puerto serie (/dev/ttyACM* ni /dev/ttyUSB*). "
            "Conecta el Arduino y revisa con: ls /dev/ttyACM* /dev/ttyUSB*"
        )
    SERIAL_PORT = candidates[0]  # usa el primero que aparezca


# -------------------- Serial transport --------------------

@dataclass
class ArduinoLink:
    port: str = "/dev/ttyACM0"
    baud: int = 115200
    timeout: float = 1.0
    write_delay: float = 0.02  # pequeño delay ayuda en algunos USB-serial

    def __post_init__(self):
        self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
        # tiempo para que el Arduino se reinicie tras abrir el puerto
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

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


# -------------------- Funciones de alto nivel para Arduino --------------------

def send_fen(link: ArduinoLink, board: chess.Board) -> None:
    """
    Envía FEN completa. El Arduino usa el campo de colocación de piezas.
    """
    fen = board.fen()
    link.send_line(fen)


# -------------------- GUI de ajedrez --------------------

PIECE_SYMBOLS = {
    "P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
    "p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚",
}

# Colores base del tablero
LIGHT_COLOR = "#f0d9b5"
DARK_COLOR = "#b58863"

# Colores de resaltado
SELECT_COLOR = "#4fc3f7"      # casilla seleccionada (azul)
MOVE_COLOR = "#81c784"        # movimientos legales sin captura (verde)
CAPTURE_COLOR = "#fff59d"     # movimientos legales con captura (amarillo)
INVALID_COLOR = "#ef9a9a"     # casillas no disponibles (rojo)


class ChessGUI:
    def __init__(self, root: tk.Tk, link: ArduinoLink):
        self.root = root
        self.link = link

        self.board = chess.Board()
        self.selected_square = None         # tipo: Optional[chess.Square]
        self.legal_targets: Set[int] = set()
        self.capture_targets: Set[int] = set()

        self.buttons = {}                   # (rank, file) -> tk.Button

        # Modo de juego: "pvp" (2 jugadores) o "pvc" (jugador vs computadora)
        self.mode_var = tk.StringVar(value="pvp")

        self._build_ui()

        # Enviar posición inicial al Arduino
        self.send_position_to_arduino()
        self.update_board()

    # ---------- Construcción de la interfaz ----------

    def _build_ui(self):
        self.root.title("Tablero de ajedrez – Raspberry Pi → Arduino")

        # Contenedor del tablero con etiquetas
        self.board_frame = tk.Frame(self.root)
        self.board_frame.pack(padx=10, pady=10)

        files = ["A", "B", "C", "D", "E", "F", "G", "H"]

        # Fila superior: etiquetas de columnas
        tk.Label(self.board_frame, text="").grid(row=0, column=0)  # esquina vacía
        for file_idx, file_char in enumerate(files):
            tk.Label(self.board_frame, text=file_char, font=("DejaVu Sans", 10)).grid(
                row=0, column=file_idx + 1
            )
        tk.Label(self.board_frame, text="").grid(row=0, column=9)  # esquina vacía

        # Filas del tablero + etiquetas de filas
        for rank_visual in range(8):  # 0 (fila superior) .. 7 (inferior)
            board_rank = 7 - rank_visual   # 7..0
            row_grid = rank_visual + 1

            # etiqueta de fila izquierda (8..1)
            rank_label = 8 - rank_visual
            tk.Label(self.board_frame, text=str(rank_label), font=("DejaVu Sans", 10)).grid(
                row=row_grid, column=0
            )

            # casillas A..H
            for file_visual in range(8):
                board_file = file_visual      # 0..7
                col_grid = file_visual + 1

                btn = tk.Button(
                    self.board_frame,
                    width=4,
                    height=2,
                    font=("DejaVu Sans", 18),
                    relief="flat",
                    bd=1,
                    command=lambda r=board_rank, f=board_file: self.on_square_clicked(r, f)
                )
                btn.grid(row=row_grid, column=col_grid)
                self.buttons[(board_rank, board_file)] = btn

            # etiqueta de fila derecha
            tk.Label(self.board_frame, text=str(rank_label), font=("DejaVu Sans", 10)).grid(
                row=row_grid, column=9
            )

        # Fila inferior: etiquetas de columnas
        tk.Label(self.board_frame, text="").grid(row=9, column=0)
        for file_idx, file_char in enumerate(files):
            tk.Label(self.board_frame, text=file_char, font=("DejaVu Sans", 10)).grid(
                row=9, column=file_idx + 1
            )
        tk.Label(self.board_frame, text="").grid(row=9, column=9)

        # Controles (modo de juego, reinicio)
        control_frame = tk.Frame(self.root)
        control_frame.pack(pady=5)

        # Modo de juego
        tk.Label(control_frame, text="Modo de juego:").pack(side=tk.LEFT, padx=5)

        rb_pvp = tk.Radiobutton(
            control_frame,
            text="2 jugadores",
            variable=self.mode_var,
            value="pvp"
        )
        rb_pvp.pack(side=tk.LEFT, padx=5)

        rb_pvc = tk.Radiobutton(
            control_frame,
            text="Jugador vs máquina (blancas)",
            variable=self.mode_var,
            value="pvc"
        )
        rb_pvc.pack(side=tk.LEFT, padx=5)

        # Botón de reinicio
        reset_btn = tk.Button(control_frame, text="Reiniciar partida", command=self.reset_game)
        reset_btn.pack(side=tk.LEFT, padx=10)

        info_label = tk.Label(
            control_frame,
            text="Click en pieza propia → click en casilla destino",
            font=("DejaVu Sans", 10)
        )
        info_label.pack(side=tk.LEFT, padx=5)

    # ---------- Lógica de interacción ----------

    def on_square_clicked(self, rank: int, file: int):
        """
        rank, file en coordenadas de python-chess:
        - rank: 0..7 (0 = fila 1, 7 = fila 8)
        - file: 0..7 (0 = columna 'a', 7 = columna 'h')
        """
        if self.board.is_game_over():
            return

        # Si es jugador vs máquina y es turno de la máquina, ignorar clics
        if self.mode_var.get() == "pvc" and self.board.turn == chess.BLACK:
            return

        sq = chess.square(file, rank)

        # Primer click: seleccionar pieza
        if self.selected_square is None:
            piece = self.board.piece_at(sq)
            if piece is None or piece.color != self.board.turn:
                # Click en casilla vacía o pieza del rival: ignorar
                return

            self.selected_square = sq
            self._compute_targets_for_selected()

        else:
            # Segundo click: intentar mover
            if sq == self.selected_square:
                # Desseleccionar si se hace click de nuevo en la misma casilla
                self.selected_square = None
                self.legal_targets.clear()
                self.capture_targets.clear()
            else:
                move = chess.Move(self.selected_square, sq)

                # Manejo mínimo de coronación: si es peón que llega al final, asumir dama
                if move not in self.board.legal_moves:
                    if self._is_pawn_promotion(self.selected_square, sq):
                        move = chess.Move(self.selected_square, sq, promotion=chess.QUEEN)

                if move in self.board.legal_moves:
                    # Ejecutar movimiento humano
                    self.board.push(move)
                    self.selected_square = None
                    self.legal_targets.clear()
                    self.capture_targets.clear()

                    # Enviar nueva posición al Arduino
                    self.send_position_to_arduino()

                    # Opcional: leer respuesta del Arduino (OK/ERR, etc.)
                    resp = self.link.read_line()
                    if resp:
                        print("Arduino:", resp)

                    # Fin de partida tras movimiento humano
                    if self.board.is_game_over():
                        self._show_game_over()
                    else:
                        # Si es jugador vs máquina, hace el movimiento la máquina
                        if self.mode_var.get() == "pvc":
                            self._make_computer_move()
                else:
                    # Movimiento ilegal: limpiamos selección
                    self.selected_square = None
                    self.legal_targets.clear()
                    self.capture_targets.clear()

        self.update_board()

    def _compute_targets_for_selected(self):
        """Calcula destinos legales y capturas para la casilla seleccionada."""
        self.legal_targets.clear()
        self.capture_targets.clear()
        if self.selected_square is None:
            return

        for m in self.board.legal_moves:
            if m.from_square == self.selected_square:
                self.legal_targets.add(m.to_square)
                if self.board.is_capture(m):
                    self.capture_targets.add(m.to_square)

    def _is_pawn_promotion(self, from_sq: int, to_sq: int) -> bool:
        piece = self.board.piece_at(from_sq)
        if piece is None or piece.piece_type != chess.PAWN:
            return False
        to_rank = chess.square_rank(to_sq)
        # Blancas coronan en rank 7, negras en rank 0
        return (piece.color == chess.WHITE and to_rank == 7) or \
               (piece.color == chess.BLACK and to_rank == 0)

    # ---------- Movimiento de la "máquina" ----------

    def _make_computer_move(self):
        """Movimiento muy simple de la máquina: elige un movimiento legal al azar."""
        if self.board.is_game_over():
            return

        legal = list(self.board.legal_moves)
        if not legal:
            return

        move = random.choice(legal)
        self.board.push(move)

        # Enviar nueva posición al Arduino
        self.send_position_to_arduino()

        resp = self.link.read_line()
        if resp:
            print("Arduino (máquina):", resp)

        if self.board.is_game_over():
            self._show_game_over()

    def _show_game_over(self):
        outcome = self.board.outcome()
        result = self.board.result()
        msg = f"Resultado: {result}"
        if outcome and outcome.termination:
            msg += f" ({outcome.termination.name})"
        messagebox.showinfo("Fin de la partida", msg)

    # ---------- Actualización visual ----------

    def update_board(self):
        for square in chess.SQUARES:
            file = chess.square_file(square)
            rank = chess.square_rank(square)

            btn = self.buttons[(rank, file)]
            piece = self.board.piece_at(square)

            # Si no hay selección, usamos colores de tablero normales
            if self.selected_square is None:
                base_color = LIGHT_COLOR if (rank + file) % 2 == 0 else DARK_COLOR
                bg = base_color
            else:
                # Hay una casilla seleccionada: aplicamos lógica de resaltado
                if self.selected_square == square:
                    bg = SELECT_COLOR
                elif square in self.capture_targets:
                    bg = CAPTURE_COLOR    # captura = amarillo
                elif square in self.legal_targets:
                    bg = MOVE_COLOR       # movimiento legal sin captura = verde
                else:
                    bg = INVALID_COLOR    # casilla no disponible = rojo

            btn.configure(bg=bg, activebackground=bg)

            # Texto: solo pieza; las casillas vacías NO muestran coordenada
            if piece is None:
                btn.configure(text="")
            else:
                symbol = piece.symbol()
                btn.configure(text=PIECE_SYMBOLS.get(symbol, symbol))

    # ---------- Comunicación con Arduino ----------

    def send_position_to_arduino(self):
        try:
            send_fen(self.link, self.board)
        except Exception as e:
            print("Error enviando FEN al Arduino:", e)

    # ---------- Control de partida ----------

    def reset_game(self):
        self.board = chess.Board()
        self.selected_square = None
        self.legal_targets.clear()
        self.capture_targets.clear()
        self.send_position_to_arduino()
        self.update_board()


# -------------------- main --------------------

def main():
    link = ArduinoLink(port=SERIAL_PORT, baud=115200)

    root = tk.Tk()
    gui = ChessGUI(root, link)

    def on_close():
        gui.link.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
