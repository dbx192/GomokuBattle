"""Optional native-engine discovery.

The rules API remains usable without binaries; production deployments can point
these variables at Stockfish, Pikafish, and KataGo for stronger AI adapters.
"""
import os
import shutil

ENGINE_ENV = {"chess": "STOCKFISH_PATH", "xiangqi": "PIKAFISH_PATH", "go": "KATAGO_PATH"}


def engine_status() -> dict[str, dict]:
    result = {}
    for game_code, variable in ENGINE_ENV.items():
        configured = os.getenv(variable)
        executable = configured or shutil.which(variable.removesuffix("_PATH").lower())
        result[game_code] = {"configured": bool(executable), "path": executable, "variable": variable}
    return result
