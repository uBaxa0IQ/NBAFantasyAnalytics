import React, { useEffect, useMemo, useRef, useState } from 'react';
import api from '../api';
import { LEAGUE_CATEGORIES as CATEGORIES } from '../utils/categories';
const recommendationsCache = new Map();
const CACHE_TTL = 5 * 60 * 1000;

const formatStat = (category, value) => {
    if (value == null || Number.isNaN(Number(value))) return '—';
    const number = Number(value);
    if (['FG%', 'FT%', '3PT%'].includes(category)) return `${(number <= 1 ? number * 100 : number).toFixed(1)}%`;
    return number.toFixed(category === 'A/TO' ? 2 : 1);
};

const zScoreTone = value => {
    const zScore = Number(value || 0);
    if (zScore >= 1) return 'bg-green-100 text-green-800';
    if (zScore >= 0.35) return 'bg-green-50 text-green-700';
    if (zScore <= -1) return 'bg-red-100 text-red-800';
    if (zScore <= -0.35) return 'bg-red-50 text-red-700';
    return 'text-gray-600';
};

const balancedCategoryCardStyle = count => {
    const columns = count <= 6 ? Math.max(1, count) : Math.min(6, Math.ceil(count / 2));
    const width = `calc(${100 / columns}% - 0.5rem)`;
    return { flex: `1 1 ${width}`, maxWidth: width, minWidth: '140px' };
};

const draftPrice = player => {
    if (!player || player.adp_value == null) return { label: '—', tone: 'text-gray-500' };
    if (player.price_type === 'value') return { label: `Value +${player.adp_value.toFixed(1)}`, tone: 'text-green-600' };
    if (player.price_type === 'turn_window') return { label: 'Брать сейчас', tone: 'text-blue-600' };
    if (player.price_type === 'market') return { label: 'По ADP', tone: 'text-gray-500' };
    return { label: `Reach ${Math.abs(player.adp_value).toFixed(1)}`, tone: 'text-red-600' };
};

const MetricCard = ({ label, value, hint, tone = 'text-gray-900' }) => (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</div>
        <div className={`mt-1 text-2xl font-bold ${tone}`}>{value}</div>
        {hint && <div className="mt-1 text-xs text-gray-400">{hint}</div>}
    </div>
);

