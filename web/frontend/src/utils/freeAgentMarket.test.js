import test from 'node:test';
import assert from 'node:assert/strict';
import { mergeFreeAgentPlayers } from './freeAgentMarket.js';

test('keeps the full free-agent market when there are no recommendations', () => {
    const market = [
        { player_id: 1, name: 'Player One', z_scores: { STL: 1 } },
        { player_id: 2, name: 'Player Two', z_scores: { STL: 2 } },
    ];

    assert.deepEqual(mergeFreeAgentPlayers(market, []), market);
});

test('adds matchup recommendations without hiding other free agents', () => {
    const market = [
        { player_id: 1, name: 'Player One', z_scores: { STL: 1 } },
        { player_id: 2, name: 'Player Two', z_scores: { STL: 2 } },
    ];
    const recommendations = [
        { player_id: 2, name: 'Player Two', matchup_gain: 0.4, drop_player: 'Bench Player' },
    ];

    assert.deepEqual(mergeFreeAgentPlayers(market, recommendations), [
        market[0],
        { ...market[1], ...recommendations[0] },
    ]);
});

test('retains a recommended player missing from a separately fetched market', () => {
    const recommendation = { player_id: 3, name: 'Player Three', matchup_gain: 0.5 };

    assert.deepEqual(mergeFreeAgentPlayers([], [recommendation]), [recommendation]);
});
