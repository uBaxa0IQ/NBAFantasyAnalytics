const playerKey = (player) => player.player_id != null
    ? `id:${player.player_id}`
    : `name:${player.name?.trim().toLowerCase()}`;

export const mergeFreeAgentPlayers = (marketPlayers = [], recommendedPlayers = []) => {
    const recommendations = new Map(recommendedPlayers.map(player => [playerKey(player), player]));
    const seen = new Set();
    const players = marketPlayers.map(player => {
        const key = playerKey(player);
        seen.add(key);
        return { ...player, ...recommendations.get(key) };
    });

    // A recommendation may be present in a refreshed ESPN response but not in
    // the separately fetched market snapshot. Keep it visible in that case.
    recommendedPlayers.forEach(player => {
        if (!seen.has(playerKey(player))) players.push(player);
    });

    return players;
};
