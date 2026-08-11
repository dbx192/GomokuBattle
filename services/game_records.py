from datetime import datetime, timezone

from models.game_stats import UserGameStats, UserGameRating

INITIAL_RATING = 1000
RATING_K = 32


def _rating_delta(winner_rating: int, loser_rating: int) -> int:
    expected = 1 / (1 + 10 ** ((loser_rating - winner_rating) / 400))
    return max(1, round(RATING_K * (1 - expected)))


def _get_rating(db, user_id: int, game_code: str) -> UserGameRating:
    rating = db.query(UserGameRating).filter_by(user_id=user_id, game_code=game_code).first()
    if not rating:
        rating = UserGameRating(user_id=user_id, game_code=game_code, rating=INITIAL_RATING)
        db.add(rating)
        db.flush()
    return rating


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

    # Only player-vs-player match rooms affect competitive ratings.
    player_ids = {color: user_id for color, user_id in players.items() if user_id}
    if getattr(record, "game_type", None) != "room" or len(player_ids) != 2:
        return
    if winner_color is None:
        for user_id in player_ids.values():
            _get_rating(db, user_id, record.game_code).draws += 1
        return
    winner_id = player_ids.get(winner_color)
    loser_id = next((user_id for color, user_id in player_ids.items() if color != winner_color), None)
    if not winner_id or not loser_id:
        return
    winner = _get_rating(db, winner_id, record.game_code)
    loser = _get_rating(db, loser_id, record.game_code)
    delta = _rating_delta(winner.rating, loser.rating)
    result["rating_delta"] = delta
    winner.rating += delta
    loser.rating -= delta
    winner.wins += 1
    loser.losses += 1
