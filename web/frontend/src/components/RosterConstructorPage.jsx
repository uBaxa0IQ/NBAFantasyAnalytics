import React, { useEffect, useMemo, useRef, useState } from 'react';
import api from '../api';
import { LEAGUE_CATEGORIES as CATEGORIES } from '../utils/categories';
import { openAppRoute } from '../utils/appRoutes';
import { buildConstructorBoard, evaluateConstructor } from '../utils/constructorEval';

const PERCENT_CATEGORIES = new Set(['FG%', 'FT%', '3PT%']);
const DRAG_TYPE = 'application/x-constructor-player';

const formatStat = (category, value) => {
    if (value == null || Number.isNaN(Number(value))) return '—';
    const number = Number(value);
    if (PERCENT_CATEGORIES.has(category)) return `${(number <= 1 ? number * 100 : number).toFixed(1)}%`;
    if (category === 'A/TO') return number.toFixed(2);
    return Math.round(number).toLocaleString('ru-RU');
};

const formatGoal = (category, goal) => (goal == null ? '—' : `≥${formatStat(category, goal)}`);

const calculateStrategyZ = (player, puntCategories = [], categories = CATEGORIES) => categories.reduce((total, category) => (
    puntCategories.includes(category) ? total : total + Number(player.z_scores?.[category] || 0)
), 0);

const zTextTone = value => {
    const zScore = Number(value || 0);
    if (zScore > 0) return 'text-green-600';
    if (zScore < 0) return 'text-red-600';
    return 'text-gray-400';
};

const bandClass = band => ({
    empty: 'border-gray-200 bg-white text-gray-400',
    building: 'border-slate-200 bg-slate-50 text-slate-700',
    below: 'border-red-200 bg-red-50 text-red-800',
    top3: 'border-amber-200 bg-amber-50 text-amber-900',
    goal: 'border-green-200 bg-green-50 text-green-800',
    first: 'border-emerald-300 bg-emerald-50 text-emerald-900',
    punt: 'border-gray-200 bg-gray-50 text-gray-400',
}[band] || 'border-gray-200 bg-white');

const errorMessage = error => {
    const detail = error?.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
    return error?.message || 'Конструктор недоступен';
};

const padRoster = (ids, rounds) => {
    const next = [...(ids || [])].slice(0, rounds).map(id => (id > 0 ? Number(id) : null));
    while (next.length < rounds) next.push(null);
    return next;
};

const readDrag = event => {
    try {
        return JSON.parse(event.dataTransfer.getData(DRAG_TYPE) || '{}');
    } catch {
        return {};
    }
};

