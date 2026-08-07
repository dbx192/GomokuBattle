"""Ruleset-neutral game engines used by AI and realtime rooms.

The browser never decides whether a move is legal.  Every engine stores only JSON
state so a game can be resumed from Redis or the database without a live object.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Optional

from services.game_service import GomokuGame


GAME_CATALOG = {
    "gomoku": {"name": "五子棋", "board": {"rows": 15, "cols": 15}, "time_control": {"mode": "per_move", "seconds": 60}},
    "go": {"name": "围棋", "board": {"rows": 19, "cols": 19}, "time_control": {"mode": "per_move", "seconds": 60}},
    "xiangqi": {"name": "中国象棋", "board": {"rows": 10, "cols": 9}, "time_control": {"mode": "per_move", "seconds": 60}},
    "chess": {"name": "国际象棋", "board": {"rows": 8, "cols": 8}, "time_control": {"mode": "per_move", "seconds": 60}},
}


class GameRuleError(ValueError):
    pass


class GameEngine(ABC):
    game_code: str

    @abstractmethod
    def new_state(self) -> dict: ...

    @abstractmethod
    def apply_move(self, state: dict, move: dict, player: str) -> dict: ...

    @abstractmethod
    def undo(self, state: dict) -> dict: ...

    def legal_moves(self, state: dict, player: str) -> list[dict]:
        return []

    def render_state(self, state: dict) -> dict:
        return state


class GomokuEngine(GameEngine):
    game_code = "gomoku"

    def new_state(self):
        return GomokuGame().to_dict() | {"game_code": self.game_code, "current_player": "black", "history": []}

    def _game(self, state):
        payload = dict(state)
        payload["current_player"] = GomokuGame.BLACK if state.get("current_player") == "black" else GomokuGame.WHITE
        return GomokuGame.from_dict(payload)

    def apply_move(self, state, move, player):
        game = self._game(state)
        stone = GomokuGame.BLACK if player == "black" else GomokuGame.WHITE
        row, col = int(move["row"]), int(move["col"])
        if not (0 <= row < 15 and 0 <= col < 15) or game.current_player != stone or not game.add_move(row, col, stone):
            raise GameRuleError("非法落子")
        winner, line = game.check_winner()
        result = game.to_dict() | {"game_code": self.game_code, "current_player": "white" if game.current_player == GomokuGame.WHITE else "black", "history": state.get("history", []) + [{"row": row, "col": col, "player": player}]}
        if winner:
            result["result"] = {"winner": player, "reason": "five_in_a_row", "winning_line": line}
        return result

    def undo(self, state):
        game = self._game(state)
        if not game.undo_move():
            raise GameRuleError("没有可撤销的步数")
        return game.to_dict() | {"game_code": self.game_code, "current_player": "white" if game.current_player == GomokuGame.WHITE else "black", "history": state.get("history", [])[:-1]}


class GoEngine(GameEngine):
    game_code = "go"
    size = 19

    def new_state(self):
        board = [[0] * self.size for _ in range(self.size)]
        return {"game_code": self.game_code, "board": board, "current_player": "black", "history": [], "position_history": [self._hash(board, "black")], "passes": 0, "phase": "playing", "komi": 7.5}

    def _hash(self, board, next_player):
        return next_player + ":" + "".join(str(cell) for row in board for cell in row)

    def _group(self, board, row, col):
        color, pending, group = board[row][col], [(row, col)], set()
        while pending:
            r, c = pending.pop()
            if (r, c) in group or not (0 <= r < self.size and 0 <= c < self.size) or board[r][c] != color:
                continue
            group.add((r, c))
            pending.extend(((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)))
        return group

    def _liberties(self, board, group):
        return {(r + dr, c + dc) for r, c in group for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)) if 0 <= r + dr < self.size and 0 <= c + dc < self.size and board[r + dr][c + dc] == 0}

    def apply_move(self, state, move, player):
        if state.get("phase") not in {"playing", "scoring"} or state.get("current_player") != player:
            raise GameRuleError("当前不能落子")
        if state.get("phase") == "scoring":
            raise GameRuleError("数子阶段只能确认死子或继续对局")
        result = deepcopy(state)
        other, stone = ("white", 1) if player == "black" else ("black", 2)
        if move.get("pass"):
            result["history"].append({"player": player, "pass": True})
            result["passes"] += 1
            result["current_player"] = other
            if result["passes"] >= 2:
                result["phase"] = "scoring"
                result["dead_marks"] = {"black": [], "white": []}
            return result
        row, col = int(move["row"]), int(move["col"])
        if not (0 <= row < self.size and 0 <= col < self.size) or result["board"][row][col] != 0:
            raise GameRuleError("非法落子")
        board = result["board"]
        board[row][col] = stone
        captured = []
        for nr, nc in ((row + 1, col), (row - 1, col), (row, col + 1), (row, col - 1)):
            if 0 <= nr < self.size and 0 <= nc < self.size and board[nr][nc] == (3 - stone):
                group = self._group(board, nr, nc)
                if not self._liberties(board, group):
                    captured.extend(group)
        for r, c in captured:
            board[r][c] = 0
        own_group = self._group(board, row, col)
        # Chinese rules allow suicide; the entire self-captured group is removed.
        self_captured = []
        if not self._liberties(board, own_group):
            self_captured = list(own_group)
            for r, c in self_captured:
                board[r][c] = 0
        next_hash = self._hash(board, other)
        if next_hash in result["position_history"]:
            raise GameRuleError("全局同形禁入")
        result["position_history"].append(next_hash)
        result["history"].append({"player": player, "row": row, "col": col, "captured": [list(p) for p in captured], "self_captured": [list(p) for p in self_captured]})
        result["passes"] = 0
        result["current_player"] = other
        return result

    def mark_dead(self, state, player, points):
        if state.get("phase") != "scoring":
            raise GameRuleError("尚未进入数子阶段")
        result = deepcopy(state)
        result["dead_marks"][player] = [list(point) for point in sorted({tuple(point) for point in points})]
        if result["dead_marks"]["black"] == result["dead_marks"]["white"]:
            dead = set(result["dead_marks"]["black"])
            board = result["board"]
            black = sum(cell == 1 for row in board for cell in row) - sum(board[r][c] == 1 for r, c in dead)
            white = sum(cell == 2 for row in board for cell in row) - sum(board[r][c] == 2 for r, c in dead) + result["komi"]
            result["result"] = {"winner": "black" if black > white else "white", "reason": "chinese_scoring", "score": {"black": black, "white": white}}
            result["phase"] = "completed"
        return result

    def resume(self, state):
        result = deepcopy(state)
        result.update({"phase": "playing", "passes": 0, "dead_marks": {}})
        return result

    def undo(self, state):
        history = state.get("history", [])
        if not history:
            raise GameRuleError("没有可撤销的步数")

        # Replaying the validated move history restores captures, self-capture,
        # ko hashes, and pass state without trusting client-provided snapshots.
        restored = self.new_state()
        for item in history[:-1]:
            move = {"pass": True} if item.get("pass") else {"row": item["row"], "col": item["col"]}
            restored = self.apply_move(restored, move, item["player"])
        return restored


class ChessEngine(GameEngine):
    game_code = "chess"

    def _chess(self):
        try:
            import chess
            return chess
        except ImportError as exc:
            raise GameRuleError("国际象棋依赖未安装，请安装 python-chess") from exc

    def new_state(self):
        chess = self._chess(); board = chess.Board()
        return self._serialize(board, [])

    def _serialize(self, board, history):
        chess = self._chess()
        squares = {}
        for square, piece in board.piece_map().items():
            squares[chess.square_name(square)] = piece.symbol()
        state = {"game_code": self.game_code, "fen": board.fen(), "current_player": "white" if board.turn else "black", "board": squares, "history": history}
        if board.is_checkmate(): state["result"] = {"winner": "black" if board.turn else "white", "reason": "checkmate"}
        elif board.is_stalemate(): state["result"] = {"winner": None, "reason": "stalemate"}
        elif board.is_insufficient_material(): state["result"] = {"winner": None, "reason": "insufficient_material"}
        elif board.is_seventyfive_moves(): state["result"] = {"winner": None, "reason": "seventyfive_moves"}
        elif board.is_fivefold_repetition(): state["result"] = {"winner": None, "reason": "fivefold_repetition"}
        return state

    def apply_move(self, state, move, player):
        chess = self._chess(); board = chess.Board(state["fen"])
        if state.get("current_player") != player: raise GameRuleError("当前不是你的回合")
        try: chess_move = chess.Move.from_uci(move["uci"])
        except (KeyError, ValueError) as exc: raise GameRuleError("无效的 UCI 着法") from exc
        if chess_move not in board.legal_moves: raise GameRuleError("非法走子")
        san = board.san(chess_move); board.push(chess_move)
        return self._serialize(board, state.get("history", []) + [{"player": player, "uci": chess_move.uci(), "san": san}])

    def undo(self, state):
        history = state.get("history", [])
        if not history: raise GameRuleError("没有可撤销的步数")
        chess = self._chess(); board = chess.Board()
        for item in history[:-1]: board.push_uci(item["uci"])
        return self._serialize(board, history[:-1])


class XiangqiEngine(GameEngine):
    """Server-side Chinese chess legality engine. Pieces use red uppercase / black lowercase."""
    game_code = "xiangqi"
    initial = [list("rheakaehr"), list("000000000"), list("0c00000c0"), list("p0p0p0p0p"), list("000000000"), list("000000000"), list("P0P0P0P0P"), list("0C00000C0"), list("000000000"), list("RHEAKAEHR")]

    def new_state(self):
        return {"game_code": self.game_code, "board": deepcopy(self.initial), "current_player": "red", "history": []}

    def _color(self, p): return "red" if p.isupper() else "black"
    def _inside(self, r, c): return 0 <= r < 10 and 0 <= c < 9
    def _palace(self, r, c, color): return 3 <= c <= 5 and ((7 <= r <= 9) if color == "red" else (0 <= r <= 2))
    def _clear_line(self, board, a, b):
        r1, c1 = a; r2, c2 = b
        if r1 != r2 and c1 != c2: return False, 0
        dr = 0 if r1 == r2 else (1 if r2 > r1 else -1); dc = 0 if c1 == c2 else (1 if c2 > c1 else -1)
        r, c, count = r1 + dr, c1 + dc, 0
        while (r, c) != (r2, c2):
            count += board[r][c] != "0"; r += dr; c += dc
        return True, count

    def _pseudo(self, board, r, c):
        p = board[r][c]
        if p == "0": return []
        color, kind, moves = self._color(p), p.lower(), []
        def add(nr, nc):
            if self._inside(nr, nc) and (board[nr][nc] == "0" or self._color(board[nr][nc]) != color): moves.append((nr, nc))
        if kind == "k":
            for dr, dc in ((1,0),(-1,0),(0,1),(0,-1)):
                if self._palace(r+dr,c+dc,color): add(r+dr,c+dc)
            # flying general
            for nr in range(r + (1 if color == "black" else -1), 10 if color == "black" else -1, 1 if color == "black" else -1):
                if board[nr][c] != "0":
                    if board[nr][c].lower() == "k" and self._color(board[nr][c]) != color: moves.append((nr,c))
                    break
        elif kind == "a":
            for dr,dc in ((1,1),(1,-1),(-1,1),(-1,-1)):
                if self._palace(r+dr,c+dc,color): add(r+dr,c+dc)
        elif kind == "e":
            for dr,dc in ((2,2),(2,-2),(-2,2),(-2,-2)):
                nr,nc=r+dr,c+dc
                if self._inside(nr,nc) and board[r+dr//2][c+dc//2] == "0" and ((nr >= 5) if color == "red" else (nr <= 4)): add(nr,nc)
        elif kind == "h":
            for dr,dc,lr,lc in ((2,1,1,0),(2,-1,1,0),(-2,1,-1,0),(-2,-1,-1,0),(1,2,0,1),(-1,2,0,1),(1,-2,0,-1),(-1,-2,0,-1)):
                if self._inside(r+dr,c+dc) and board[r+lr][c+lc] == "0": add(r+dr,c+dc)
        elif kind in {"r","c"}:
            for dr,dc in ((1,0),(-1,0),(0,1),(0,-1)):
                seen=0; nr,nc=r+dr,c+dc
                while self._inside(nr,nc):
                    target=board[nr][nc]
                    if kind == "r":
                        if target == "0": moves.append((nr,nc))
                        else:
                            if self._color(target)!=color: moves.append((nr,nc))
                            break
                    else:
                        if target == "0":
                            if seen == 0:
                                moves.append((nr, nc))
                        else:
                            seen += 1
                            if seen == 2:
                                if self._color(target)!=color: moves.append((nr,nc))
                                break
                        nr+=dr; nc+=dc; continue
                    nr+=dr; nc+=dc
        elif kind == "p":
            forward = -1 if color == "red" else 1
            add(r+forward,c)
            crossed = r <= 4 if color == "red" else r >= 5
            if crossed: add(r,c-1); add(r,c+1)
        return moves

    def _in_check(self, board, color):
        general = "K" if color == "red" else "k"; pos = next(((r,c) for r,row in enumerate(board) for c,p in enumerate(row) if p == general), None)
        if not pos: return True
        return any(pos in self._pseudo(board,r,c) for r,row in enumerate(board) for c,p in enumerate(row) if p != "0" and self._color(p) != color)

    def _legal(self, board, color):
        moves=[]
        for r,row in enumerate(board):
            for c,p in enumerate(row):
                if p != "0" and self._color(p)==color:
                    for nr,nc in self._pseudo(board,r,c):
                        copy=deepcopy(board); copy[nr][nc]=p; copy[r][c]="0"
                        if not self._in_check(copy,color): moves.append((r,c,nr,nc))
        return moves

    def apply_move(self,state,move,player):
        if state.get("current_player") != player: raise GameRuleError("当前不是你的回合")
        fr,fc,tr,tc=(int(move[k]) for k in ("from_row","from_col","to_row","to_col"))
        if (fr,fc,tr,tc) not in self._legal(state["board"],player): raise GameRuleError("非法走子")
        result=deepcopy(state); piece=result["board"][fr][fc]; captured=result["board"][tr][tc]
        result["board"][tr][tc]=piece; result["board"][fr][fc]="0"; other="black" if player=="red" else "red"; result["current_player"]=other
        result["history"].append({"player":player,"from_row":fr,"from_col":fc,"to_row":tr,"to_col":tc,"piece":piece,"captured":captured})
        if not self._legal(result["board"],other): result["result"]={"winner":player,"reason":"checkmate" if self._in_check(result["board"],other) else "stalemate"}
        return result

    def undo(self,state):
        history=state.get("history",[])
        if not history: raise GameRuleError("没有可撤销的步数")
        result=deepcopy(state); item=history[-1]; result["board"][item["from_row"]][item["from_col"]]=item["piece"]; result["board"][item["to_row"]][item["to_col"]]=item["captured"]; result["current_player"]=item["player"]; result["history"]=history[:-1]; result.pop("result",None); return result


ENGINES = {"gomoku": GomokuEngine(), "go": GoEngine(), "xiangqi": XiangqiEngine(), "chess": ChessEngine()}


def get_engine(game_code: str) -> GameEngine:
    try: return ENGINES[game_code]
    except KeyError as exc: raise GameRuleError("不支持的棋种") from exc
