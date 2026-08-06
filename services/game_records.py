from datetime import datetime, timezone

from models.game_stats import UserGameStats


def apply_result(db, record, state: dict, players: dict[str, int | None]):
    """Persist a terminal state and update only the relevant game's statistics once."""
    result = state.get("result")
    if not result or record.status == "completed":
        return
    winner_color = result.get("winner")
    record.status = "completed"
    record.result_reason = result.get("reason")
    record.ended_at = datetime.now(timezone.utc)
    record.winner_id = players.get(winner_color) if winner_color else None
    for color, user_id in players.items():
        if not user_id:
            continue
        stats = db.query(UserGameStats).filter_by(user_id=user_id, game_code=record.game_code).first()
        if not stats:
            stats = UserGameStats(user_id=user_id, game_code=record.game_code, wins=0, losses=0, draws=0)
            db.add(stats)
        if winner_color is None:
            stats.draws = (stats.draws or 0) + 1
        elif color == winner_color:
            stats.wins = (stats.wins or 0) + 1
        else:
            stats.losses = (stats.losses or 0) + 1
