import React, { useEffect, useMemo, useRef, useState } from 'react';
import api from '../api';
import { LEAGUE_CATEGORIES as CATEGORIES } from '../utils/categories';
import { openAppRoute } from '../utils/appRoutes';
import DraftRoom from './DraftRoom';

const errorMessage = error => {
    const detail = error?.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
    return error?.message || 'Мок недоступен';
};

const REVERSE_CATEGORIES = new Set(['TO']);

const categoryTotal = (row, category) => {
    const value = Number(row?.category_totals?.[category]);
    return Number.isFinite(value) ? value : null;
};

const catsTaken = (left, right, categories) => {
    let score = 0;
    let compared = 0;
    categories.forEach(category => {
        let own = categoryTotal(left, category);
        let opponent = categoryTotal(right, category);
        if (own == null || opponent == null) return;
        compared += 1;
        if (REVERSE_CATEGORIES.has(category)) {
            own = -own;
            opponent = -opponent;
        }
        if (own > opponent + 1e-12) score += 1;
        else if (Math.abs(own - opponent) <= 1e-12) score += 0.5;
    });
    return { score, compared };
};

const attachH2h = (standings, categories) => {
    const rows = Array.isArray(standings) ? standings : [];
    if (rows.length < 2) return rows;
    const cats = categories?.length ? categories : CATEGORIES;
    const ranked = rows.map(row => {
        let wins = 0;
        let ties = 0;
        let losses = 0;
        rows.forEach(other => {
            if (other.slot === row.slot) return;
            const { score, compared } = catsTaken(row, other, cats);
            if (!compared) return;
            const midpoint = compared / 2;
            if (Math.abs(score - midpoint) <= 1e-12) ties += 1;
            else if (score > midpoint) wins += 1;
            else losses += 1;
        });
        return { ...row, matchup_wins: wins, matchup_ties: ties, matchup_losses: losses };
    });
    ranked.sort((left, right) => (
        (right.matchup_wins + 0.5 * right.matchup_ties) - (left.matchup_wins + 0.5 * left.matchup_ties)
        || Number(right.category_wins) - Number(left.category_wins)
        || left.slot - right.slot
    ));
    let rank = 1;
    let previous = null;
    return ranked.map((row, index) => {
        const key = `${row.matchup_wins}:${row.matchup_ties}:${row.category_wins}`;
        if (previous != null && key !== previous) rank = index + 1;
        previous = key;
        return { ...row, league_rank: rank };
    });
};

