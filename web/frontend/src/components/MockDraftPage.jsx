import React, { useEffect, useMemo, useRef, useState } from 'react';
import api from '../api';
import { LEAGUE_CATEGORIES as CATEGORIES } from '../utils/categories';

const formatStat = (category, value) => {
    if (value == null || Number.isNaN(Number(value))) return '—';
    const number = Number(value);
    if (['FG%', 'FT%', '3PT%'].includes(category)) return `${(number <= 1 ? number * 100 : number).toFixed(1)}%`;
    return number.toFixed(category === 'A/TO' ? 2 : 1);
};

const calculateStrategyZ = (player, puntCategories = [], categories = CATEGORIES) => categories.reduce((total, category) => (
    puntCategories.includes(category) ? total : total + Number(player.z_scores?.[category] || 0)
), 0);

const zTextTone = value => {
    const zScore = Number(value || 0);
    if (zScore > 0) return 'text-green-600';
    if (zScore < 0) return 'text-red-600';
    return 'text-gray-400';
};

const errorMessage = error => {
    const detail = error?.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
    return error?.message || 'Мок недоступен';
};

const leaveMock = () => {
    if (window.location.hash === '#/mock') {
        window.location.hash = '';
        return;
    }
    window.history.pushState({}, '', '/');
    window.dispatchEvent(new PopStateEvent('popstate'));
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
    const [search, setSearch] = useState('');
    const [position, setPosition] = useState('ALL');
    const [playersView, setPlayersView] = useState('draft');
    const [sortBy, setSortBy] = useState('total_z');
    const [sortDir, setSortDir] = useState('desc');
    const [inspectedSlot, setInspectedSlot] = useState(null);
    const [viewRound, setViewRound] = useState(null);
    const [picksExpanded, setPicksExpanded] = useState(false);
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
            setInspectedSlot(response.data.slot);
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

    const handleSort = column => {
        if (sortBy === column) setSortDir(current => current === 'asc' ? 'desc' : 'asc');
        else {
            setSortBy(column);
            setSortDir(column === 'name' ? 'asc' : 'desc');
        }
    };
    const SortIcon = ({ column }) => <span className="ml-1 text-gray-400">{sortBy === column ? (sortDir === 'asc' ? '↑' : '↓') : '⇅'}</span>;

    const visibleBoard = useMemo(() => {
        const filtered = (result?.available || []).filter(player => {
            const matchesPosition = position === 'ALL' || String(player.position || '').includes(position);
            const matchesSearch = !search || String(player.name || '').toLowerCase().includes(search.toLowerCase());
            return matchesPosition && matchesSearch;
        });
        return [...filtered].sort((left, right) => {
            if (sortBy === 'name') {
                return sortDir === 'asc' ? left.name.localeCompare(right.name) : right.name.localeCompare(left.name);
            }
            const read = player => {
                if (sortBy === 'total_z') return calculateStrategyZ(player, puntCategories, CATEGORIES);
                if (sortBy === 'espn_market_pick') return Number(player.espn_market_pick || 999);
                if (playersView === 'stats') return Number(player.stats?.[sortBy] || 0);
                return Number(player.z_scores?.[sortBy] || 0);
            };
            const delta = read(left) - read(right);
            return sortDir === 'asc' ? delta : -delta;
        });
    }, [result?.available, position, search, sortBy, sortDir, playersView, puntCategories]);

    const inspected = (result?.teams || []).find(team => team.slot === inspectedSlot) || (result?.teams || []).find(team => team.is_you);
    const reports = result?.round_reports || [];
    const selectedReport = reports.find(report => report.round === viewRound) || reports[reports.length - 1];
    const standings = result?.status === 'complete' ? result.standings : selectedReport?.standings;
    const you = (standings || []).find(row => row.is_you);
    const pickLog = result?.pick_log || [];
    const recent = [...pickLog].slice(-8).reverse();
    const picksByRound = useMemo(() => {
        const rounds = [];
        pickLog.forEach(pick => {
            const round = pick.round || 1;
            const last = rounds[rounds.length - 1];
            if (!last || last.round !== round) rounds.push({ round, picks: [pick] });
            else last.picks.push(pick);
        });
        return rounds;
    }, [pickLog]);
    const onClock = result?.status === 'on_the_clock';
    const complete = result?.status === 'complete';
    const modelPick = result?.model_pick;
    const categories = result?.categories || CATEGORIES;

    const pickValue = (player, category) => (
        playersView === 'stats' ? formatStat(category, player.stats?.[category]) : Number(player.z_scores?.[category] || 0).toFixed(2)
    );
    const pickTone = (player, category) => zTextTone(player.z_scores?.[category]);

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
            <section className="flex flex-wrap items-center justify-between gap-3">
                <button onClick={leaveMock} className="text-sm text-blue-700 hover:underline">К основному приложению</button>
                <div className="flex flex-wrap gap-2">
                    <div className="inline-flex rounded-lg border border-gray-300 bg-gray-50 p-1">
                        <button type="button" onClick={() => persist({ picks, seed, advisor: 'heuristic' })} className={`rounded-md px-3 py-1.5 text-sm ${advisor === 'heuristic' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-600'}`}>Эвристика</button>
                        <button type="button" onClick={() => persist({ picks, seed, advisor: 'v8' })} className={`rounded-md px-3 py-1.5 text-sm ${advisor === 'v8' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-600'}`}>V8</button>
                    </div>
                    <button disabled={loading || !picks.length} onClick={() => run(picks.slice(0, -1))} className="rounded border px-3 py-1.5 text-sm disabled:opacity-40">Отменить</button>
                    <button disabled={loading} onClick={() => run([], Math.floor(Math.random() * 1e9), false)} className="rounded border px-3 py-1.5 text-sm disabled:opacity-40">Заново</button>
                    <button onClick={onOpenSettings} className="rounded border px-3 py-1.5 text-sm">Настройки</button>
                </div>
            </section>

            <section className="grid grid-cols-2 gap-3 lg:grid-cols-5">
                <div className="rounded-xl border bg-white p-4"><div className="text-xs text-gray-500">Пик</div><div className="mt-1 text-2xl font-bold">{result?.overall ? `#${result.overall}` : '—'}</div></div>
                <div className="rounded-xl border bg-white p-4"><div className="text-xs text-gray-500">Раунд</div><div className="mt-1 text-2xl font-bold">{result?.round ? `${result.round} / ${result?.rounds || '—'}` : '—'}</div></div>
                <div className="rounded-xl border bg-white p-4"><div className="text-xs text-gray-500">Состав</div><div className="mt-1 text-2xl font-bold">{result?.your_roster?.length || 0} / {result?.rounds || '—'}</div></div>
                <div className="rounded-xl border bg-white p-4"><div className="text-xs text-gray-500">Место</div><div className="mt-1 text-2xl font-bold">{you ? `#${you.league_rank} / ${result.team_count}` : '—'}</div></div>
                <div className="rounded-xl border bg-white p-4"><div className="text-xs text-gray-500">Категории</div><div className="mt-1 text-2xl font-bold">{you ? `${you.category_wins.toFixed(2)} / ${categories.length}` : '—'}</div></div>
            </section>
            {loading && <div className="text-sm text-gray-500">{result ? 'Ход моделей…' : 'Собираем доску…'}</div>}
            {error && <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}

            {onClock && modelPick && (
                <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-blue-200 bg-blue-50 p-4">
                    <div>
                        <div className="text-xs font-medium uppercase tracking-wide text-blue-700">{result?.advisor_label || (advisor === 'v8' ? 'Нейросеть V8' : 'Эвристика')} взяла бы</div>
                        <button onClick={() => onPlayerClick?.(modelPick)} className="mt-1 text-lg font-bold text-blue-800 hover:underline">{modelPick.name}</button>
                        <div className="text-xs text-blue-700">{modelPick.position} · Z {calculateStrategyZ(modelPick, puntCategories, categories).toFixed(2)}</div>
                    </div>
                    <button disabled={loading} onClick={() => run([...picks, modelPick.player_id])} className="rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">Взять</button>
                </section>
            )}

            {!!pickLog.length && <section className="overflow-hidden rounded-xl border bg-white">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b p-3">
                    <h2 className="font-bold">{picksExpanded ? 'Все пики' : 'Последние пики'}</h2>
                    {pickLog.length > 8 && (
                        <button type="button" onClick={() => setPicksExpanded(open => !open)} className="text-sm text-blue-700 hover:underline">
                            {picksExpanded ? 'Свернуть' : `Показать все · ${pickLog.length}`}
                        </button>
                    )}
                </div>
                {picksExpanded ? (
                    <div className="max-h-[32rem] overflow-y-auto">
                        {picksByRound.map(group => (
                            <div key={group.round} className="border-b last:border-b-0">
                                <div className="sticky top-0 bg-gray-50 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">Раунд {group.round}</div>
                                <div className="grid sm:grid-cols-2 lg:grid-cols-4">
                                    {group.picks.map(pick => (
                                        <div key={pick.overall} className={`border-b p-3 text-sm sm:border-r ${pick.is_you ? 'bg-blue-50' : ''}`}>
                                            <span className="mr-2 text-gray-400">#{pick.overall}</span>
                                            <button onClick={() => onPlayerClick?.(pick.player)} className="font-medium hover:text-blue-700">{pick.player.name}</button>
                                            <div className="ml-8 text-xs text-gray-400">{pick.team_name} · {pick.policy_label}</div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        ))}
                    </div>
                ) : (
                    <div className="grid sm:grid-cols-2 lg:grid-cols-4">{recent.map(pick => (
                        <div key={pick.overall} className={`border-b p-3 text-sm sm:border-r ${pick.is_you ? 'bg-blue-50' : ''}`}>
                            <span className="mr-2 text-gray-400">#{pick.overall}</span>
                            <button onClick={() => onPlayerClick?.(pick.player)} className="font-medium hover:text-blue-700">{pick.player.name}</button>
                            <div className="ml-8 text-xs text-gray-400">{pick.team_name} · {pick.policy_label}</div>
                        </div>
                    ))}</div>
                )}
            </section>}

            {onClock && <section className="overflow-hidden rounded-xl border bg-white">
                <div className="flex flex-col gap-3 border-b p-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="inline-flex rounded-lg border border-gray-300 bg-gray-50 p-1">
                        <button onClick={() => { setPlayersView('stats'); setSortBy('total_z'); }} className={`rounded-md px-3 py-1.5 text-sm ${playersView === 'stats' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-600'}`}>Статы</button>
                        <button onClick={() => { setPlayersView('draft'); setSortBy('total_z'); }} className={`rounded-md px-3 py-1.5 text-sm ${playersView === 'draft' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-600'}`}>Z</button>
                    </div>
                    <div className="flex min-w-0 flex-1 gap-2 sm:justify-end">
                        <select value={position} onChange={event => setPosition(event.target.value)} className="rounded border p-2 text-sm"><option value="ALL">Все позиции</option>{['PG', 'SG', 'SF', 'PF', 'C'].map(item => <option key={item} value={item}>{item}</option>)}</select>
                        <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Поиск" className="min-w-0 flex-1 rounded border p-2 text-sm sm:max-w-sm" />
                    </div>
                </div>
                <div className="overflow-x-auto"><table className="min-w-full border-collapse text-sm">
                    <thead><tr className="bg-gray-100">
                        <th className="border p-2"></th>
                        <th onClick={() => handleSort('name')} className="cursor-pointer border p-2 text-left">Игрок<SortIcon column="name" /></th>
                        <th className="border p-2">Поз.</th>
                        <th onClick={() => handleSort('espn_market_pick')} className="cursor-pointer border p-2">Рынок<SortIcon column="espn_market_pick" /></th>
                        <th onClick={() => handleSort('total_z')} className="cursor-pointer border p-2 hover:bg-gray-200">{puntCategories.length ? 'Z стратегии' : 'Total Z'}<SortIcon column="total_z" /></th>
                        {categories.map(category => <th key={category} onClick={() => handleSort(category)} className={`cursor-pointer border p-2 hover:bg-gray-200 ${puntCategories.includes(category) ? 'opacity-50' : ''}`}>{category}<SortIcon column={category} /></th>)}
                    </tr></thead>
                    <tbody>{visibleBoard.slice(0, 120).map(player => {
                        const strategyZ = calculateStrategyZ(player, puntCategories, categories);
                        const generalZ = calculateStrategyZ(player, [], categories);
                        return (
                        <tr key={player.player_id || player.name} className={`hover:bg-gray-50 ${modelPick?.player_id === player.player_id ? 'bg-blue-50' : ''}`}>
                            <td className="border p-2"><button disabled={loading} onClick={() => run([...picks, player.player_id])} className="rounded border px-2 py-1 text-xs disabled:opacity-40">Взять</button></td>
                            <td className="border p-2"><button onClick={() => onPlayerClick?.(player)} className="font-medium text-blue-600 hover:underline">{player.name}</button></td>
                            <td className="border p-2 text-center">{player.position}</td>
                            <td className="border p-2 text-center">{player.espn_market_pick?.toFixed?.(1) || '—'}</td>
                            <td className={`border p-2 text-center font-bold ${zTextTone(strategyZ)}`}>{strategyZ.toFixed(2)}{puntCategories.length > 0 && <div className="text-xs font-normal text-gray-400">общий {generalZ.toFixed(2)}</div>}</td>
                            {categories.map(category => (
                                <td key={category} className={`border p-2 text-center ${pickTone(player, category)} ${puntCategories.includes(category) ? 'opacity-30' : ''}`}>{pickValue(player, category)}</td>
                            ))}
                        </tr>
                        );
                    })}</tbody>
                </table></div>
            </section>}

            {!!reports.length && standings && <section className="overflow-hidden rounded-xl border bg-white">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b p-3">
                    <h2 className="font-bold">{complete ? 'Лига' : `После раунда ${selectedReport?.round}`}</h2>
                    {reports.length > 1 && <select value={viewRound || ''} onChange={event => setViewRound(Number(event.target.value))} className="rounded border p-1.5 text-sm">
                        {reports.map(report => <option key={report.round} value={report.round}>Раунд {report.round}</option>)}
                    </select>}
                </div>
                {you && <div className="flex flex-wrap justify-center gap-2 border-b p-3">{categories.map(category => {
                    const rank = you.category_ranks?.[category];
                    const total = you.category_totals?.[category];
                    return <div key={category} className={`min-w-28 flex-1 rounded-lg border p-3 ${puntCategories.includes(category) ? 'opacity-60' : ''}`}>
                        <div className="text-xs text-gray-500">{category} · #{rank ?? '—'}</div>
                        <div className={`text-lg font-bold ${rank <= 6 ? 'text-green-600' : rank >= 10 ? 'text-red-600' : 'text-gray-700'}`}>{formatStat(category, total)}</div>
                    </div>;
                })}</div>}
                <div className="overflow-x-auto"><table className="min-w-full text-sm">
                    <thead><tr className="bg-gray-100">
                        <th className="border p-2">#</th><th className="border p-2 text-left">Команда</th><th className="border p-2">Политика</th><th className="border p-2">Победы</th>
                        {categories.map(category => <th key={category} className="border p-2">{category}</th>)}
                    </tr></thead>
                    <tbody>{standings.map(row => (
                        <tr key={row.slot} onClick={() => setInspectedSlot(row.slot)} className={`cursor-pointer ${row.is_you ? 'bg-blue-50' : inspectedSlot === row.slot ? 'bg-gray-50' : 'hover:bg-gray-50'}`}>
                            <td className="border p-2 text-center font-bold">{row.league_rank}</td>
                            <td className="border p-2">{row.team_name}{row.is_you ? ' · вы' : ''} · слот {row.slot}</td>
                            <td className="border p-2 text-center text-xs">{row.policy_label}</td>
                            <td className="border p-2 text-center font-bold">{row.category_wins.toFixed(2)}</td>
                            {categories.map(category => {
                                const rank = row.category_ranks?.[category];
                                return <td key={category} className={`border p-2 text-center ${rank <= 6 ? 'text-green-700' : rank >= 10 ? 'text-red-700' : ''}`}>#{rank}</td>;
                            })}
                        </tr>
                    ))}</tbody>
                </table></div>
            </section>}

            {inspected && <section className="overflow-hidden rounded-xl border bg-white">
                <div className="border-b p-3 font-bold">{inspected.team_name} · {inspected.policy_label}</div>
                <div className="divide-y">{inspected.roster.map((player, index) => (
                    <div key={player.player_id || player.name} className="flex items-center justify-between gap-3 p-3 text-sm">
                        <div>
                            <span className="mr-2 text-gray-400">{index + 1}</span>
                            <button onClick={() => onPlayerClick?.(player)} className="font-medium text-blue-600 hover:underline">{player.name}</button>
                            <div className="ml-6 text-xs text-gray-400">{player.position}</div>
                        </div>
                        <div className={calculateStrategyZ(player, puntCategories, categories) >= 0 ? 'font-bold text-green-600' : 'font-bold text-red-600'}>{calculateStrategyZ(player, puntCategories, categories).toFixed(1)}</div>
                    </div>
                ))}</div>
            </section>}
        </div>
    );
}
