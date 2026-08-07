"""External AI engines for all supported board games.

The application owns rules validation. These adapters only ask established
engines for a candidate move and never substitute a handcrafted AI fallback.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import platform
from collections import deque
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
    # Windows builds run directly under WSL and include their adjacent DLLs. Prefer
    # them there because older Linux KataGo builds can depend on unavailable system
    # OpenSSL/libzip versions.
    is_wsl = "microsoft" in platform.release().lower()
    katago_candidates = [
        PROJECT_ROOT / "engines/katago-v1.15.3-eigen-windows-x64/katago.exe",
        PROJECT_ROOT / "engines/katago-v1.15.3-eigen-linux-x64/katago",
    ] if is_wsl else [
        PROJECT_ROOT / "engines/katago-v1.15.3-eigen-linux-x64/katago",
        PROJECT_ROOT / "engines/katago-v1.15.3-eigen-windows-x64/katago.exe",
    ]
    local_candidates = {
        "gomoku": [PROJECT_ROOT / "engines/Rapfi-engine/pbrain-rapfi-linux-clang-avx2", PROJECT_ROOT / "engines/Rapfi-engine/pbrain-rapfi-windows-avx2.exe"],
        "go": katago_candidates,
        "xiangqi": [PROJECT_ROOT / "engines/Pikafish.2026-01-02/Linux/pikafish-avx2", PROJECT_ROOT / "engines/Pikafish.2026-01-02/Windows/pikafish-avx2.exe"],
        "chess": [PROJECT_ROOT / "engines/stockfish-ubuntu-x86-64-avx2/stockfish/stockfish-ubuntu-x86-64-avx2", PROJECT_ROOT / "engines/stockfish-windows-x86-64-avx2/stockfish/stockfish-windows-x86-64-avx2.exe"],
    }
    for candidate in local_candidates[game_code]:
        if candidate.is_file() and (os.name == "nt" or candidate.suffix == ".exe" or os.access(candidate, os.X_OK)):
            return str(candidate)
    return None


def go_resources() -> tuple[str | None, str | None]:
    config = os.getenv("KATAGO_CONFIG")
    model = os.getenv("KATAGO_MODEL")
    path = resolve_path("go")
    folder = Path(path).parent if path else None
    config_file = folder / "default_gtp.cfg" if folder else None
    config = config or (str(config_file) if config_file and config_file.is_file() else None)
    if not model:
        models = sorted((PROJECT_ROOT / "engines").rglob("*.bin.gz"))
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
        process_command = command
        # Windows console programs executed from WSL may buffer stdout forever
        # when connected to a pipe. `script` gives them a pseudo-terminal while
        # retaining the same stdin/stdout contract for the adapters.
        if os.name != "nt" and Path(command[0]).suffix.lower() == ".exe":
            launch_dir = cwd or os.getcwd()
            windows_command = [command[0]]
            for argument in command[1:]:
                candidate = Path(argument)
                windows_command.append(os.path.relpath(candidate, launch_dir) if candidate.is_absolute() and candidate.is_file() else argument)
            process_command = ["script", "-qfec", shlex.join(windows_command), "/dev/null"]
        process = subprocess.Popen(process_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=cwd)
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


class _PersistentGtp:
    """One serialized KataGo GTP process, keeping the neural model in memory."""

    def __init__(self):
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._output: Queue[str | None] = Queue()
        self._output_tail: deque[str] = deque(maxlen=12)
        self._stderr_tail: deque[str] = deque(maxlen=12)
        self._command: tuple[str, ...] | None = None
        self._cwd: str | None = None

    def _stop(self):
        if self._process and self._process.poll() is None:
            self._process.kill()
            self._process.wait(timeout=2)
        self._process = None
        self._command = None
        self._cwd = None
        self._output = Queue()
        self._output_tail.clear()
        self._stderr_tail.clear()

    def _start(self, command: list[str], cwd: str | None):
        process_command = command
        if os.name != "nt" and Path(command[0]).suffix.lower() == ".exe":
            launch_dir = cwd or os.getcwd()
            windows_command = [command[0]]
            for argument in command[1:]:
                candidate = Path(argument)
                windows_command.append(os.path.relpath(candidate, launch_dir) if candidate.is_absolute() and candidate.is_file() else argument)
            process_command = ["script", "-qfec", shlex.join(windows_command), "/dev/null"]
        process = subprocess.Popen(process_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd)
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        self._process = process
        self._command, self._cwd = tuple(command), cwd

        def read_output():
            for line in process.stdout:
                self._output_tail.append(line.strip())
                self._output.put(line)
            self._output.put(None)

        def read_stderr():
            for line in process.stderr:
                self._stderr_tail.append(line.strip())

        threading.Thread(target=read_output, daemon=True).start()
        threading.Thread(target=read_stderr, daemon=True).start()

    def _exit_error(self) -> AIEngineError:
        code = self._process.poll() if self._process else None
        detail = " ".join(self._stderr_tail or self._output_tail).strip()
        suffix = f"（退出码 {code}{'：' + detail if detail else ''}）"
        return AIEngineError("KataGo 意外退出" + suffix)

    def request(self, command: list[str], commands: list[str], timeout: float, cwd: str, response: callable) -> str:
        with self._lock:
            for attempt in range(2):
                if self._process is None or self._process.poll() is not None or self._command != tuple(command) or self._cwd != cwd:
                    self._stop()
                    try:
                        self._start(command, cwd)
                    except (OSError, subprocess.SubprocessError) as exc:
                        self._stop()
                        raise AIEngineError("KataGo 引擎启动失败") from exc
                try:
                    assert self._process and self._process.stdin
                    self._process.stdin.write("\n".join(commands) + "\n")
                    self._process.stdin.flush()
                    output, deadline, exited = [], time.monotonic() + timeout, False
                    while time.monotonic() < deadline:
                        try:
                            line = self._output.get(timeout=max(0.01, deadline - time.monotonic()))
                        except Empty:
                            break
                        if line is None:
                            error = self._exit_error()
                            self._stop()
                            if attempt == 0:
                                exited = True
                                break
                            raise error
                        output.append(line)
                        if response(line):
                            return "".join(output)
                    if exited:
                        continue
                    raise AIEngineError("KataGo 思考超时")
                except (OSError, subprocess.SubprocessError) as exc:
                    self._stop()
                    raise AIEngineError("KataGo 引擎通信失败") from exc
            raise AIEngineError("KataGo 意外退出")


_KATAGO_GTP = _PersistentGtp()


def warm_go_engine() -> None:
    """Start loading KataGo in the background; failures remain visible on play."""
    path = resolve_path("go")
    config, model = go_resources()
    if not path or not config or not model:
        return
    command = [path, "gtp", "-config", config, "-model", model]
    if "human" in Path(model).name.lower():
        command.extend(["-override-config", "humanSLProfile=rank_9d"])
    try:
        with _KATAGO_GTP._lock:
            if _KATAGO_GTP._process is None or _KATAGO_GTP._process.poll() is not None:
                _KATAGO_GTP._stop()
                _KATAGO_GTP._start(command, str(Path(path).parent))
    except (AIEngineError, OSError, subprocess.SubprocessError):
        _KATAGO_GTP._stop()


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
    command = [path, "gtp", "-config", config, "-model", model]
    # The b18c human SL model distributed with KataGo requires profile metadata
    # even when used as the main model. A normal KataGo model does not need this.
    if "human" in Path(model).name.lower():
        command.extend(["-override-config", "humanSLProfile=rank_9d"])
    # KataGo model initialization is costly. Keep one serialized GTP process
    # alive so normal moves do not reload the model every turn.
    output = _KATAGO_GTP.request(command, commands, profile["move_time_ms"] / 1000 + 10, str(Path(path).parent), response=lambda line: bool(response_pattern.match(line)))
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
    row, col = int(match.group(2)), int(match.group(1))
    if not (0 <= row < 15 and 0 <= col < 15) or state["board"][row][col] != 0:
        raise AIEngineError("Rapfi 返回了非法着法")
    return {"row": row, "col": col}


def choose_move(game_code: str, state: dict, difficulty: str) -> dict:
    selectors = {"gomoku": choose_gomoku, "go": choose_go, "xiangqi": choose_xiangqi, "chess": choose_chess}
    try:
        return selectors[game_code](state, difficulty)
    except KeyError as exc:
        raise AIEngineError("不支持的 AI 棋种") from exc
