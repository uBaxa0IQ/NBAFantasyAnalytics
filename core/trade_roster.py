"""Keep the same manual selection policy on both sides of a trade."""


def selected_names_after_trade(selected, give, receive):
    return list(dict.fromkeys([name for name in selected if name not in give] + list(receive)))


def validate_ownership(ownership, moves):
    if len(moves) < 2:
        raise ValueError('Нужны две разные команды')
    for team_id, move in moves.items():
        if team_id not in ownership:
            raise ValueError('Команда не найдена')
        if len(move['give']) != len(set(move['give'])) or len(move['receive']) != len(set(move['receive'])):
            raise ValueError('Игрок указан несколько раз')
        if not set(move['give']).issubset(ownership[team_id]):
            raise ValueError('Отдаваемый игрок отсутствует в составе команды')
