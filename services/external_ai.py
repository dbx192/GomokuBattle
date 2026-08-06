"""External AI engines for all supported board games.

The application owns rules validation. These adapters only ask established
engines for a candidate move and never substitute a handcrafted AI fallback.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from queue import Empty, Queue
from pathlib import Path


class AIEngineError(RuntimeError):
    pass


DIFFICULTIES = {
    "easy": {"label": "简单", "move_time_ms": 250, "depth": 5},
    "normal": {"label": "普通", "move_time_ms": 1000, "depth": 10},
    "hard": {"label": "困难", "move_time_ms": 3000, "depth": 16},
}
ENGINE_ENV = {"gomoku": "RAPFI_PATH", "go": "KATAGO_PATH", "xiangqi": "PIKAFISH_PATH", "chess": "STOCKFISH_PATH"}
PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
    found = next((shutil.which(name) for name in names[game_code] if shutil.which(name)), None)
    if found:
        return found
    local_candidates = {
        "gomoku": [PROJECT_ROOT / "engines/Rapfi-engine/pbrain-rapfi-linux-clang-avx2", PROJECT_ROOT / "engines/Rapfi-engine/pbrain-rapfi-windows-avx2.exe"],
        "go": [PROJECT_ROOT / "engines/katago-v1.15.3-eigen-windows-x64/katago.exe"],
        "xiangqi": [PROJECT_ROOT / "engines/Pikafish.2026-01-02/Linux/pikafish-avx2", PROJECT_ROOT / "engines/Pikafish.2026-01-02/Windows/pikafish-avx2.exe"],
        "chess": [PROJECT_ROOT / "engines/stockfish-windows-x86-64-avx2/stockfish/stockfish-windows-x86-64-avx2.exe"],
    }
    for candidate in local_candidates[game_code]:
        if candidate.is_file() and (os.name == "nt" or candidate.suffix == ".exe" or os.access(candidate, os.X_OK)):
            return str(candidate)
    return None


def go_resources() -> tuple[str | None, str | None]:
    config = os.getenv("KATAGO_CONFIG")
    model = os.getenv("KATAGO_MODEL")
    folder = PROJECT_ROOT / "engines/katago-v1.15.3-eigen-windows-x64"
    config = config or (str(folder / "default_gtp.cfg") if (folder / "default_gtp.cfg").is_file() else None)
    if not model:
        models = list(folder.glob("*.bin.gz"))
        model = str(models[0]) if models else None
    return config, model


def engine_status() -> dict[str, dict]:
    result = {}
    for code, variable in ENGINE_ENV.items():
        path = resolve_path(code)
        ready = bool(path)
        if code == "go":
            config, model = go_resources()
            ready = ready and bool(config) and bool(model)
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


def _run(command: list[str], commands: list[str], timeout: float, cwd: str | None = None, response: callable | None = None) -> str:
    response = response or (lambda line: "bestmove " in line)
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=cwd)
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write("\n".join(commands) + "\n")
        process.stdin.flush()
        lines: Queue[str | None] = Queue()

        def read_output():
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        threading.Thread(target=read_output, daemon=True).start()
        output = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = lines.get(timeout=max(0.01, deadline - time.monotonic()))
            except Empty:
                break
            if line is None:
                break
            output.append(line)
            if response(line):
                break
        if process.poll() is None:
            try:
                process.stdin.write("quit\n")
                process.stdin.flush()
            except OSError:
                pass
            process.kill()
        process.wait(timeout=2)
        return "".join(output)
    except (OSError, subprocess.SubprocessError, Empty) as exc:
        raise AIEngineError("AI 引擎启动或思考失败") from exc


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
    output = _run([path], ["uci", "isready", "ucinewgame", "isready", f"position fen {state['fen']}", f"go movetime {profile['move_time_ms']}"], profile["move_time_ms"] / 1000 + 5, cwd=str(Path(path).parent))
    return {"uci": _bestmove(output)}


def choose_xiangqi(state: dict, difficulty: str) -> dict:
    from services.pikafish import board_to_fen, _uci_to_move

    path = resolve_path("xiangqi")
    if not path:
        raise AIEngineError("Pikafish 未部署，请配置 PIKAFISH_PATH")
    profile = difficulty_profile(difficulty)
    # Pikafish keeps pikafish.nnue one directory above its CPU-specific binary.
    output = _run([path], ["uci", "isready", "ucinewgame", "isready", f"position fen {board_to_fen(state['board'], state['current_player'])}", f"go depth {profile['depth']}"], profile["move_time_ms"] / 1000 + 5, cwd=str(Path(path).parent.parent))
    try:
        return _uci_to_move(_bestmove(output))
    except ValueError as exc:
        raise AIEngineError("Pikafish 返回了无效着法") from exc


def _go_coord(row: int, col: int) -> str:
    files = "ABCDEFGHJKLMNOPQRST"
    return f"{files[col]}{19 - row}"


def choose_go(state: dict, difficulty: str) -> dict:
    path = resolve_path("go")
    config, model = go_resources()
    if not path or not config or not model:
        raise AIEngineError("KataGo 未部署，请配置 KATAGO_PATH、KATAGO_CONFIG 和 KATAGO_MODEL")
    profile = difficulty_profile(difficulty)
    command_id = 0
    def gtp(command: str) -> str:
        nonlocal command_id
        command_id += 1
        return f"{command_id} {command}"

    commands = [gtp("boardsize 19"), gtp("clear_board"), gtp(f"time_settings 0 {max(1, profile['move_time_ms'] // 1000)} 1")]
    for row, values in enumerate(state["board"]):
        for col, stone in enumerate(values):
            if stone:
                commands.append(gtp(f"play {'B' if stone == 1 else 'W'} {_go_coord(row, col)}"))
    commands.append(gtp(f"genmove {'B' if state['current_player'] == 'black' else 'W'}"))
    final_id = command_id
    response_pattern = re.compile(rf"^=\s*{final_id}(?:\s|$)")
    output = _run([path, "gtp", "-config", config, "-model", model], commands, profile["move_time_ms"] / 1000 + 10, response=lambda line: bool(response_pattern.match(line)))
    match = re.search(rf"^=\s*{final_id}\s+([^\s]+)", output, re.MULTILINE)
    if not match:
        raise AIEngineError("KataGo 没有返回可用着法")
    if match.group(1).lower() == "pass":
        return {"pass": True}
    square = match.group(1).upper()
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
    output = _run([path], commands, profile["move_time_ms"] / 1000 + 8, cwd=str(Path(path).parent), response=lambda line: bool(re.match(r"^\s*\d+\s*,\s*\d+\s*$", line)))
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