export default function MockDraftPage({ mainTeam, projectedPeriod, leagueId, puntCategories = [], onPlayerClick, onOpenSettings }) {
    const storageKey = `draft-mock-strong:${leagueId}:${mainTeam}:${projectedPeriod}`;
    const puntKey = (puntCategories || []).join(',');
    const [session, setSession] = useState(() => {
        try {
            const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
            if (saved && saved.seed != null) return saved;
        } catch { /* ignore quota / parse */ }
        return { picks: [], seed: Math.floor(Math.random() * 1e9), advisor: 'heuristic' };
    });
    const picks = session?.picks || [];
    const seed = session.seed;
    const advisor = session.advisor === 'v8' ? 'v8' : 'heuristic';
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [viewRound, setViewRound] = useState(null);
    const [inspectedSlot, setInspectedSlot] = useState(null);
    const [showHint, setShowHint] = useState(false);
    const [showSimulation, setShowSimulation] = useState(false);
    const requestId = useRef(0);

    const persist = next => {
        setSession(next);
        try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* ignore quota */ }
    };

    const run = async (nextPicks, nextSeed = seed, recover = true, nextAdvisor = advisor) => {
        if (!mainTeam) return;
        const id = requestId.current + 1;
        requestId.current = id;
        setLoading(true);
        setError('');
        try {
            const response = await api.post(`/draft/mock/${mainTeam}`, {
                picks: nextPicks,
                seed: nextSeed,
                period: projectedPeriod,
                opponent_field: 'strong',
                advisor: nextAdvisor,
                punt_categories: puntCategories,
            });
            if (id !== requestId.current) return;
            setResult(response.data);
            persist({ picks: nextPicks, seed: nextSeed, advisor: nextAdvisor });
            setInspectedSlot(null);
            const reports = response.data.round_reports || [];
            setViewRound(reports.length ? reports[reports.length - 1].round : null);
        } catch (requestError) {
            if (id !== requestId.current || requestError.code === 'ERR_CANCELED') return;
            const message = errorMessage(requestError);
            if (recover && nextPicks.length && /недоступен/i.test(message)) {
                await run([], nextSeed, false, nextAdvisor);
                return;
            }
            setError(message);
        } finally {
            if (id === requestId.current) setLoading(false);
        }
    };

    useEffect(() => {
        run(picks, seed, true, advisor);
        return () => { requestId.current += 1; };
    }, [mainTeam, projectedPeriod, puntKey, advisor]);

    const reports = result?.round_reports || [];
    const selectedReport = reports.find(report => report.round === viewRound) || reports[reports.length - 1];
    const categories = result?.categories || CATEGORIES;
    const standings = useMemo(
        () => attachH2h(result?.status === 'complete' ? result.standings : selectedReport?.standings, categories),
        [result, selectedReport, categories],
    );
    const you = standings.find(row => row.is_you);
    const onClock = result?.status === 'on_the_clock';
    const modelPick = result?.model_pick;
    const yourRoster = (result?.your_roster || you?.roster || []).map(player => ({
        ...player,
        draft_pick: result?.pick_log?.find(pick => pick.is_you && (pick.player?.player_id === player.player_id || pick.player?.name === player.name))?.overall,
    }));
    const inspected = inspectedSlot == null ? null : (standings.find(row => row.slot === inspectedSlot) || (result?.teams || []).find(team => team.slot === inspectedSlot));

    if (!mainTeam) {
        return (
            <div className="rounded border bg-white p-6 text-center">
                <p className="mb-4 text-gray-600">Нужна команда</p>
                <button onClick={onOpenSettings} className="rounded bg-blue-600 px-4 py-2 text-white">Настройки</button>
            </div>
        );
    }

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <button onClick={() => openAppRoute('')} className="text-sm text-blue-700 hover:underline">К основному приложению</button>
                <div className="flex flex-wrap gap-2">
                    <div className="inline-flex rounded-lg border border-gray-300 bg-gray-50 p-1">
                        <button type="button" onClick={() => persist({ picks, seed, advisor: 'heuristic' })} className={`rounded-md px-3 py-1.5 text-sm ${advisor === 'heuristic' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-600'}`}>Эвристика</button>
                        <button type="button" onClick={() => persist({ picks, seed, advisor: 'v8' })} className={`rounded-md px-3 py-1.5 text-sm ${advisor === 'v8' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-600'}`}>V8</button>
                    </div>
                    <button disabled={loading || !picks.length} onClick={() => run(picks.slice(0, -1))} className="rounded border px-3 py-1.5 text-sm disabled:opacity-40">Отменить</button>
                    <button disabled={loading} onClick={() => run([], Math.floor(Math.random() * 1e9), false)} className="rounded border px-3 py-1.5 text-sm disabled:opacity-40">Заново</button>
                </div>
            </div>
            {loading && <div className="text-sm text-gray-500">{result ? 'Ход моделей…' : 'Собираем доску…'}</div>}
            {error && <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
            <DraftRoom
                categories={categories}
                puntCategories={puntCategories}
                onPlayerClick={onPlayerClick}
                roundLabel={result?.round ? `${result.round} / ${result.rounds || '—'}` : '—'}
                clockLabel={onClock ? `Ваш ход · #${result.overall}` : (result?.overall ? `Пик #${result.overall}` : '—')}
                yourPick={result?.planned_picks?.[result?.your_pick_index] || (onClock ? result?.overall : null)}
                picksUntil={onClock ? 0 : null}
                rosterCount={yourRoster.length}
                rosterLimit={result?.rounds}
                rankLabel={you ? `#${you.league_rank} / ${result.team_count}` : '—'}
                recordLabel={you?.matchup_wins == null ? null : `${you.matchup_wins}-${you.matchup_losses}-${you.matchup_ties}`}
                showHint={showHint}
                onToggleHint={() => setShowHint(value => !value)}
                showSimulation={showSimulation}
                onToggleSimulation={() => setShowSimulation(value => !value)}
                hint={modelPick ? {
                    label: result?.advisor_label || 'Взял бы',
                    player: modelPick,
                    name: modelPick.name,
                    position: modelPick.position,
                    z: modelPick.total_z,
                    disabled: loading,
                    onTake: () => run([...picks, modelPick.player_id]),
                } : null}
                players={onClock ? (result?.available || []) : []}
                onDraftPlayer={onClock ? player => run([...picks, player.player_id]) : null}
                highlightedPlayerId={showHint ? modelPick?.player_id : null}
                pickLog={(result?.pick_log || []).map(pick => ({
                    overall: pick.overall,
                    round: pick.round,
                    playerName: pick.player?.name,
                    player: pick.player,
                    teamName: pick.team_name,
                    isYou: pick.is_you,
                }))}
                standingsTitle={result?.status === 'complete' ? 'Лига' : `После раунда ${selectedReport?.round || '—'}`}
                roundOptions={reports.map(report => ({ value: report.round, label: `Раунд ${report.round}` }))}
                viewRound={selectedReport?.round}
                onViewRound={setViewRound}
                standings={standings}
                yourRoster={yourRoster}
                inspected={inspected}
                onInspectTeam={row => setInspectedSlot(row && row.slot !== result?.slot ? row.slot : null)}
                simulationContent={<div className="rounded-xl border bg-white p-6 text-sm text-gray-500">В моке соперники уже доигрывают до вашего хода. Отдельный прогноз здесь не запускается.</div>}
            />
        </div>
    );
}