export default function RosterConstructorPage({ mainTeam, projectedPeriod, leagueId, puntCategories = [], onPlayerClick, onOpenSettings }) {
    const storageKey = `draft-constructor:${leagueId}:${mainTeam}:${projectedPeriod}`;
    const puntKey = (puntCategories || []).join(',');
    const [tab, setTab] = useState(() => {
        try {
            const saved = sessionStorage.getItem('constructor-inner-tab');
            return saved === 'players' ? 'players' : 'constructor';
        } catch { return 'constructor'; }
    });
    const [board, setBoard] = useState(null);
    const [evaluation, setEvaluation] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [search, setSearch] = useState('');
    const [position, setPosition] = useState('ALL');
    const [sortBy, setSortBy] = useState('espn_market_pick');
    const [sortDir, setSortDir] = useState('asc');
    const [plan, setPlan] = useState(() => {
        try {
            const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
            if (saved && Array.isArray(saved.favorites)) return { favorites: saved.favorites.map(Number).filter(Boolean), roster: saved.roster || [] };
        } catch { /* ignore */ }
        return { favorites: [], roster: [] };
    });
    const requestId = useRef(0);

    const persist = next => {
        setPlan(next);
        try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* ignore quota */ }
    };
    const selectTab = next => {
        setTab(next);
        try { sessionStorage.setItem('constructor-inner-tab', next); } catch { /* ignore */ }
    };

    const rounds = board?.rounds || plan.roster.length || 13;
    const roster = padRoster(plan.roster, rounds);
    const favorites = plan.favorites;
    const categories = board?.categories || CATEGORIES;
    const picks = board?.picks || [];
    const playersById = useMemo(() => Object.fromEntries((board?.players || []).map(player => [Number(player.player_id), player])), [board]);

    useEffect(() => {
        if (!mainTeam) return undefined;
        const id = requestId.current + 1;
        requestId.current = id;
        setLoading(true);
        setError('');
        Promise.all([
            api.get(`/draft/recommendations/${mainTeam}`, {
                params: { period: projectedPeriod, limit: 300, trigger: 'upcoming' },
            }),
            api.get('/draft/state'),
        ])
            .then(([recommendations, draftState]) => {
                if (id !== requestId.current) return;
                setBoard(buildConstructorBoard(recommendations.data, draftState.data, mainTeam));
            })
            .catch(requestError => {
                if (id !== requestId.current) return;
                setError(errorMessage(requestError));
            })
            .finally(() => {
                if (id === requestId.current) setLoading(false);
            });
        return () => { requestId.current += 1; };
    }, [mainTeam, projectedPeriod]);

    useEffect(() => {
        if (!board) return;
        setEvaluation(evaluateConstructor({
            players: board.players,
            rosterIds: roster,
            picks: board.picks,
            categories,
            puntCategories,
        }));
    }, [board, roster.join(','), puntKey, categories]);

    const setRoster = next => persist({ favorites, roster: padRoster(next, rounds) });
    const toggleFavorite = playerId => {
        const id = Number(playerId);
        if (!id) return;
        persist({
            roster,
            favorites: favorites.includes(id) ? favorites.filter(item => item !== id) : [...favorites, id],
        });
    };
    const placePlayer = (playerId, slotIndex) => {
        const id = Number(playerId);
        if (!id) return;
        const next = padRoster(roster, rounds);
        const currentIndex = next.indexOf(id);
        if (currentIndex === slotIndex) return;
        if (currentIndex >= 0) next[currentIndex] = next[slotIndex] ?? null;
        next[slotIndex] = id;
        persist({
            roster: next,
            favorites: favorites.includes(id) ? favorites : [...favorites, id],
        });
    };
    const addToFirstEmpty = playerId => {
        const empty = roster.findIndex(id => !id);
        if (empty < 0) return;
        placePlayer(playerId, empty);
    };
    const clearSlot = slotIndex => {
        const next = padRoster(roster, rounds);
        next[slotIndex] = null;
        setRoster(next);
    };

    const handleSort = column => {
        if (sortBy === column) setSortDir(current => current === 'asc' ? 'desc' : 'asc');
        else {
            setSortBy(column);
            setSortDir(column === 'name' ? 'asc' : 'desc');
        }
    };
    const SortIcon = ({ column }) => <span className="ml-1 text-gray-400">{sortBy === column ? (sortDir === 'asc' ? '↑' : '↓') : '⇅'}</span>;

    const visiblePlayers = useMemo(() => {
        const filtered = (board?.players || []).filter(player => {
            const matchesPosition = position === 'ALL' || String(player.position || '').includes(position);
            const matchesSearch = !search || String(player.name || '').toLowerCase().includes(search.toLowerCase());
            return matchesPosition && matchesSearch;
        });
        return [...filtered].sort((left, right) => {
            if (sortBy === 'name') {
                return sortDir === 'asc' ? left.name.localeCompare(right.name) : right.name.localeCompare(left.name);
            }
            const read = player => {
                if (sortBy === 'total_z') return calculateStrategyZ(player, puntCategories, categories);
                if (sortBy === 'espn_market_pick') return Number(player.espn_market_pick || 999);
                return Number(player.z_scores?.[sortBy] || 0);
            };
            return sortDir === 'asc' ? read(left) - read(right) : read(right) - read(left);
        });
    }, [board, position, search, sortBy, sortDir, puntCategories, categories]);

    const favoritePlayers = favorites.map(id => playersById[id]).filter(Boolean).filter(player => !roster.includes(Number(player.player_id)));
    const assembly = evaluation?.assembly;
    const workingInGoal = evaluation?.working_in_goal ?? 0;
    const workingCount = evaluation?.working_count ?? 7;

    const onDragStart = (event, playerId, fromSlot) => {
        event.dataTransfer.setData(DRAG_TYPE, JSON.stringify({ playerId, fromSlot }));
        event.dataTransfer.effectAllowed = 'move';
    };
    const onDropSlot = (event, slotIndex) => {
        event.preventDefault();
        const payload = readDrag(event);
        if (payload.playerId) placePlayer(payload.playerId, slotIndex);
    };

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
                <button onClick={() => openAppRoute('')} className="text-sm text-blue-700 hover:underline">К основному приложению</button>
                <div className="flex flex-wrap gap-2">
                    <div className="inline-flex rounded-lg border border-gray-300 bg-gray-50 p-1">
                        <button type="button" onClick={() => selectTab('constructor')} className={`rounded-md px-3 py-1.5 text-sm ${tab === 'constructor' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-600'}`}>Конструктор</button>
                        <button type="button" onClick={() => selectTab('players')} className={`rounded-md px-3 py-1.5 text-sm ${tab === 'players' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-600'}`}>Игроки</button>
                        <button type="button" onClick={() => openAppRoute('mock')} className="rounded-md px-3 py-1.5 text-sm text-gray-600">Мок</button>
                    </div>
                    <button onClick={onOpenSettings} className="rounded border px-3 py-1.5 text-sm">Настройки</button>
                </div>
            </section>

            <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <div className="rounded-xl border bg-white p-4"><div className="text-xs text-gray-500">Состав</div><div className="mt-1 text-2xl font-bold">{roster.filter(Boolean).length} / {rounds}</div></div>
                <div className="rounded-xl border bg-white p-4"><div className="text-xs text-gray-500">Цели</div><div className="mt-1 text-2xl font-bold">{workingInGoal} / {workingCount}</div></div>
                <div className="rounded-xl border bg-white p-4"><div className="text-xs text-gray-500">Сбор 13</div><div className="mt-1 text-2xl font-bold">{assembly?.full_rate == null ? '—' : `${assembly.full_rate}%`}</div></div>
                <div className="rounded-xl border bg-white p-4"><div className="text-xs text-gray-500">Ядро</div><div className="mt-1 text-2xl font-bold">{assembly?.core_rate == null ? '—' : `${assembly.core_rate}%`}</div><div className="text-xs text-gray-400">рынок ≤ пик+{8}</div></div>
            </section>
            {loading && <div className="text-sm text-gray-500">Собираем пул игроков…</div>}
            {error && <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}

            {tab === 'constructor' && (
                <>
                    <section className="flex flex-wrap justify-center gap-2">
                        {(evaluation?.categories || categories.map(category => ({ category, band: 'empty' }))).map(row => (
                            <div key={row.category} className={`min-w-28 flex-1 rounded-lg border p-3 ${bandClass(row.band)} ${puntCategories.includes(row.category) ? 'opacity-60' : ''}`}>
                                <div className="text-xs opacity-70">{row.category}{row.working ? '' : row.band === 'punt' ? ' · пант' : ''}</div>
                                <div className="text-lg font-bold">{formatStat(row.category, row.value)}</div>
                                {row.working && <div className="text-xs opacity-70">цель {formatGoal(row.category, row.goal)}</div>}
                            </div>
                        ))}
                    </section>

                    <div className="grid gap-4 xl:grid-cols-2">
                        <section className="flex max-h-[40rem] flex-col overflow-hidden rounded-xl border bg-white xl:h-0 xl:max-h-none xl:min-h-full">
                            <div className="shrink-0 border-b p-3 font-bold">Избранное · {favoritePlayers.length}</div>
                            <div className="min-h-0 flex-1 divide-y overflow-y-auto">
                                {!favoritePlayers.length && <div className="p-4 text-sm text-gray-500">На вкладке «Игроки» отметь звёздочкой. Отсюда перетаскивай в слот или нажми «В состав».</div>}
                                {favoritePlayers.map(player => (
                                    <div
                                        key={player.player_id}
                                        draggable
                                        onDragStart={event => onDragStart(event, player.player_id, null)}
                                        className="flex items-center justify-between gap-3 p-3 text-sm"
                                    >
                                        <div>
                                            <button onClick={() => onPlayerClick?.(player)} className="font-medium text-blue-600 hover:underline">{player.name}</button>
                                            <div className="text-xs text-gray-400">{player.position} · пик {player.espn_market_pick?.toFixed?.(1) || '—'}</div>
                                        </div>
                                        <div className="flex gap-2">
                                            <button onClick={() => addToFirstEmpty(player.player_id)} className="rounded border px-2 py-1 text-xs">В состав</button>
                                            <button onClick={() => toggleFavorite(player.player_id)} className="text-xs text-gray-500">×</button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </section>
                        <section className="flex min-h-0 flex-col overflow-hidden rounded-xl border bg-white">
                            <div className="flex shrink-0 items-center justify-between border-b p-3">
                                <h2 className="font-bold">Состав{board?.slot ? ` · слот ${board.slot}` : ''}</h2>
                                <button onClick={() => setRoster([])} className="text-sm text-red-700 hover:underline">Очистить</button>
                            </div>
                            <div className="divide-y">
                                {roster.map((playerId, index) => {
                                    const player = playersById[playerId];
                                    const slotInfo = assembly?.slots?.[index];
                                    return (
                                        <div
                                            key={picks[index] || index}
                                            onDragOver={event => event.preventDefault()}
                                            onDrop={event => onDropSlot(event, index)}
                                            className={`flex min-h-16 items-center justify-between gap-3 p-3 ${player ? 'bg-white' : 'bg-slate-50'}`}
                                        >
                                            <div className="w-20 shrink-0 text-xs font-semibold text-gray-400">#{picks[index] || index + 1} · {index + 1}</div>
                                            {player ? (
                                                <div
                                                    draggable
                                                    onDragStart={event => onDragStart(event, player.player_id, index)}
                                                    className="min-w-0 flex-1 cursor-grab"
                                                >
                                                    <button onClick={() => onPlayerClick?.(player)} className="font-medium text-blue-600 hover:underline">{player.name}</button>
                                                    <div className="text-xs text-gray-400">{player.position} · рынок {player.espn_market_pick?.toFixed?.(1) || '—'}</div>
                                                </div>
                                            ) : (
                                                <div className="flex-1 text-sm text-gray-400">Перетащи из избранного</div>
                                            )}
                                            <div className="w-16 text-right text-sm font-bold">
                                                {slotInfo?.available == null ? '' : `${slotInfo.available}%`}
                                            </div>
                                            {player && <button onClick={() => clearSlot(index)} className="text-xs text-gray-500">×</button>}
                                        </div>
                                    );
                                })}
                            </div>
                        </section>
                    </div>
                </>
            )}

            {tab === 'players' && (
                <section className="overflow-hidden rounded-xl border bg-white">
                    <div className="flex flex-col gap-3 border-b p-3 sm:flex-row sm:items-center sm:justify-between">
                        <div className="text-sm text-gray-500">Звезда — в избранное конструктора</div>
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
                            <th onClick={() => handleSort('total_z')} className="cursor-pointer border p-2">{puntCategories.length ? 'Z стратегии' : 'Total Z'}<SortIcon column="total_z" /></th>
                            {categories.map(category => <th key={category} onClick={() => handleSort(category)} className={`cursor-pointer border p-2 ${puntCategories.includes(category) ? 'opacity-50' : ''}`}>{category}<SortIcon column={category} /></th>)}
                        </tr></thead>
                        <tbody>{visiblePlayers.slice(0, 200).map(player => {
                            const starred = favorites.includes(Number(player.player_id));
                            const strategyZ = calculateStrategyZ(player, puntCategories, categories);
                            return (
                                <tr key={player.player_id || player.name} className={`hover:bg-gray-50 ${starred ? 'bg-amber-50' : ''}`}>
                                    <td className="border p-2 text-center">
                                        <button onClick={() => toggleFavorite(player.player_id)} className={starred ? 'text-amber-500' : 'text-gray-300'} aria-label={starred ? 'Убрать из избранного' : 'В избранное'}>{starred ? '★' : '☆'}</button>
                                    </td>
                                    <td className="border p-2"><button onClick={() => onPlayerClick?.(player)} className="font-medium text-blue-600 hover:underline">{player.name}</button></td>
                                    <td className="border p-2 text-center">{player.position}</td>
                                    <td className="border p-2 text-center">{player.espn_market_pick?.toFixed?.(1) || '—'}</td>
                                    <td className={`border p-2 text-center font-bold ${zTextTone(strategyZ)}`}>{strategyZ.toFixed(2)}</td>
                                    {categories.map(category => (
                                        <td key={category} className={`border p-2 text-center ${zTextTone(player.z_scores?.[category])} ${puntCategories.includes(category) ? 'opacity-30' : ''}`}>{Number(player.z_scores?.[category] || 0).toFixed(2)}</td>
                                    ))}
                                </tr>
                            );
                        })}</tbody>
                    </table></div>
                </section>
            )}
        </div>
    );
}
