"""Optional Pikafish adapter for Chinese-chess AI sessions.

Pikafish speaks the UCI command protocol. The rules engine remains the
authority: a returned move is converted back to board coordinates and checked
before it is applied.
"""
from __future__ import annotations

def board_to_fen(board: list[list[str]], current_player: str) -> str:
    """Serialize the internal 10x9 board into a Pikafish-compatible FEN."""
    rows = []
    for row in board:
        empty = 0
        fields = []
        for piece in row:
            if piece == "0":
                empty += 1
            else:
                if empty:
                    fields.append(str(empty))
                    empty = 0
                fields.append(piece)
        if empty:
            fields.append(str(empty))
        rows.append("".join(fields))
    # Internal row 0 is the black home rank (FEN rank 9), so rows already have
    # the correct top-to-bottom order.
    side = "w" if current_player == "red" else "b"
    return "/".join(rows) + f" {side} - - 0 1"


def _uci_to_move(uci: str) -> dict[str, int]:
    if len(uci) < 4:
        raise ValueError("Pikafish returned an invalid move")
    files = {char: index for index, char in enumerate("abcdefghi")}
    try:
        fc, fr = files[uci[0]], int(uci[1])
        tc, tr = files[uci[2]], int(uci[3])
    except (KeyError, ValueError) as exc:
        raise ValueError("Pikafish returned an invalid move") from exc
    if not (0 <= fr <= 9 and 0 <= tr <= 9):
        raise ValueError("Pikafish returned an invalid move")
    return {"from_row": 9 - fr, "from_col": fc, "to_row": 9 - tr, "to_col": tc}

