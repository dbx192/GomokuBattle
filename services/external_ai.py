"""External AI engines for all supported board games.

The application owns rules validation. These adapters only ask established
engines for a candidate move and never substitute a handcrafted AI fallback.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


class AIEngineError(RuntimeError):
    pass


DIFFICULTIES = {
    "easy": {"label": "简单", "move_time_ms": 250, "depth": 5},
    "normal": {"label": "普通", "move_time_ms": 1000, "depth": 10},
    "hard": {"label": "困难", "move_time_ms": 3000, "depth": 16},
}
ENGINE_ENV = {"gomoku": "RAPFI_PATH", "go": "KATAGO_PATH", "xiangqi": "PIKAFISH_PATH", "chess": "STOCKFISH_PATH"}


def difficulty_profile(value: str) -> dict:
    try:
        return DIFFICULTIES[value]
    except KeyError as exc:
        raise AIEngineError("不支持的 AI 难度") from exc


def resolve_path(game_code: str) -> str | None:
    variable = ENGINE_ENV[game_code]
    configured = os.getenv(variable)
    if configured:
        path = Path(configured).expanduser()
        return str(path) if path.is_file() and (os.name == "nt" or os.access(path, os.X_OK)) else None
    names = {"gomoku": ("rapfi", "rapfi.exe"), "go": ("katago", "katago.exe"), "xiangqi": ("pikafish", "pikafish.exe"), "chess": ("stockfish", "stockfish.exe")}
    return next((found for name in names[game_code] if (found := shutil.which(name))), None)


def engine_status() -> dict[str, dict]:
    result = {}
    for code, variable in ENGINE_ENV.items():
        path = resolve_path(code)
        ready = bool(path)
        if code == "go":
            ready = ready and bool(os.getenv("KATAGO_CONFIG")) and bool(os.getenv("KATAGO_MODEL"))
        result[code] = {"configured": ready, "path": path, "variable": variable}
    return result


def require_engine(game_code: str) -> None:
    if engine_status()[game_code]["configured"]:
        return
    messages = {
        "gomoku": "Rapfi 未部署，请配置 RAPFI_PATH",
        "go": "KataGo 未部署，请配置 KATAGO_PATH、KATAGO_CONFIG 和 KATAGO_MODEL",
        "xiangqi": "Pikafish 未部署，请配置 PIKAFISH_PATH",
        "chess": "Stockfish 未部署，请配置 STOCKFISH_PATH",
    }
    raise AIEngineError(messages[game_code])


def _run(command: list[str], commands: list[str], timeout: float, cwd: str | None = None) -> str:
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=cwd)
        output, _ = process.communicate("\n".join(commands) + "\n", timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AIEngineError("AI 引擎启动或思考失败") from exc
    return output


def _bestmove(output: str) -> str:
    match = re.search(r"^bestmove\s+(\S+)", output, re.MULTILINE)
    if not match or match.group(1) == "(none)":
        raise AIEngineError("AI 引擎没有返回可用着法")
    return match.group(1)


def choose_chess(state: dict, difficulty: str) -> dict:
    path = resolve_path("chess")
    if not path:
        raise AIEngineError("Stockfish 未部署，请配置 STOCKFISH_PATH")
    profile = difficulty_profile(difficulty)
    output = _run([path], ["uci", "isready", f"position fen {state['fen']}", f"go movetime {profile['move_time_ms']}"], profile["move_time_ms"] / 1000 + 5)
    return {"uci": _bestmove(output)}


def choose_xiangqi(state: dict, difficulty: str) -> dict:
    from services.pikafish import board_to_fen, _uci_to_move

    path = resolve_path("xiangqi")
    if not path:
        raise AIEngineError("Pikafish 未部署，请配置 PIKAFISH_PATH")
    profile = difficulty_profile(difficulty)
    output = _run([path], ["uci", "isready", f"position fen {board_to_fen(state['board'], state['current_player'])}", f"go depth {profile['depth']}"], profile["move_time_ms"] / 1000 + 5)
    try:
        return _uci_to_move(_bestmove(output))
    except ValueError as exc:
        raise AIEngineError("Pikafish 返回了无效着法") from exc


def _go_coord(row: int, col: int) -> str:
    files = "ABCDEFGHJKLMNOPQRST"
    return f"{files[col]}{19 - row}"


def choose_go(state: dict, difficulty: str) -> dict:
    path = resolve_path("go")
    config, model = os.getenv("KATAGO_CONFIG"), os.getenv("KATAGO_MODEL")
    if not path or not config or not model:
        raise AIEngineError("KataGo 未部署，请配置 KATAGO_PATH、KATAGO_CONFIG 和 KATAGO_MODEL")
    profile = difficulty_profile(difficulty)
    commands = ["boardsize 19", "clear_board", f"time_settings 0 {max(1, profile['move_time_ms'] // 1000)} 1"]
    for row, values in enumerate(state["board"]):
        for col, stone in enumerate(values):
            if stone:
                commands.append(f"play {'B' if stone == 1 else 'W'} {_go_coord(row, col)}")
    commands.append(f"genmove {'B' if state['current_player'] == 'black' else 'W'}")
    output = _run([path, "gtp", "-config", config, "-model", model], commands, profile["move_time_ms"] / 1000 + 10)
    responses = [line[1:].strip() for line in output.splitlines() if line.startswith("=")]
    if not responses or responses[-1].lower() == "pass":
        return {"pass": True}
    square = responses[-1].split()[0].upper()
    files = "ABCDEFGHJKLMNOPQRST"
    try:
        return {"row": 19 - int(square[1:]), "col": files.index(square[0])}
    except (ValueError, IndexError) as exc:
        raise AIEngineError("KataGo 返回了无效着法") from exc


def choose_gomoku(state: dict, difficulty: str) -> dict:
    path = resolve_path("gomoku")
    if not path:
        raise AIEngineError("Rapfi 未部署，请配置 RAPFI_PATH")
    profile = difficulty_profile(difficulty)
    commands = ["START 15", f"INFO timeout_turn {profile['move_time_ms']}", "BOARD"]
    for row, values in enumerate(state["board"]):
        for col, stone in enumerate(values):
            if stone:
                commands.append(f"{col},{row},{stone}")
    commands.append("DONE")
    output = _run([path], commands, profile["move_time_ms"] / 1000 + 8, cwd=str(Path(path).parent))
    match = re.search(r"^(\d+)\s*,\s*(\d+)\s*$", output, re.MULTILINE)
    if not match:
        raise AIEngineError("Rapfi 没有返回可用着法")
    return {"row": int(match.group(2)), "col": int(match.group(1))}


def choose_move(game_code: str, state: dict, difficulty: str) -> dict:
    selectors = {"gomoku": choose_gomoku, "go": choose_go, "xiangqi": choose_xiangqi, "chess": choose_chess}
    try:
        return selectors[game_code](state, difficulty)
    except KeyError as exc:
        raise AIEngineError("不支持的 AI 棋种") from exc