const DraftAssistant = ({ draftState, mainTeam, puntCategories = [], projectedPeriod, onOpenSettings, onPlayerClick }) => {
    const [activeTab, setActiveTab] = useState('draft');
    const [playersView, setPlayersView] = useState('draft');
    const [recommendations, setRecommendations] = useState(null);
    const [recommendationsLoading, setRecommendationsLoading] = useState(false);
    const recommendationContextRef = useRef(null);
    const [error, setError] = useState(null);
    const [search, setSearch] = useState('');
    const [position, setPosition] = useState('ALL');
    const [sortBy, setSortBy] = useState('total_z');
    const [sortDir, setSortDir] = useState('desc');
    const [simulationSlot, setSimulationSlot] = useState(1);
    const [detailedSimulations, setDetailedSimulations] = useState({});
    const [simulationLoading, setSimulationLoading] = useState(false);
    const lastGoodDraftRef = useRef(null);
    const [modeOverride, setModeOverride] = useState(null);
    const [modeSwitching, setModeSwitching] = useState(false);
    const [modeError, setModeError] = useState(null);

    const isUpcoming = draftState?.status === 'upcoming';
    const isLive = draftState?.status === 'live';
    const isPostDraft = draftState?.postdraft;
    const effectiveDraftMode = modeOverride || draftState?.draft_connection_mode || 'espn';
    const analyticsDraftMode = effectiveDraftMode === 'analytics';
    const officialDraftMode = isLive && !analyticsDraftMode;
    if (draftState && (draftState.live_snapshot_available || (draftState.pick_count || 0) > 0)) {
        lastGoodDraftRef.current = draftState;
    }
    const snapshotMissing = !(draftState?.live_snapshot_available || (draftState?.pick_count || 0) > 0);
    const viewState = officialDraftMode && snapshotMissing && lastGoodDraftRef.current
        ? lastGoodDraftRef.current
        : draftState;
    const pickCount = viewState?.pick_count;
    const hasLiveSnapshot = Boolean(viewState?.live_snapshot_available || pickCount);
    const waitingForFirstLiveSnapshot = isLive && analyticsDraftMode && !draftState?.live_source && !hasLiveSnapshot;
    const refreshingLiveSnapshot = isLive && analyticsDraftMode && !draftState?.live_source && hasLiveSnapshot;
    const snapshotTime = viewState?.live_updated_at
        ? new Date(Number(viewState.live_updated_at) * 1000).toLocaleTimeString('ru-RU')
        : null;
    const teamCount = Math.max(1, viewState?.team_count || 1);

    useEffect(() => {
        if (recommendations?.simulation?.mode === 'known_order') setSimulationSlot(recommendations.simulation.slot);
    }, [recommendations]);

    useEffect(() => {
        if (modeOverride && draftState?.draft_connection_mode === modeOverride) setModeOverride(null);
    }, [draftState?.draft_connection_mode, modeOverride]);

    useEffect(() => {
        if (!mainTeam || pickCount === undefined) return;
        let active = true;
        setDetailedSimulations({});
        setError(null);
        const contextKey = [mainTeam, projectedPeriod, puntCategories.join(',')].join('|');
        if (recommendationContextRef.current !== contextKey) {
            recommendationContextRef.current = contextKey;
            setRecommendations(null);
        }
        setRecommendationsLoading(true);
        const cacheKey = [mainTeam, projectedPeriod, puntCategories.join(','), pickCount].join('|');
        const cached = recommendationsCache.get(cacheKey);
        if (cached && Date.now() - cached.savedAt < CACHE_TTL) {
            setRecommendations(cached.data);
            setRecommendationsLoading(false);
            return () => { active = false; };
        }
        api.get(`/draft/recommendations/${mainTeam}`, {
            params: { period: projectedPeriod, punt_categories: puntCategories.join(','), limit: 300 },
        })
            .then(response => {
                if (!active) return;
                recommendationsCache.set(cacheKey, { data: response.data, savedAt: Date.now() });
                if (recommendationsCache.size > 8) recommendationsCache.delete(recommendationsCache.keys().next().value);
                setRecommendations(response.data);
            })
            .catch(requestError => active && setError(requestError.response?.data?.detail || 'Не удалось загрузить данные драфта'))
            .finally(() => active && setRecommendationsLoading(false));
        return () => { active = false; };
    }, [mainTeam, puntCategories, pickCount, projectedPeriod]);

    useEffect(() => {
        if (activeTab !== 'simulation' || !mainTeam || recommendations?.simulation?.mode !== 'all_slots' || detailedSimulations[simulationSlot]) return;
        let active = true;
        setSimulationLoading(true);
        api.get(`/draft/recommendations/${mainTeam}`, {
            params: { period: projectedPeriod, punt_categories: puntCategories.join(','), simulation_slot: simulationSlot, limit: 300 },
        })
            .then(response => active && setDetailedSimulations(current => ({ ...current, [simulationSlot]: response.data.simulation })))
            .catch(requestError => active && setError(requestError.response?.data?.detail || 'Не удалось уточнить симуляцию'))
            .finally(() => active && setSimulationLoading(false));
        return () => { active = false; };
    }, [activeTab, mainTeam, recommendations, simulationSlot, detailedSimulations, projectedPeriod, puntCategories]);

    const draftedIds = useMemo(() => new Set(
        (viewState?.picks || []).map(pick => Number(pick.player_id)).filter(id => id > 0)
    ), [viewState?.picks]);
    const draftedNames = useMemo(() => new Set(
        (viewState?.picks || [])
            .map(pick => String(pick.player_name || '').trim().toLowerCase())
            .filter(Boolean)
    ), [viewState?.picks]);
    const availablePlayers = useMemo(() => (recommendations?.players || []).filter(player => {
        const playerId = Number(player.player_id);
        if (playerId > 0 && draftedIds.has(playerId)) return false;
        return !draftedNames.has(String(player.name || '').trim().toLowerCase());
    }), [recommendations, draftedIds, draftedNames]);

    const visiblePlayers = useMemo(() => {
        const query = search.trim().toLowerCase();
        const players = availablePlayers.filter(player => (
            (!query || player.name.toLowerCase().includes(query) || String(player.nba_team).toLowerCase().includes(query))
            && (position === 'ALL' || player.position === position)
        ));
        players.sort((a, b) => {
            if (sortBy === 'name') return sortDir === 'asc' ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
            const readValue = player => {
                if (sortBy === 'total_z') return player.total_z;
                if (sortBy === 'espn_adp') return player.espn_adp ?? Number.POSITIVE_INFINITY;
                if (sortBy === 'espn_market_pick') return player.espn_market_pick ?? player.espn_adp ?? Number.POSITIVE_INFINITY;
                if (sortBy === 'games_played') return player.games_played || 0;
                return Number((playersView === 'stats' ? player.stats : player.z_scores)?.[sortBy] || 0);
            };
            const valueA = readValue(a);
            const valueB = readValue(b);
            return sortDir === 'asc' ? valueA - valueB : valueB - valueA;
        });
        return players;
    }, [availablePlayers, search, position, sortBy, sortDir, playersView]);

    const simulationResults = recommendations?.simulation?.mode === 'all_slots'
        ? (recommendations.simulation.slot_results || [])
        : recommendations?.simulation?.slot_result ? [recommendations.simulation.slot_result] : [];
    const detailedSimulation = detailedSimulations[simulationSlot];
    const selectedSimulation = detailedSimulation?.slot_result
        || simulationResults.find(result => result.slot === simulationSlot)
        || simulationResults[0];
    const rankedSimulationSlots = [...simulationResults].sort((a, b) => b.average_category_wins - a.average_category_wins || a.average_league_rank - b.average_league_rank);
    const selectedSlotRank = selectedSimulation ? rankedSimulationSlots.findIndex(result => result.slot === selectedSimulation.slot) + 1 : null;
    const effectiveSimulationRuns = detailedSimulation?.runs
        || (recommendations?.simulation?.mode === 'all_slots' ? recommendations.simulation.runs_per_slot : recommendations?.simulation?.runs);

    const roster = useMemo(() => recommendations?.roster || [], [recommendations]);
    const rosterLimit = viewState?.roster_size || recommendations?.roster_limit || roster.length;
    const rosterTotalZ = roster.reduce((sum, player) => sum + Number(player.total_z || 0), 0);
    const rosterCategoryStrength = useMemo(() => Object.fromEntries(CATEGORIES.map(category => [
        category,
        roster.reduce((sum, player) => sum + Number(player.z_scores?.[category] || 0), 0),
    ])), [roster]);
    const balancedRound = recommendations?.round_balanced_comparison;
    const balancedComparison = balancedRound?.comparison;
    const pickAdvice = recommendations?.pick_advice;
    const projectedTurns = (selectedSimulation?.round_targets || []).slice(0, 3);
    const completedRounds = balancedRound?.completed_rounds || 0;
    const roundProgress = pickCount ? (pickCount % teamCount || teamCount) : 0;
    const displayRound = viewState?.next_round || (pickCount ? Math.ceil(pickCount / teamCount) : 1);

    const handleSort = column => {
        if (sortBy === column) setSortDir(current => current === 'asc' ? 'desc' : 'asc');
        else {
            setSortBy(column);
            setSortDir(column === 'espn_adp' ? 'asc' : 'desc');
        }
    };
    const SortIcon = ({ column }) => sortBy === column ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ' ⇅';

    const switchDraftMode = async mode => {
        if (mode === effectiveDraftMode || modeSwitching) return;
        if (mode === 'analytics' && !window.confirm('Переключиться на live-аналитику? ESPN отключит открытую официальную Draft Lobby, потому что разрешено только одно соединение.')) return;
        setModeSwitching(true);
        setModeError(null);
        try {
            await api.put('/settings/draft-connection-mode', { mode });
            setModeOverride(mode);
        } catch (requestError) {
            setModeError(requestError.response?.data?.detail || 'Не удалось переключить draft-соединение');
        } finally {
            setModeSwitching(false);
        }
    };

    if (!draftState) return <div className="p-6 text-center text-gray-500">Загрузка…</div>;
    const tabs = [['players', isPostDraft ? 'Свободные агенты' : 'Игроки'], ['draft', 'Драфт'], ['simulation', 'Симуляция']];

    return (
        <div>
            <div className="sticky top-0 z-10 mb-4 -mx-4 -mt-4 border-b bg-white shadow-sm">
                <div className="flex items-center overflow-x-auto">
                    <div className="grid min-w-[420px] flex-1 grid-cols-3">
                        {tabs.map(([key, label]) => <button key={key} onClick={() => setActiveTab(key)} className={`py-2 px-4 font-medium whitespace-nowrap ${activeTab === key ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500 hover:text-gray-700'}`}>{label}</button>)}
                    </div>
                    <button onClick={onOpenSettings} className="ml-4 rounded p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-700" title="Настройки">
<span className="block text-xl leading-5" aria-hidden="true">⚙</span>
                        <svg className="hidden h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826 2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
                    </button>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-2 border-t bg-slate-50 px-4 py-1.5">
                    <div className="mr-1 flex items-center gap-2 text-xs text-gray-500">
                        <span className={`h-2 w-2 rounded-full ${modeSwitching ? 'bg-amber-400' : analyticsDraftMode && draftState?.live_source ? 'bg-green-500' : 'bg-gray-400'}`} />
                        <span>{modeSwitching ? 'Переключение…' : analyticsDraftMode && draftState?.live_source ? 'Live подключён' : 'Источник драфта'}</span>
                    </div>
                    <div className="inline-flex rounded-lg border border-gray-200 bg-white p-0.5 text-xs" title="ESPN допускает только одно активное draft-соединение">
                        <button disabled={modeSwitching} onClick={() => switchDraftMode('espn')} className={`rounded-md px-3 py-1.5 font-medium transition-colors ${effectiveDraftMode === 'espn' ? 'bg-gray-800 text-white shadow-sm' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-700'}`}>ESPN</button>
                        <button disabled={modeSwitching} onClick={() => switchDraftMode('analytics')} className={`rounded-md px-3 py-1.5 font-medium transition-colors ${effectiveDraftMode === 'analytics' ? 'bg-blue-600 text-white shadow-sm' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-700'}`}>Аналитика</button>
                    </div>
                </div>
            </div>

            {error && <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
            {modeError && <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{modeError}</div>}
            {recommendationsLoading && recommendations && <div className="mb-4 flex items-center gap-2 rounded border border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-800"><span className="h-2 w-2 animate-pulse rounded-full bg-blue-500" />Пересчитываем данные после пика #{pickCount || '—'} — предыдущий дэшборд остаётся доступным.</div>}
            {!mainTeam ? (
                <div className="rounded border bg-white p-6 text-center"><button onClick={onOpenSettings} className="rounded bg-blue-600 px-4 py-2 text-white hover:bg-blue-700">Выбрать команду</button></div>
            ) : !recommendations ? (
                <div className="rounded border bg-white p-10 text-center text-gray-500">
                    {error ? 'Данные драфта сейчас недоступны' : 'Загрузка…'}
                </div>
            ) : <>
                {(activeTab === 'draft' || activeTab === 'players') && officialDraftMode && !hasLiveSnapshot && <section className="rounded-2xl border border-blue-200 bg-blue-50 p-8 text-center shadow-sm"><div className="text-sm font-semibold uppercase tracking-wide text-blue-700">Сейчас используется Draft Room ESPN</div><h1 className="mt-2 text-2xl font-bold text-gray-900">Снимок live-драфта ещё не получен</h1><p className="mx-auto mt-2 max-w-2xl text-sm text-gray-600">Один раз включите аналитику, чтобы загрузить актуальные пики, состав и рекомендации. После возврата в ESPN этот снимок останется на экране.</p><button disabled={modeSwitching} onClick={() => switchDraftMode('analytics')} className="mt-5 rounded bg-blue-600 px-5 py-2.5 font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-wait disabled:opacity-60">{modeSwitching ? 'Подключаемся…' : 'Получить live-снимок'}</button></section>}

                {(activeTab === 'draft' || activeTab === 'players') && officialDraftMode && hasLiveSnapshot && <section className="mb-4 flex flex-col gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 sm:flex-row sm:items-center sm:justify-between"><div><span className="font-semibold">Live приостановлен.</span> Показан снимок после пика #{pickCount}{snapshotTime ? ` · ${snapshotTime}` : ''}. Выбранные игроки скрыты. Пики, сделанные после переключения в ESPN, пока не учтены.</div><button disabled={modeSwitching} onClick={() => switchDraftMode('analytics')} className="shrink-0 rounded bg-amber-600 px-3 py-1.5 font-medium text-white hover:bg-amber-700 disabled:opacity-60">Обновить снимок</button></section>}

                {(activeTab === 'draft' || activeTab === 'players') && refreshingLiveSnapshot && <section className="mb-4 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900"><span className="font-semibold">Синхронизируем пропущенные пики…</span> Пока показываем предыдущий снимок после пика #{pickCount}.</section>}

                {(activeTab === 'draft' || activeTab === 'players') && waitingForFirstLiveSnapshot && <section className="rounded-2xl border border-amber-200 bg-amber-50 p-8 text-center shadow-sm"><div className="text-sm font-semibold uppercase tracking-wide text-amber-700">Live ESPN</div><h1 className="mt-2 text-2xl font-bold text-gray-900">Получаем первый снимок драфта</h1><p className="mx-auto mt-2 max-w-2xl text-sm text-gray-600">Как только ESPN подтвердит соединение, здесь появятся актуальные пики, состав и рекомендации.</p><div className="mt-4 text-xs text-amber-700">{draftState.live_sync_status === 'degraded' ? 'ESPN прервал соединение; backend переподключается автоматически.' : 'Соединение устанавливается…'}</div></section>}

                {activeTab === 'players' && !waitingForFirstLiveSnapshot && (!officialDraftMode || hasLiveSnapshot) && (
                    <section className="overflow-hidden rounded-xl border bg-white">
                        <div className="flex flex-col gap-3 border-b p-3 sm:flex-row sm:items-center sm:justify-between">
                            <div className="inline-flex self-start rounded-lg border border-gray-300 bg-gray-50 p-1">
                                <button onClick={() => { setPlayersView('stats'); setSortBy('total_z'); }} className={`rounded-md px-4 py-2 text-sm font-medium ${playersView === 'stats' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-600'}`}>Обычная статистика</button>
                                <button onClick={() => { setPlayersView('draft'); setSortBy('total_z'); }} className={`rounded-md px-4 py-2 text-sm font-medium ${playersView === 'draft' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-600'}`}>Драфт-анализ</button>
                            </div>
                            <div className="flex min-w-0 flex-1 gap-2 sm:justify-end">
                                <select value={position} onChange={event => setPosition(event.target.value)} className="rounded border p-2 text-sm"><option value="ALL">Все позиции</option>{['PG', 'SG', 'SF', 'PF', 'C'].map(item => <option key={item} value={item}>{item}</option>)}</select>
                                <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Поиск по имени..." className="min-w-0 flex-1 rounded border p-2 text-sm sm:max-w-sm" />
                            </div>
                        </div>
                        {playersView === 'stats' && <div className="border-b bg-blue-50 px-4 py-3 text-sm text-blue-900">Нейтральный статистический список доступных игроков: без ADP, вероятности доступности, очереди и draft-рекомендаций.</div>}
                        {playersView === 'draft' && <div className="border-b bg-blue-50 px-4 py-3 text-sm text-blue-900">Только доступные игроки по текущему снимку драфта{pickCount ? ` · после пика #${pickCount}` : ''}{draftedIds.size ? ` · скрыто выбранных: ${draftedIds.size}` : ''}.</div>}
                        <div className="overflow-x-auto"><table className="min-w-full border-collapse bg-white text-sm"><thead><tr className="bg-gray-100">
                            <th onClick={() => handleSort('name')} className="cursor-pointer whitespace-nowrap border p-2">Игрок<SortIcon column="name" /></th><th className="border p-2">Поз.</th><th className="border p-2">NBA</th><th onClick={() => handleSort('games_played')} className="cursor-pointer border p-2">GP<SortIcon column="games_played" /></th>
                            {playersView === 'draft' && <th onClick={() => handleSort('espn_market_pick')} className="cursor-pointer whitespace-nowrap border p-2">Рынок ESPN<SortIcon column="espn_market_pick" /></th>}<th onClick={() => handleSort('total_z')} className="cursor-pointer whitespace-nowrap border p-2">Total Z<SortIcon column="total_z" /></th>
                            {CATEGORIES.map(category => <th key={category} onClick={() => handleSort(category)} className={`cursor-pointer whitespace-nowrap border p-2 ${playersView === 'draft' && puntCategories.includes(category) ? 'opacity-40' : ''}`}>{category}<SortIcon column={category} /></th>)}
                        </tr></thead><tbody>{visiblePlayers.map(player => <tr key={player.player_id || player.name} className="hover:bg-gray-50">
                            <td className="cursor-pointer whitespace-nowrap border p-2 font-medium text-blue-600 hover:underline" onClick={() => onPlayerClick?.(player)}>{player.name}</td><td className="border p-2 text-center">{player.position}</td><td className="border p-2 text-center">{player.nba_team}</td><td className="border p-2 text-center">{player.games_played || '—'}</td>
                            {playersView === 'draft' && <td className="border p-2 text-center"><div className="font-medium">#{player.espn_market_pick?.toFixed(1) || '—'}</div><div className="text-[11px] text-gray-400">Roto #{player.espn_roto_rank ?? '—'} · ADP {player.espn_adp?.toFixed(1) || '—'}</div>{player.availability_probability != null && <div className="text-xs text-blue-500">{player.availability_probability}% · {player.draft_action}</div>}</td>}<td className={`border p-2 text-center font-bold ${zScoreTone(player.total_z)}`}>{Number(player.total_z || 0).toFixed(2)}</td>
                            {CATEGORIES.map(category => { const value = playersView === 'stats' ? player.stats?.[category] : player.z_scores?.[category]; const zScore = Number(player.z_scores?.[category] || 0); const tone = playersView === 'stats' ? zScoreTone(zScore) : (value > 0 ? 'text-green-600' : value < 0 ? 'text-red-600' : 'text-gray-400'); return <td key={category} className={`border p-2 text-center ${tone} ${playersView === 'draft' && puntCategories.includes(category) ? 'opacity-30' : ''}`}>{playersView === 'stats' ? <><div className="font-medium">{formatStat(category, value)}</div><div className="mt-0.5 text-[11px] opacity-75">Z {zScore > 0 ? '+' : ''}{zScore.toFixed(2)}</div></> : Number(value || 0).toFixed(2)}</td>; })}
                        </tr>)}</tbody></table></div>
                    </section>
                )}

                {activeTab === 'draft' && isUpcoming && <DraftPrepInfo draftState={draftState} recommendations={recommendations} onOpenSettings={onOpenSettings} />}

                {activeTab === 'draft' && !isUpcoming && !waitingForFirstLiveSnapshot && (!officialDraftMode || hasLiveSnapshot) && (
                    <div className="space-y-4">
                        <section className="overflow-hidden rounded-2xl bg-gradient-to-br from-blue-950 via-blue-900 to-indigo-800 text-white shadow-lg">
                            <div className="grid gap-5 p-6 lg:grid-cols-[1.5fr_1fr]"><div><div className="text-sm font-medium text-blue-200">{isLive ? 'LIVE DRAFT' : 'DRAFT COMPLETE'}</div><h1 className="mt-2 text-3xl font-bold">{isLive ? `Раунд ${displayRound}` : 'Итоговый драфт-дэшборд'}</h1><p className="mt-2 text-blue-100">{isLive ? `Сейчас выбирает: ${viewState.next_team_name || 'ожидаем ESPN'} · общий пик #${viewState.next_overall || '—'}` : 'Все пики завершены. Ниже — итоговая сила состава и прогноз сезона.'}</p>{isLive && <><div className="mt-4 h-2 overflow-hidden rounded-full bg-white/20"><div className="h-full rounded-full bg-cyan-300" style={{ width: `${Math.min(100, roundProgress / teamCount * 100)}%` }} /></div><div className="mt-1 text-xs text-blue-200">Пиков в текущем раунде: {roundProgress} / {teamCount}</div></>}</div><div className="grid grid-cols-2 gap-3"><div className="rounded-xl bg-white/10 p-4"><div className="text-xs text-blue-200">{isLive ? 'Ваш следующий пик' : 'Драфт завершён'}</div><div className="mt-1 text-2xl font-bold">{isLive ? `#${recommendations.next_pick_for_team || '—'}` : `${pickCount} пиков`}</div><div className="text-xs text-blue-200">{isLive ? `через ${recommendations.picks_until_turn ?? '—'} выборов` : `${rosterLimit} раундов завершено`}</div></div><div className="rounded-xl bg-white/10 p-4"><div className="text-xs text-blue-200">Состав</div><div className="mt-1 text-2xl font-bold">{roster.length} / {rosterLimit}</div><div className="text-xs text-blue-200">игроков выбрано</div></div></div></div>
                        </section>
                        <section className="grid grid-cols-2 gap-3 lg:grid-cols-5"><MetricCard label="Сила состава" value={rosterTotalZ.toFixed(1)} hint="Абсолютный Total Z" tone={rosterTotalZ >= 0 ? 'text-green-600' : 'text-red-600'} /><MetricCard label="Относительно лиги" value={balancedComparison ? `#${balancedComparison.league_rank} / ${balancedComparison.team_count}` : '—'} hint={completedRounds ? `После ${completedRounds}-го раунда` : 'После полного 1-го раунда'} /><MetricCard label="Категорий / матчап" value={selectedSimulation?.average_category_wins != null ? `${selectedSimulation.average_category_wins.toFixed(2)} / ${Math.max(1, CATEGORIES.length - puntCategories.length)}` : '—'} hint={puntCategories.length ? 'Категории стратегии' : 'Прогноз полного состава'} /><MetricCard label="Прогноз места" value={selectedSimulation?.average_league_rank != null ? `${selectedSimulation.average_league_rank.toFixed(1)} / ${teamCount}` : '—'} hint="По draft simulation" /><MetricCard label="Плей-офф" value={selectedSimulation?.playoff_probability != null ? `${selectedSimulation.playoff_probability}%` : '—'} hint={`Топ-4: ${selectedSimulation?.top_four_probability ?? '—'}%`} /></section>
                        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.15fr_.85fr]"><RecommendedPicks advice={pickAdvice} players={availablePlayers} onPlayerClick={onPlayerClick} isPostDraft={isPostDraft} /><RosterCard roster={roster} onPlayerClick={onPlayerClick} /></div>
                        <section className="rounded-xl border bg-white p-4 shadow-sm"><div className="mb-3 flex items-center justify-between"><div><h2 className="font-bold">Сила по категориям</h2><p className="text-xs text-gray-500">Абсолютная сумма Z текущего состава</p></div>{balancedComparison && <span className="text-xs text-gray-500">Ранги лиги зафиксированы после раунда {completedRounds}</span>}</div><div className="flex flex-wrap justify-center gap-2">{CATEGORIES.map(category => { const value = rosterCategoryStrength[category] || 0; const rank = balancedComparison?.category_ranks?.[category]; return <div key={category} style={balancedCategoryCardStyle(CATEGORIES.length)} className={`rounded-lg border p-3 ${puntCategories.includes(category) ? 'bg-gray-100 opacity-60' : ''}`}><div className="text-xs text-gray-500">{category}{rank ? ` · #${rank}` : ''}</div><div className={`text-lg font-bold ${value > 0 ? 'text-green-600' : value < 0 ? 'text-red-600' : 'text-gray-500'}`}>{value > 0 ? '+' : ''}{value.toFixed(1)}</div></div>; })}</div></section>
                        {projectedTurns.length > 0 && <ProjectedTurns turns={projectedTurns} simulation={selectedSimulation} />}
                        {viewState.last_picks?.length > 0 && <section className="overflow-hidden rounded-xl border bg-white shadow-sm"><div className="border-b p-4"><h2 className="font-bold">Последние пики</h2></div><div className="grid sm:grid-cols-2 lg:grid-cols-3">{viewState.last_picks.slice(0, 6).map(pick => <div key={pick.overall} className="border-b p-3 text-sm sm:border-r"><span className="mr-2 text-gray-400">#{pick.overall}</span><span className="font-medium">{pick.player_name}</span><div className="ml-8 text-xs text-gray-400">{pick.team_name}</div></div>)}</div></section>}
                    </div>
                )}

                {activeTab === 'simulation' && recommendations.simulation && selectedSimulation && <SimulationView recommendations={recommendations} selectedSimulation={selectedSimulation} simulationResults={simulationResults} rankedSimulationSlots={rankedSimulationSlots} selectedSlotRank={selectedSlotRank} effectiveSimulationRuns={effectiveSimulationRuns} simulationLoading={simulationLoading} simulationSlot={simulationSlot} setSimulationSlot={setSimulationSlot} puntCategories={puntCategories} teamCount={teamCount} onPlayerClick={onPlayerClick} isPostDraft={isPostDraft} />}
            </>}
        </div>
    );
};

const DraftPrepInfo = ({ draftState, recommendations }) => <div className="space-y-4"><section className="rounded-2xl bg-gradient-to-br from-blue-950 via-blue-900 to-indigo-800 p-6 text-white shadow-lg"><div className="text-sm font-medium text-blue-200">DRAFT PREP</div><h1 className="mt-2 text-3xl font-bold">Драфт ещё не начался</h1><p className="mt-2 max-w-2xl text-blue-100">Полный live-dashboard включится автоматически, когда ESPN переведёт драфт в состояние in progress.</p></section><section className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4"><MetricCard label="Тип" value={draftState.settings?.type || '—'} hint="Формат ESPN" /><MetricCard label="Порядок" value={draftState.settings?.order_known ? `Позиция ${recommendations.simulation?.slot || '—'}` : 'Не определён'} hint={draftState.settings?.order_known ? `Первый пик #${recommendations.planned_pick || '—'}` : 'Можно изучать позиции в симуляции'} /><MetricCard label="На выбор" value={draftState.settings?.time_per_selection ? `${draftState.settings.time_per_selection} сек` : '—'} hint="Лимит ESPN" /><MetricCard label="Команд" value={draftState.team_count || '—'} hint="В текущей лиге" /></section><section className="rounded-xl border bg-white p-5 text-sm text-gray-600">До старта используйте «Игроки» для изучения статистики и «Симуляцию» для проверки своей draft-позиции. Полный dashboard появится автоматически со стартом live-драфта.</section></div>;

const laneMeta = {
    take_now: { title: 'Брать сейчас', hint: 'Не доживут до следующего хода' },
    wait: { title: 'Можно ждать', hint: 'Скорее всего будут на следующем пике' },
    fallback: { title: 'Фоллы', hint: 'Замена, если цели снимут' },
    reach: { title: 'Вряд ли доживёт', hint: 'Не стройте план вокруг этих имён' },
    target: { title: 'Цели на ваш пик', hint: 'С высокой вероятностью будут доступны' },
    bubble: { title: 'На границе', hint: 'Могут уйти, держите фолл' },
};

const AdvicePlayerRow = ({ player, index, onPlayerClick, isPostDraft, featured = false }) => {
    const best = [...CATEGORIES].sort((a, b) => (player.z_scores?.[b] || 0) - (player.z_scores?.[a] || 0)).slice(0, 2);
    const availability = isPostDraft
        ? 'свободный агент'
        : player.availability_probability != null
            ? `${player.availability_probability}% · ${player.draft_action}`
            : 'рынок без очереди';
    return (
        <div className={`grid gap-3 p-4 sm:grid-cols-[2rem_1fr_auto] sm:items-center ${featured ? 'bg-blue-50' : 'hover:bg-gray-50'}`}>
            <div className={`text-lg font-bold ${featured ? 'text-blue-500' : 'text-gray-300'}`}>{index}</div>
            <div>
                <button onClick={() => onPlayerClick?.(player)} className="font-semibold text-blue-700 hover:underline">{player.name}</button>
                <div className="mt-1 text-xs text-gray-500">{player.position} · {player.nba_team} · GP {player.games_played || '—'} · рынок #{player.espn_market_pick?.toFixed?.(1) || player.espn_market_pick || '—'} · ADP {player.espn_adp?.toFixed?.(1) || player.espn_adp || '—'}</div>
                <div className="mt-1 text-xs text-gray-600">{player.reason}</div>
                <div className="mt-2 flex flex-wrap gap-1">
                    {best.map(category => <span key={category} className="rounded bg-green-50 px-2 py-0.5 text-xs text-green-700">{category} {Number(player.z_scores?.[category] || 0).toFixed(1)}</span>)}
                    {player.lookahead_wins != null && <span className="rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-700">EV {Number(player.lookahead_wins).toFixed(2)} кат.</span>}
                </div>
            </div>
            <div className="text-right">
                <div className="text-lg font-bold">{Number(player.score ?? player.total_z ?? 0).toFixed(1)}</div>
                <div className="text-xs text-gray-400">{Number(player.total_z || 0).toFixed(1)} Z</div>
                <div className="text-xs text-blue-600">{availability}</div>
            </div>
        </div>
    );
};

const AdviceLane = ({ lane, players, onPlayerClick, isPostDraft, startIndex }) => {
    if (!players?.length) return null;
    const meta = laneMeta[lane] || { title: lane, hint: '' };
    return (
        <div className="border-t">
            <div className="flex items-baseline justify-between px-4 pt-3">
                <h3 className="text-sm font-semibold text-gray-800">{meta.title}</h3>
                <span className="text-xs text-gray-400">{meta.hint}</span>
            </div>
            <div className="divide-y">
                {players.map((player, index) => (
                    <AdvicePlayerRow key={player.player_id || player.name} player={player} index={startIndex + index} onPlayerClick={onPlayerClick} isPostDraft={isPostDraft} />
                ))}
            </div>
        </div>
    );
};

const RecommendedPicks = ({ advice, players, onPlayerClick, isPostDraft }) => {
    const byKey = new Map((players || []).map(player => [player.player_id || player.name, player]));
    const hydrate = row => {
        if (!row) return null;
        return { ...row, ...(byKey.get(row.player_id) || byKey.get(row.name) || {}) };
    };
    const fallback = (players || []).slice(0, 6);
    const primary = hydrate(advice?.primary) || fallback[0];
    const used = new Set(primary ? [primary.player_id || primary.name] : []);
    const unique = list => (list || []).map(hydrate).filter(player => {
        if (!player) return false;
        const key = player.player_id || player.name;
        if (used.has(key)) return false;
        used.add(key);
        return true;
    });
    const onClock = advice?.is_on_the_clock;
    const takeNow = unique(advice?.take_now);
    const wait = unique(advice?.wait);
    const fallbackLane = unique(advice?.fallback);
    const hasAdvice = Boolean(advice?.primary);
    const lanes = isPostDraft
        ? []
        : onClock
            ? [['take_now', takeNow], ['wait', wait], ['fallback', fallbackLane]]
            : [['target', wait], ['bubble', fallbackLane], ['reach', takeNow]];
    const board = hasAdvice ? [primary, ...takeNow, ...wait, ...fallbackLane].filter(Boolean) : fallback;
    const list = isPostDraft ? fallback : board;
    let cursor = primary ? 2 : 1;

    return (
        <section className="h-full overflow-hidden rounded-xl border bg-white shadow-sm">
            <div className="border-b p-4">
                <div className="flex items-center justify-between">
                    <div>
                        <h2 className="font-bold">{isPostDraft ? 'Лучшие доступные свободные агенты' : 'Рекомендованные следующие пики'}</h2>
                        <p className="text-xs text-gray-500">{advice?.summary || (isPostDraft ? 'Ценность и потенциальное усиление состава после драфта' : 'EV состава по пантам, now/later и lookahead')}</p>
                    </div>
                    <span className="text-sm text-gray-400">{advice?.phase ? `фаза ${advice.phase}` : `Top ${list.length}`}</span>
                </div>
            </div>
            {primary && !isPostDraft && <AdvicePlayerRow player={primary} index={1} onPlayerClick={onPlayerClick} isPostDraft={isPostDraft} featured />}
            {isPostDraft && fallback.map((player, index) => <AdvicePlayerRow key={player.player_id || player.name} player={player} index={index + 1} onPlayerClick={onPlayerClick} isPostDraft={isPostDraft} />)}
            {!isPostDraft && lanes.map(([lane, lanePlayers]) => {
                const startIndex = cursor;
                cursor += lanePlayers.length;
                return <AdviceLane key={lane} lane={lane} players={lanePlayers} onPlayerClick={onPlayerClick} isPostDraft={isPostDraft} startIndex={startIndex} />;
            })}
            {!list.length && <div className="p-8 text-center text-sm text-gray-400">Нет доступных рекомендаций</div>}
        </section>
    );
};

const RosterCard = ({ roster, onPlayerClick }) => <section className="h-full overflow-hidden rounded-xl border bg-white shadow-sm"><div className="border-b p-4"><h2 className="font-bold">Мой состав</h2><p className="text-xs text-gray-500">Текущие пики ESPN и их вклад</p></div><div className="divide-y">{roster.map((player, index) => <div key={player.player_id || player.name} className="flex items-center justify-between gap-3 p-3 text-sm"><div><span className="mr-2 text-gray-400">{index + 1}</span><button onClick={() => onPlayerClick?.(player)} className="font-medium hover:text-blue-600">{player.name}</button><div className="ml-6 text-xs text-gray-400">{player.position} · пик #{player.draft_pick || '—'} · ADP {player.espn_adp?.toFixed(1) || '—'}</div></div><div className={player.total_z >= 0 ? 'font-bold text-green-600' : 'font-bold text-red-600'}>{player.total_z.toFixed(1)}</div></div>)}{!roster.length && <div className="p-10 text-center text-gray-400">Первый пик ещё не сделан</div>}</div></section>;

const ProjectedTurns = ({ turns, simulation }) => <section className="rounded-xl border bg-white p-4 shadow-sm"><div className="mb-3"><h2 className="font-bold">Прогноз следующих ваших ходов</h2><p className="text-xs text-gray-500">Наиболее частые варианты из симуляции рынка</p></div><div className="grid gap-3 md:grid-cols-3">{turns.map(turn => { const primary = simulation?.projected_roster?.find(player => player.round === turn.round); return <div key={`${turn.round}-${turn.pick}`} className="rounded-lg border p-4"><div className="text-xs text-gray-500">Раунд {turn.round} · пик #{turn.pick}</div><div className="mt-2 font-bold text-blue-700">{primary?.name || turn.targets?.[0]?.name || '—'}</div><div className="mt-1 text-xs text-gray-500">Доступен: {primary?.availability_frequency ?? turn.targets?.[0]?.availability_frequency ?? '—'}% · выбор: {primary?.selection_frequency ?? turn.targets?.[0]?.selection_frequency ?? '—'}%</div>{turn.targets?.length > 1 && <div className="mt-2 text-xs text-gray-400">Альтернативы: {turn.targets.slice(1, 3).map(player => player.name).join(' · ')}</div>}</div>; })}</div></section>;

const SimulationView = ({ recommendations, selectedSimulation, simulationResults, rankedSimulationSlots, selectedSlotRank, effectiveSimulationRuns, simulationLoading, setSimulationSlot, puntCategories, teamCount, onPlayerClick, isPostDraft }) => {
    const activeCategoryCount = Math.max(1, CATEGORIES.length - (puntCategories?.length || 0));
    return <div className="space-y-4"><section className="rounded border bg-white p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><div className="font-bold">{isPostDraft ? `Итоговая симуляция позиции ${selectedSimulation.slot}` : `Позиция ${selectedSimulation.slot}`}</div><div className="text-sm text-gray-500">{recommendations.simulation.mode === 'all_slots' ? `#${selectedSlotRank} из ${rankedSimulationSlots.length} · ${effectiveSimulationRuns} прогонов` : `Позиция определена · ${effectiveSimulationRuns} прогонов`}{simulationLoading ? ' · уточняем…' : ''}</div></div>{recommendations.simulation.mode === 'all_slots' && <div className="flex flex-wrap gap-1">{simulationResults.map(result => <button key={result.slot} onClick={() => setSimulationSlot(result.slot)} className={`h-9 w-9 rounded border text-sm font-medium ${selectedSimulation.slot === result.slot ? 'border-blue-600 bg-blue-600 text-white' : 'bg-white text-gray-600'}`}>{result.slot}</button>)}</div>}</div>{!isPostDraft && selectedSimulation.round_targets?.length > 0 && <div className="mt-4 text-sm text-gray-600">Пики: <span className="font-medium text-gray-900">{selectedSimulation.round_targets.map(round => round.pick).join(' · ')}</span></div>}<div className="mt-2 text-sm"><span className="text-gray-500">Стратегия: </span><span className="font-medium">{puntCategories.length ? `Punt ${puntCategories.join(' + ')}` : 'без панта'}</span></div></section><section className="grid grid-cols-2 gap-2 md:grid-cols-5"><MetricCard label="Категорий / матчап" value={`${selectedSimulation.average_category_wins?.toFixed(2) || '—'} / ${activeCategoryCount}`} hint={puntCategories.length ? 'Только категории стратегии' : undefined} /><MetricCard label="Место" value={`${selectedSimulation.average_league_rank?.toFixed(1) || '—'} / ${teamCount}`} /><MetricCard label="Топ-4" value={`${selectedSimulation.top_four_probability ?? '—'}%`} /><MetricCard label="Плей-офф" value={`${selectedSimulation.playoff_probability ?? '—'}%`} /><MetricCard label="Средний GP" value={selectedSimulation.average_games_played ?? '—'} hint={`${selectedSimulation.average_low_gp_count ?? '—'} игроков < 50`} /></section>{!isPostDraft && <SimulationRosterTable recommendations={recommendations} simulation={selectedSimulation} onPlayerClick={onPlayerClick} />}<section className="rounded border bg-white p-4"><div className="mb-3 flex items-center justify-between gap-3"><h2 className="font-bold">Категории против лиги</h2><div className="text-sm text-gray-500">В среднем <span className="font-semibold text-gray-900">#{selectedSimulation.average_league_rank?.toFixed(1) || '—'} из {teamCount}</span></div></div><div className="flex flex-wrap justify-center gap-2">{CATEGORIES.map(category => { const rank = selectedSimulation.category_ranks?.[category]; const margin = selectedSimulation.category_margin?.[category]; return <div key={category} style={balancedCategoryCardStyle(CATEGORIES.length)} className={`rounded border p-3 ${puntCategories.includes(category) ? 'opacity-40' : ''}`}><div className="text-xs text-gray-500">{category} · #{rank ?? '—'}</div><div className={`font-bold ${margin > 0 ? 'text-green-600' : margin < 0 ? 'text-red-600' : 'text-gray-500'}`}>{margin != null ? `${margin > 0 ? '+' : ''}${margin.toFixed(1)}` : '—'}</div></div>; })}</div></section></div>;
};

const SimulationRosterTable = ({ recommendations, simulation, onPlayerClick }) => <section className="overflow-hidden rounded border bg-white"><div className="flex items-center justify-between border-b p-4"><h2 className="font-bold">Пример одного прогона</h2><span className="text-sm text-gray-400">{simulation.projected_roster?.length || 0}</span></div><div className="overflow-x-auto"><table className="min-w-full text-sm"><thead><tr className="bg-gray-100"><th className="border p-2">Раунд</th><th className="border p-2">Пик</th><th className="border p-2 text-left">Игрок</th><th className="border p-2">Поз.</th><th className="border p-2">GP</th><th className="border p-2">Рынок</th><th className="border p-2">Цена</th><th className="border p-2">Доступен</th><th className="border p-2">Выбор</th></tr></thead><tbody>{(simulation.round_targets || []).map(round => { const primary = simulation.projected_roster?.find(player => player.round === round.round); const profile = recommendations.players.find(player => player.name === primary?.name); const alternatives = (round.targets || []).filter(player => player.name !== primary?.name); const price = draftPrice(primary); return <tr key={round.round} className="hover:bg-gray-50"><td className="border p-2 text-center">{round.round}</td><td className="border p-2 text-center">#{round.pick}</td><td className="border p-2">{primary ? <button onClick={() => onPlayerClick?.(profile || primary)} className="font-medium text-blue-600 hover:underline">{primary.name}</button> : '—'}{alternatives.length > 0 && <div className="mt-1 text-xs text-gray-400">{alternatives.map(player => `${player.name}: доступен ${player.availability_frequency}%, выбор ${player.selection_frequency}%`).join(' · ')}</div>}</td><td className="border p-2 text-center">{primary?.position || '—'}</td><td className="border p-2 text-center">{primary?.games_played || '—'}</td><td className="border p-2 text-center"><div>#{primary?.espn_market_pick?.toFixed(1) || '—'}</div><div className="text-[11px] text-gray-400">Roto #{primary?.espn_roto_rank ?? '—'} · ADP {primary?.espn_adp?.toFixed(1) || '—'}</div></td><td className={`border p-2 text-center ${price.tone}`}>{price.label}</td><td className="border p-2 text-center">{primary ? `${primary.availability_frequency}%` : '—'}</td><td className="border p-2 text-center">{primary ? `${primary.selection_frequency}%` : '—'}</td></tr>; })}</tbody></table></div></section>;

export default DraftAssistant;
