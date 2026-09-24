import React, { useEffect, useMemo, useRef, useState } from 'react';
import api from '../api';
import { LEAGUE_CATEGORIES as CATEGORIES } from '../utils/categories';
import DraftRoom from './DraftRoom';
const recommendationsCache = new Map();
const CACHE_TTL = 5 * 60 * 1000;
const storedRecommendationKey = contextKey => `draft-recommendation:${contextKey}`;

const readStoredRecommendation = contextKey => {
    try { return JSON.parse(sessionStorage.getItem(storedRecommendationKey(contextKey)) || 'null'); } catch { return null; }
};

const storeRecommendation = (contextKey, data) => {
    try { sessionStorage.setItem(storedRecommendationKey(contextKey), JSON.stringify(data)); } catch { /* refresh fallback only */ }
};

const formatStat = (category, value) => {
    if (value == null || Number.isNaN(Number(value))) return '—';
    const number = Number(value);
    if (['FG%', 'FT%', '3PT%'].includes(category)) return `${(number <= 1 ? number * 100 : number).toFixed(1)}%`;
    return number.toFixed(category === 'A/TO' ? 2 : 1);
};

const zTextTone = value => {
    const zScore = Number(value || 0);
    if (zScore > 0) return 'text-green-600';
    if (zScore < 0) return 'text-red-600';
    return 'text-gray-400';
};

const calculateStrategyZ = (player, puntCategories = []) => CATEGORIES.reduce((total, category) => (
    puntCategories.includes(category) ? total : total + Number(player.z_scores?.[category] || 0)
), 0);

const calculateGeneralZ = player => CATEGORIES.reduce(
    (total, category) => total + Number(player.z_scores?.[category] || 0),
    0,
);

const nextOwnPick = (pickCount, pickOrder, teamId) => {
    if (!pickOrder?.length || teamId == null || teamId === '') return null;
    const order = pickOrder.map(id => String(id));
    const target = String(teamId);
    const start = Number(pickCount) || 0;
    for (let index = start; index < start + order.length * 2; index += 1) {
        const round = Math.floor(index / order.length);
        const slot = index % order.length;
        const active = round % 2 === 0 ? order : [...order].reverse();
        if (active[slot] === target) return { overall: index + 1, until: index - start };
    }
    return null;
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

const MetricCard = ({ label, value, tone = 'text-gray-900' }) => (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</div>
        <div className={`mt-1 text-2xl font-bold ${tone}`}>{value}</div>
    </div>
);

const DraftAssistant = ({ draftState, mainTeam, puntCategories = [], projectedPeriod, leagueId, onOpenSettings, onPlayerClick, onDraftState }) => {
    const [activeTab, setActiveTab] = useState('draft');
    const storageKey = `draft-plan:${leagueId}:${projectedPeriod}:${mainTeam}`;
    const [plans, setPlans] = useState(() => {
        try { return JSON.parse(localStorage.getItem('draft-plans') || '{}'); } catch { return {}; }
    });
    const plan = plans[storageKey] || { queue: [], mock: [] };
    const mockIds = draftState?.status === 'upcoming' ? plan.mock.map(p => p.player_id).join(',') : '';
    const updatePlan = patch => setPlans(current => ({ ...current, [storageKey]: { ...(current[storageKey] || { queue: [], mock: [] }), ...patch } }));
    useEffect(() => { localStorage.setItem('draft-plans', JSON.stringify(plans)); }, [plans]);

    const [playersView, setPlayersView] = useState('draft');
    const [recommendations, setRecommendations] = useState(null);
    const [recommendationsLoading, setRecommendationsLoading] = useState(false);
    const [projectionLoading, setProjectionLoading] = useState(false);
    const recommendationContextRef = useRef(null);
    const recommendationAbort = useRef(null);
    const recommendationRequestId = useRef(0);
    const lastRequestedRecommendation = useRef(null);
    const [error, setError] = useState(null);
    const [search, setSearch] = useState('');
    const [position, setPosition] = useState('ALL');
    const [sortBy, setSortBy] = useState('total_z');
    const [sortDir, setSortDir] = useState('desc');
    const [simulationSlot, setSimulationSlot] = useState(1);
    const [detailedSimulations, setDetailedSimulations] = useState({});
    const [simulationLoading, setSimulationLoading] = useState(false);
    const [benchmark, setBenchmark] = useState(null);
    const [benchmarkLoading, setBenchmarkLoading] = useState(false);
    const benchmarkAbort = useRef(null);
    useEffect(() => {
        setBenchmark(null);
        setBenchmarkLoading(false);
        return () => benchmarkAbort.current?.abort();
    }, [mainTeam, projectedPeriod, leagueId]);
    const [benchmarkError, setBenchmarkError] = useState(null);
    const [pulling, setPulling] = useState(false);
    const [pullError, setPullError] = useState(null);
    const [showHint, setShowHint] = useState(false);
    const [showSimulation, setShowSimulation] = useState(false);
    const [inspectedTeamId, setInspectedTeamId] = useState(null);

    const isUpcoming = draftState?.status === 'upcoming';
    const isLive = draftState?.status === 'live';
    const isPostDraft = draftState?.postdraft;
    const viewState = draftState;
    const pickCount = viewState?.pick_count;
    const hasLiveSnapshot = Boolean(viewState?.live_snapshot_available);
    const snapshotTime = viewState?.live_updated_at
        ? new Date(Number(viewState.live_updated_at) * 1000).toLocaleTimeString('ru-RU')
        : null;
    const teamCount = Math.max(1, viewState?.team_count || 1);
    const effectivePlayersView = isPostDraft ? 'stats' : playersView;
    const recommendationTrigger = isUpcoming
        ? `upcoming:${pickCount || 0}:${mockIds}`
        : isPostDraft
            ? `completed:${pickCount || 0}`
            : isLive && hasLiveSnapshot
                ? `snapshot:${pickCount || 0}:${viewState?.live_updated_at || 0}`
                : null;
    const recommendationTriggerKind = isUpcoming
        ? 'upcoming'
        : isPostDraft
            ? 'completed'
            : 'snapshot';

    useEffect(() => {
        if (recommendations?.simulation?.mode === 'known_order') setSimulationSlot(recommendations.simulation.slot);
    }, [recommendations]);

    useEffect(() => {
        if (isPostDraft && activeTab === 'simulation') setActiveTab('draft');
    }, [activeTab, isPostDraft]);

    const recommendationContextKey = [leagueId, mainTeam, projectedPeriod, puntCategories.join(','), mockIds].join('|');

    useEffect(() => {
        if (!mainTeam) return;
        if (recommendationContextRef.current === recommendationContextKey) return;
        recommendationContextRef.current = recommendationContextKey;
        recommendationAbort.current?.abort();
        recommendationRequestId.current += 1;
        lastRequestedRecommendation.current = null;
        setRecommendations(readStoredRecommendation(recommendationContextKey));
        setRecommendationsLoading(false);
        setDetailedSimulations({});
        setError(null);
    }, [mainTeam, recommendationContextKey]);

    useEffect(() => {
        if (!mainTeam || pickCount === undefined || !recommendationTrigger) return undefined;
        const requestKey = `${recommendationContextKey}|${recommendationTrigger}`;
        if (lastRequestedRecommendation.current === requestKey) return undefined;
        lastRequestedRecommendation.current = requestKey;
        recommendationAbort.current?.abort();
        const controller = new AbortController();
        recommendationAbort.current = controller;
        const requestId = recommendationRequestId.current + 1;
        recommendationRequestId.current = requestId;
        setDetailedSimulations({});
        setError(null);
        setRecommendationsLoading(true);
        setProjectionLoading(false);
        const cacheKey = [leagueId, mainTeam, projectedPeriod, puntCategories.join(','), pickCount, mockIds, viewState?.live_updated_at || ''].join('|');
        const cached = recommendationsCache.get(cacheKey);
        if (cached && Date.now() - cached.savedAt < CACHE_TTL) {
            setRecommendations(current => (
                current?.projection_ready && Number(current.draft_pick_count) === Number(cached.data?.draft_pick_count)
                    ? current
                    : cached.data
            ));
            setRecommendationsLoading(false);
            return undefined;
        }
        const paramsFor = scope => ({
            period: projectedPeriod,
            punt_categories: puntCategories.join(','),
            mock_player_ids: mockIds,
            limit: 300,
            expected_pick_count: isLive ? pickCount : undefined,
            trigger: recommendationTriggerKind,
            scope,
        });
        const accept = data => requestId === recommendationRequestId.current && (!isLive || Number(data?.draft_pick_count) === Number(pickCount));
        const loadBoard = api.get(`/draft/recommendations/${mainTeam}`, {
            params: paramsFor(isUpcoming ? 'full' : 'board'),
            signal: controller.signal,
        });
        loadBoard
            .then(response => {
                if (!accept(response.data)) return null;
                setRecommendations(current => (
                    current?.projection_ready && Number(current.draft_pick_count) === Number(response.data.draft_pick_count)
                        ? current
                        : response.data
                ));
                setRecommendationsLoading(false);
                recommendationsCache.set(cacheKey, { data: response.data, savedAt: Date.now() });
                if (recommendationsCache.size > 8) recommendationsCache.delete(recommendationsCache.keys().next().value);
                storeRecommendation(recommendationContextKey, response.data);
                return null;
            })
            .catch(requestError => {
                if (requestError.code === 'ERR_CANCELED') {
                    if (lastRequestedRecommendation.current === requestKey) lastRequestedRecommendation.current = null;
                    return;
                }
                if (requestId !== recommendationRequestId.current) return;
                if (requestError.response?.status !== 409) setError(requestError.response?.data?.detail || 'Не удалось загрузить данные драфта');
            })
            .finally(() => {
                if (requestId === recommendationRequestId.current) setRecommendationsLoading(false);
            });
        return () => {
            controller.abort();
            if (lastRequestedRecommendation.current === requestKey) lastRequestedRecommendation.current = null;
        };
    }, [mainTeam, pickCount, recommendationContextKey, recommendationTrigger, recommendationTriggerKind, isLive, isUpcoming, leagueId, projectedPeriod, puntCategories, mockIds]);

    useEffect(() => {
        if (!showSimulation || isUpcoming || !mainTeam || pickCount === undefined) return undefined;
        if (isLive && !hasLiveSnapshot) return undefined;
        if (recommendationsLoading) return undefined;
        if (!recommendations || Number(recommendations.draft_pick_count) !== Number(pickCount) || recommendations.projection_ready) return undefined;
        const controller = new AbortController();
        const cacheKey = [leagueId, mainTeam, projectedPeriod, puntCategories.join(','), pickCount, mockIds, viewState?.live_updated_at || ''].join('|');
        setProjectionLoading(true);
        api.get(`/draft/recommendations/${mainTeam}`, {
            params: {
                period: projectedPeriod,
                punt_categories: puntCategories.join(','),
                mock_player_ids: mockIds,
                limit: 300,
                expected_pick_count: pickCount,
                trigger: isLive ? 'snapshot' : 'manual',
                scope: 'projection',
            },
            signal: controller.signal,
        })
            .then(response => {
                if (Number(response.data?.draft_pick_count) !== Number(pickCount)) return;
                recommendationsCache.set(cacheKey, { data: response.data, savedAt: Date.now() });
                setRecommendations(response.data);
            })
            .catch(requestError => {
                if (requestError.code === 'ERR_CANCELED' || requestError.response?.status === 409) return;
                setError(requestError.response?.data?.detail || 'Не удалось посчитать симуляцию');
            })
            .finally(() => { if (!controller.signal.aborted) setProjectionLoading(false); });
        return () => {
            controller.abort();
            setProjectionLoading(false);
        };
    }, [showSimulation, isLive, isUpcoming, hasLiveSnapshot, mainTeam, pickCount, projectedPeriod, puntCategories, mockIds, viewState?.live_updated_at, recommendationsLoading, recommendations?.draft_pick_count, recommendations?.projection_ready, leagueId]);

    useEffect(() => {
        const mode = recommendations?.simulation?.mode;
        const needsSim = mode === 'all_slots' || (mode === 'known_order' && !recommendations?.simulation?.slot_result);
        if (activeTab !== 'simulation' || !mainTeam || !needsSim || detailedSimulations[simulationSlot]) return;
        let active = true;
        setSimulationLoading(true);
        api.get(`/draft/recommendations/${mainTeam}`, {
            params: { period: projectedPeriod, punt_categories: puntCategories.join(','), mock_player_ids: mockIds, simulation_slot: simulationSlot, trigger: 'manual', limit: 300 },
        })
            .then(response => active && setDetailedSimulations(current => ({ ...current, [simulationSlot]: response.data.simulation })))
            .catch(requestError => active && setError(requestError.response?.data?.detail || 'Не удалось уточнить симуляцию'))
            .finally(() => active && setSimulationLoading(false));
        return () => { active = false; };
    }, [activeTab, mainTeam, recommendations, simulationSlot, detailedSimulations, projectedPeriod, puntCategories, mockIds]);

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
                if (sortBy === 'total_z') return calculateStrategyZ(player, puntCategories);
                if (sortBy === 'espn_adp') return player.espn_adp ?? Number.POSITIVE_INFINITY;
                if (sortBy === 'espn_market_pick') return player.espn_market_pick ?? player.espn_adp ?? Number.POSITIVE_INFINITY;
                if (sortBy === 'games_played') return player.games_played || 0;
                return Number((effectivePlayersView === 'stats' ? player.stats : player.z_scores)?.[sortBy] || 0);
            };
            const valueA = readValue(a);
            const valueB = readValue(b);
            return sortDir === 'asc' ? valueA - valueB : valueB - valueA;
        });
        return players;
    }, [availablePlayers, search, position, sortBy, sortDir, effectivePlayersView, puntCategories]);

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

    const snapshotRoster = useMemo(() => (viewState?.picks || [])
        .filter(pick => String(pick.team_id) === String(mainTeam))
        .sort((left, right) => Number(left.overall) - Number(right.overall))
        .map(pick => ({
            player_id: pick.player_id,
            name: pick.player_name,
            draft_pick: pick.overall,
            position: null,
            total_z: null,
        })), [viewState?.picks, mainTeam]);
    const rosterReady = recommendations && Number(recommendations.draft_pick_count) === Number(pickCount);
    const roster = rosterReady && recommendations.roster?.length
        ? recommendations.roster
        : (isLive ? snapshotRoster : (recommendations?.roster || []));
    const ownPick = isLive ? nextOwnPick(pickCount, viewState?.settings?.pick_order, mainTeam) : null;
    const rosterLimit = viewState?.roster_size || recommendations?.roster_limit || roster.length;
    const rosterTotalZ = roster.reduce((sum, player) => sum + Number(player.total_z || 0), 0);
    const rosterCategoryStrength = useMemo(() => Object.fromEntries(CATEGORIES.map(category => [
        category,
        roster.reduce((sum, player) => sum + Number(player.z_scores?.[category] || 0), 0),
    ])), [roster]);
    const balancedRound = recommendations?.round_balanced_comparison;
    const balancedComparison = balancedRound?.comparison;
    const liveStandings = useMemo(() => (
        Number(balancedRound?.completed_rounds) > 0 ? (balancedRound.standings || []) : []
    ), [balancedRound]);
    const youStanding = liveStandings.find(row => row.is_you) || null;
    const inspectedStanding = inspectedTeamId == null ? null : (liveStandings.find(row => String(row.team_id) === String(inspectedTeamId)) || null);
    const completedTeamStats = isLive && Number(balancedRound?.completed_rounds) > 0 ? balancedRound : null;
    const displayedTotalZ = isLive ? (completedTeamStats ? Number(completedTeamStats.total_z || 0) : null) : rosterTotalZ;
    const displayedCategoryStrength = isLive ? (completedTeamStats?.category_strength || {}) : rosterCategoryStrength;
    const pickAdvice = recommendations?.pick_advice;
    const calculatedPickCount = recommendations?.draft_pick_count;
    const recommendationsAreStale = isLive && recommendations && Number(calculatedPickCount) !== Number(pickCount);
    const waitingForScheduledCalculation = isLive && !recommendations && !recommendationsLoading && !recommendationTrigger;
    const projectedTurns = (selectedSimulation?.round_targets || []).slice(0, 3);
    const categoryRanks = balancedComparison?.category_ranks || {};
    const rankedCategories = [...CATEGORIES].filter(category => categoryRanks[category] != null).sort((a, b) => categoryRanks[a] - categoryRanks[b]);
    const strongestCategories = rankedCategories.slice(0, 3);
    const weakestCategories = rankedCategories.slice(-3).reverse();
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

    const pullBoard = async () => {
        if (pulling || !isLive) return;
        setPulling(true);
        setPullError(null);
        try {
            const response = await api.post('/draft/pull');
            onDraftState?.(response.data);
        } catch (requestError) {
            setPullError(requestError.response?.data?.detail || 'Не удалось снять доску. Прошлый снимок на месте.');
        } finally {
            setPulling(false);
        }
    };

    const runBenchmark = async () => {
        if (!mainTeam || benchmarkLoading) return;
        setBenchmarkLoading(true);
        setBenchmarkError(null);
        const controller = new AbortController();
        benchmarkAbort.current?.abort();
        benchmarkAbort.current = controller;
        try {
            const response = await api.post(`/draft/benchmark-jobs/${mainTeam}`, null, { params: { period: projectedPeriod }, signal: controller.signal });
            const deadline = Date.now() + 15 * 60 * 1000;
            while (!controller.signal.aborted && Date.now() < deadline) {
                const job = await api.get(`/draft/jobs/${response.data.job_id}`, { signal: controller.signal });
                if (job.data.status === 'complete') { setBenchmark(job.data.result); return; }
                if (job.data.status === 'failed') throw new Error(job.data.error);
                await new Promise(resolve => setTimeout(resolve, 2000));
            }
            throw new Error('Расчёт ещё выполняется. Повторное нажатие откроет тот же расчёт.');
        } catch (requestError) {
            if (!controller.signal.aborted) setBenchmarkError(requestError.response?.data?.detail || requestError.message || 'Не удалось сравнить стратегии');
        } finally {
            if (!controller.signal.aborted) setBenchmarkLoading(false);
        }
    };

    if (!draftState) return <div className="p-6 text-center text-gray-500">Загрузка…</div>;
    const snakeSlot = (draftState.settings?.pick_order || []).findIndex(id => String(id) === String(mainTeam)) + 1 || null;
    const tabs = isPostDraft
        ? [['players', 'Свободные агенты'], ['draft', 'Анализ состава']]
        : [['players', 'Игроки'], ['draft', 'Драфт'], ['simulation', 'Симуляция']];

    return (
        <div>
            <div className="sticky top-0 z-10 mb-4 -mx-4 -mt-4 border-b bg-white shadow-sm">
                <div className="flex items-center overflow-x-auto">
                    <div className={`grid flex-1 ${isPostDraft ? 'min-w-[300px] grid-cols-2' : 'min-w-[420px] grid-cols-3'}`}>
                        {tabs.map(([key, label]) => <button key={key} onClick={() => setActiveTab(key)} className={`py-2 px-4 font-medium whitespace-nowrap ${activeTab === key ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500 hover:text-gray-700'}`}>{label}</button>)}
                    </div>
                    <button onClick={onOpenSettings} className="ml-2 rounded p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-700" title="Настройки">
<span className="block text-xl leading-5" aria-hidden="true">⚙</span>
                        <svg className="hidden h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826 2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
                    </button>
                </div>
                {isLive && <div className="flex flex-wrap items-center justify-between gap-2 border-t bg-slate-50 px-4 py-1.5 text-xs text-gray-600">
                    <span>{hasLiveSnapshot ? `Снимок #${pickCount || '—'}${snapshotTime ? ` · ${snapshotTime}` : ''}` : 'Доска ESPN, снимок ещё не снят'}</span>
                    <button
                        disabled={pulling}
                        title="Снять доску и сразу выйти из лобби"
                        onClick={pullBoard}
                        className="rounded bg-blue-600 px-3 py-1.5 font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >{pulling ? 'Снимаем…' : 'Снять доску'}</button>
                </div>}
            </div>

            {!isPostDraft && <section className="mb-4 rounded border bg-white p-4">
                <h2 className="font-semibold">Очередь</h2>
                <div className="mt-2 flex flex-wrap gap-2">{plan.queue.map((player, index) => <div key={player.player_id} className="rounded border p-2 text-sm">
                    <button onClick={() => onPlayerClick?.(player)}>{draftedIds.has(Number(player.player_id)) ? 'Выбран: ' : ''}{player.name}</button>
                    <button disabled={index === 0} aria-label={`Поднять ${player.name}`} className="ml-2" onClick={() => { const queue = [...plan.queue]; [queue[index - 1], queue[index]] = [queue[index], queue[index - 1]]; updatePlan({ queue }); }}>↑</button>
                    <button aria-label={`Убрать ${player.name} из очереди`} className="ml-2" onClick={() => updatePlan({ queue: plan.queue.filter(p => p.player_id !== player.player_id) })}>×</button>
                </div>)}</div>
                {isUpcoming && <div className="mt-4 border-t pt-3"><h2 className="font-semibold">Состав · {plan.mock.length}</h2>
                    {plan.mock.map(player => <button key={player.player_id} className="mr-2 mt-2 rounded border p-2 text-sm" onClick={() => updatePlan({ mock: plan.mock.filter(p => p.player_id !== player.player_id) })}>{player.name} ×</button>)}
                    {!!plan.mock.length && <button className="mt-2 text-sm text-red-700" onClick={() => updatePlan({ mock: [] })}>Очистить</button>}
                </div>}
            </section>}

            {error && <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
            {pullError && <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{pullError}</div>}
            {recommendationsLoading && <div className="mb-4 rounded border border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-800">Считаем состав… #{pickCount || '—'}</div>}
            {showSimulation && projectionLoading && !recommendationsLoading && <div className="mb-4 rounded border border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-800">Считаем прогноз… #{pickCount || '—'}</div>}
            {recommendationsAreStale && !recommendationsLoading && <div className="mb-4 rounded border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">Снимок #{calculatedPickCount}, сейчас #{pickCount}</div>}
            {!mainTeam ? (
                <div className="rounded border bg-white p-6 text-center"><button onClick={onOpenSettings} className="rounded bg-blue-600 px-4 py-2 text-white hover:bg-blue-700">Выбрать команду</button></div>
            ) : (
            <>
                {isUpcoming && activeTab === 'draft' && <DraftPrepInfo draftState={draftState} recommendations={recommendations} mainTeam={mainTeam} snakeSlot={snakeSlot} />}
                {activeTab === 'draft' && !isUpcoming && (
                    <DraftRoom
                        puntCategories={puntCategories}
                        onPlayerClick={onPlayerClick}
                        totalsAreZ
                        roundLabel={isPostDraft ? 'Финал' : String(displayRound || '—')}
                        clockLabel={isLive ? `${viewState?.next_team_name || '—'} · #${viewState?.next_overall || '—'}` : 'Драфт завершён'}
                        yourPick={isLive ? ownPick?.overall : null}
                        picksUntil={isLive ? (ownPick?.until ?? null) : null}
                        rosterCount={roster.length}
                        rosterLimit={rosterLimit}
                        rankLabel={youStanding ? `#${youStanding.league_rank} / ${liveStandings.length}` : '—'}
                        recordLabel={youStanding?.matchup_wins == null ? null : `${youStanding.matchup_wins}-${youStanding.matchup_losses}-${youStanding.matchup_ties}`}
                        showHint={showHint}
                        onToggleHint={() => setShowHint(value => !value)}
                        showSimulation={showSimulation}
                        onToggleSimulation={() => setShowSimulation(value => !value)}
                        hint={pickAdvice?.primary ? {
                            label: pickAdvice.is_on_the_clock ? 'Сейчас взял бы' : 'На ваш пик',
                            player: pickAdvice.primary,
                            name: pickAdvice.primary.name,
                            position: pickAdvice.primary.position,
                            z: pickAdvice.primary.total_z ?? pickAdvice.primary.score,
                        } : null}
                        players={availablePlayers}
                        highlightedPlayerId={showHint ? pickAdvice?.primary?.player_id : null}
                        pickLog={(viewState?.picks || []).map(pick => ({
                            overall: pick.overall,
                            round: pick.round,
                            playerName: pick.player_name,
                            player: { name: pick.player_name, player_id: pick.player_id },
                            teamName: pick.team_name,
                            isYou: String(pick.team_id) === String(mainTeam),
                        }))}
                        standingsTitle={Number(balancedRound?.completed_rounds) > 0 ? `После раунда ${balancedRound.completed_rounds}` : 'Лига'}
                        standings={liveStandings}
                        yourRoster={roster}
                        inspected={inspectedStanding}
                        onInspectTeam={row => setInspectedTeamId(row && String(row.team_id) !== String(mainTeam) ? row.team_id : null)}
                        simulationContent={(
                            <div className="space-y-4">
                                {!projectionLoading && recommendations?.projection_ready && selectedSimulation && (
                                    <>
                                        <section className="grid grid-cols-2 gap-3">
                                            <div className="rounded-xl border bg-white p-4"><div className="text-xs text-gray-500">Прогноз места</div><div className="mt-1 text-2xl font-bold">{selectedSimulation.average_league_rank != null ? `${Number(selectedSimulation.average_league_rank).toFixed(1)} / ${teamCount}` : '—'}</div></div>
                                            <div className="rounded-xl border bg-white p-4"><div className="text-xs text-gray-500">Top-N</div><div className="mt-1 text-2xl font-bold">{selectedSimulation.projected_top_n_strength_rate != null ? `${selectedSimulation.projected_top_n_strength_rate}%` : '—'}</div></div>
                                        </section>
                                        {projectedTurns.length > 0 && <ProjectedTurns turns={projectedTurns} simulation={selectedSimulation} />}
                                    </>
                                )}
                            </div>
                        )}
                    />
                )}
                {!recommendations && activeTab !== 'draft' ? (
                    <div className="rounded border bg-white p-10 text-center text-gray-500">
                        {error ? 'Данные драфта сейчас недоступны' : waitingForScheduledCalculation ? 'Снимите доску для пересчёта' : 'Собираем доску игроков…'}
                    </div>
                ) : recommendations ? <>
                {activeTab === 'players' && (
                    <section className="overflow-hidden rounded-xl border bg-white">
                        <div className="flex flex-col gap-3 border-b p-3 sm:flex-row sm:items-center sm:justify-between">
                            {!isPostDraft && <div className="inline-flex self-start rounded-lg border border-gray-300 bg-gray-50 p-1">
                                <button onClick={() => { setPlayersView('stats'); setSortBy('total_z'); }} className={`rounded-md px-4 py-2 text-sm font-medium ${playersView === 'stats' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-600'}`}>Обычная статистика</button>
                                <button onClick={() => { setPlayersView('draft'); setSortBy('total_z'); }} className={`rounded-md px-4 py-2 text-sm font-medium ${playersView === 'draft' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-600'}`}>Драфт-анализ</button>
                            </div>}
                            <div className="flex min-w-0 flex-1 gap-2 sm:justify-end">
                                <select value={position} onChange={event => setPosition(event.target.value)} className="rounded border p-2 text-sm"><option value="ALL">Все позиции</option>{['PG', 'SG', 'SF', 'PF', 'C'].map(item => <option key={item} value={item}>{item}</option>)}</select>
                                <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Поиск по имени..." className="min-w-0 flex-1 rounded border p-2 text-sm sm:max-w-sm" />
                            </div>
                        </div>
                        <div className="overflow-x-auto"><table className="min-w-full border-collapse bg-white text-sm"><thead><tr className="bg-gray-100">
                            <th onClick={() => handleSort('name')} className="cursor-pointer whitespace-nowrap border p-2">Игрок<SortIcon column="name" /></th><th className="border p-2">Поз.</th><th className="border p-2">NBA</th><th onClick={() => handleSort('games_played')} className="cursor-pointer border p-2">GP<SortIcon column="games_played" /></th>
                            {effectivePlayersView === 'draft' && <th onClick={() => handleSort('espn_market_pick')} className="cursor-pointer whitespace-nowrap border p-2">Оценка рынка<SortIcon column="espn_market_pick" /></th>}<th onClick={() => handleSort('total_z')} className="cursor-pointer whitespace-nowrap border p-2 hover:bg-gray-200">{puntCategories.length ? 'Z стратегии' : 'Total Z'}<SortIcon column="total_z" /></th>
                            {CATEGORIES.map(category => <th key={category} onClick={() => handleSort(category)} className={`cursor-pointer whitespace-nowrap border p-2 hover:bg-gray-200 ${puntCategories.includes(category) ? 'opacity-50' : ''}`}>{category}<SortIcon column={category} /></th>)}
                        </tr></thead><tbody>{visiblePlayers.map(player => {
                            const strategyZ = calculateStrategyZ(player, puntCategories);
                            return <tr key={player.player_id || player.name} className="hover:bg-gray-50">
                            <td className="cursor-pointer whitespace-nowrap border p-2 font-medium text-blue-600 hover:underline" onClick={() => onPlayerClick?.(player)}>{player.name}</td><td className="border p-2 text-center">{player.position}</td><td className="border p-2 text-center">{player.nba_team}</td><td className="border p-2 text-center">{player.games_played || '—'}</td>
                            {effectivePlayersView === 'draft' && <td className="border p-2 text-center">{player.espn_market_pick?.toFixed(1) || '—'}</td>}<td className={`border p-2 text-center font-bold ${zTextTone(strategyZ)}`}>{strategyZ.toFixed(2)}{puntCategories.length > 0 && <div className="text-xs font-normal text-gray-400">общий {calculateGeneralZ(player).toFixed(2)}</div>}</td>
                            {CATEGORIES.map(category => { const value = effectivePlayersView === 'stats' ? player.stats?.[category] : player.z_scores?.[category]; const zScore = Number(player.z_scores?.[category] || 0); return <td key={category} className={`border p-2 text-center ${zTextTone(zScore)} ${puntCategories.includes(category) ? 'opacity-30' : ''}`}>{effectivePlayersView === 'stats' ? formatStat(category, value) : zScore.toFixed(2)}</td>; })}
                        </tr>;
                        })}</tbody></table></div>
                    </section>
                )}

                {activeTab === 'simulation' && recommendations.simulation && !selectedSimulation && (
                    <div className="rounded border bg-white p-10 text-center text-gray-500">{simulationLoading ? 'Считаем симуляцию слота…' : 'Нет данных симуляции'}</div>
                )}
                {activeTab === 'simulation' && recommendations.simulation && selectedSimulation && <SimulationView recommendations={recommendations} selectedSimulation={selectedSimulation} simulationResults={simulationResults} rankedSimulationSlots={rankedSimulationSlots} selectedSlotRank={selectedSlotRank} effectiveSimulationRuns={effectiveSimulationRuns} simulationLoading={simulationLoading} simulationSlot={simulationSlot} setSimulationSlot={setSimulationSlot} puntCategories={puntCategories} teamCount={teamCount} onPlayerClick={onPlayerClick} isPostDraft={isPostDraft} benchmark={benchmark} benchmarkLoading={benchmarkLoading} benchmarkError={benchmarkError} runBenchmark={runBenchmark} />}
            </> : null}
            </>
            )}
        </div>
    );
};

const DraftPrepInfo = ({ draftState, recommendations, snakeSlot }) => {
    const slot = recommendations?.simulation?.slot || snakeSlot;
    const firstPick = recommendations?.planned_pick || (slot && (draftState.settings?.pick_order || []).length ? slot : null);
    const orderKnown = Boolean(draftState.settings?.order_known || slot);
    return <div className="space-y-4"><section className="rounded-2xl bg-gradient-to-br from-blue-950 via-blue-900 to-indigo-800 p-6 text-white shadow-lg"><div className="text-sm font-medium text-blue-200">DRAFT PREP</div><h1 className="mt-2 text-3xl font-bold">{orderKnown ? `Слот ${slot || '—'}` : 'Порядок не известен'}</h1></section><section className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4"><MetricCard label="Тип" value={draftState.settings?.type || '—'} /><MetricCard label="Пик" value={orderKnown ? `#${firstPick || '—'}` : '—'} /><MetricCard label="Таймер" value={draftState.settings?.time_per_selection ? `${draftState.settings.time_per_selection} сек` : '—'} /><MetricCard label="Команд" value={draftState.team_count || '—'} /></section></div>;
};

const AdaptiveStrategyPanel = ({ strategy }) => {
    const rows = strategy?.strategies || [];
    const learned = strategy?.learned_policy;
    if (!rows.length && !learned?.enabled) return null;
    const fixed = rows.length === 1 && rows[0].id === 'fixed';
    return (
        <section className="rounded-xl border bg-white p-4 shadow-sm">
            <h2 className="mb-3 font-bold">{fixed ? 'Пант' : 'Стратегии'}</h2>
            {learned?.enabled && (
                <div className="mb-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800">
                    Нейросеть V8 · {learned.checkpoint || 'frozen.pt'}
                </div>
            )}
            <div className="flex flex-wrap gap-2">{rows.slice(0, 5).map(row => <div key={row.id} className="min-w-36 flex-1 rounded-lg border p-3"><div className="text-xs text-gray-500">{row.punt_categories.length ? `Punt ${row.punt_categories.join(' + ')}` : 'Balanced'}</div><div className="mt-1 text-lg font-bold text-blue-700">{Number(row.probability).toFixed(0)}%</div></div>)}</div>
        </section>
    );
};

const laneMeta = {
    take_now: 'Брать',
    wait: 'Ждать',
    fallback: 'Фолл',
    reach: 'Риск',
    target: 'Цель',
    bubble: 'Граница',
};

const AdvicePlayerRow = ({ player, index, onPlayerClick, featured = false }) => {
    const best = [...CATEGORIES].sort((a, b) => (player.z_scores?.[b] || 0) - (player.z_scores?.[a] || 0)).slice(0, 2);
    return (
        <div className={`grid gap-3 p-4 sm:grid-cols-[2rem_1fr_auto] sm:items-center ${featured ? 'bg-blue-50' : 'hover:bg-gray-50'}`}>
            <div className={`text-lg font-bold ${featured ? 'text-blue-500' : 'text-gray-300'}`}>{index}</div>
            <div>
                <button onClick={() => onPlayerClick?.(player)} className="font-semibold text-blue-700 hover:underline">{player.name}</button>
                <div className="mt-1 text-xs text-gray-500">{player.position} · {player.nba_team} · #{player.espn_market_pick?.toFixed?.(1) || player.espn_market_pick || '—'}</div>
                <div className="mt-2 flex flex-wrap gap-1">
                    {best.map(category => <span key={category} className="rounded bg-green-50 px-2 py-0.5 text-xs text-green-700">{category} {Number(player.z_scores?.[category] || 0).toFixed(1)}</span>)}
                </div>
            </div>
            <div className="text-right">
                <div className="text-lg font-bold">{Number(player.score ?? player.total_z ?? 0).toFixed(1)}</div>
                {player.availability_probability != null && <div className="text-xs text-blue-600">{player.availability_probability}%</div>}
            </div>
        </div>
    );
};

const AdviceLane = ({ lane, players, onPlayerClick, isPostDraft, startIndex }) => {
    if (!players?.length) return null;
    const meta = laneMeta[lane] || lane;
    return (
        <div className="border-t">
            <div className="px-4 pt-3">
                <h3 className="text-sm font-semibold text-gray-800">{meta}</h3>
            </div>
            <div className="divide-y">
                {players.map((player, index) => (
                    <AdvicePlayerRow key={player.player_id || player.name} player={player} index={startIndex + index} onPlayerClick={onPlayerClick} />
                ))}
            </div>
        </div>
    );
};

const RecommendedPicks = ({ advice, players, onPlayerClick, isPostDraft }) => {
    const byKey = new Map((players || []).map(player => [player.player_id || player.name, player]));
    const hydrate = row => {
        if (!row) return null;
        const current = byKey.get(row.player_id) || byKey.get(row.name);
        return current ? { ...row, ...current } : null;
    };
    const fallback = (players || []).slice(0, 6);
    const advisedPrimary = hydrate(advice?.primary);
    const primary = advisedPrimary || fallback[0];
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
    const hasAdvice = Boolean(advisedPrimary);
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
                    <h2 className="font-bold">{isPostDraft ? 'Свободные агенты' : 'Пики'}</h2>
                    <span className="text-sm text-gray-400">Top {list.length}</span>
                </div>
            </div>
            {primary && !isPostDraft && <AdvicePlayerRow player={primary} index={1} onPlayerClick={onPlayerClick} featured />}
            {isPostDraft && fallback.map((player, index) => <AdvicePlayerRow key={player.player_id || player.name} player={player} index={index + 1} onPlayerClick={onPlayerClick} />)}
            {!isPostDraft && lanes.map(([lane, lanePlayers]) => {
                const startIndex = cursor;
                cursor += lanePlayers.length;
                return <AdviceLane key={lane} lane={lane} players={lanePlayers} onPlayerClick={onPlayerClick} isPostDraft={isPostDraft} startIndex={startIndex} />;
            })}
            {!list.length && <div className="p-8 text-center text-sm text-gray-400">Нет доступных рекомендаций</div>}
        </section>
    );
};

const RosterCard = ({ roster, onPlayerClick }) => <section className="h-full overflow-hidden rounded-xl border bg-white shadow-sm"><div className="border-b p-4"><h2 className="font-bold">Состав</h2></div><div className="divide-y">{roster.map((player, index) => <div key={player.player_id || player.name} className="flex items-center justify-between gap-3 p-3 text-sm"><div><span className="mr-2 text-gray-400">{index + 1}</span><button onClick={() => onPlayerClick?.(player)} className="font-medium hover:text-blue-600">{player.name}</button><div className="ml-6 text-xs text-gray-400">{player.position || '—'} · #{player.draft_pick || '—'}</div></div><div className={player.total_z == null ? 'text-gray-400' : player.total_z >= 0 ? 'font-bold text-green-600' : 'font-bold text-red-600'}>{player.total_z == null ? '—' : player.total_z.toFixed(1)}</div></div>)}{!roster.length && <div className="p-10 text-center text-gray-400">Пусто</div>}</div></section>;

const RosterZTable = ({ roster, puntCategories, onPlayerClick }) => {
    const [sortBy, setSortBy] = useState('total_z');
    const [sortDir, setSortDir] = useState('desc');
    const sortedRoster = useMemo(() => [...roster].sort((left, right) => {
        if (sortBy === 'name') {
            return sortDir === 'asc' ? left.name.localeCompare(right.name) : right.name.localeCompare(left.name);
        }
        const leftValue = sortBy === 'total_z' ? calculateStrategyZ(left, puntCategories) : Number(left.z_scores?.[sortBy] || 0);
        const rightValue = sortBy === 'total_z' ? calculateStrategyZ(right, puntCategories) : Number(right.z_scores?.[sortBy] || 0);
        return sortDir === 'asc' ? leftValue - rightValue : rightValue - leftValue;
    }), [roster, puntCategories, sortBy, sortDir]);
    const handleSort = column => {
        if (sortBy === column) setSortDir(current => current === 'asc' ? 'desc' : 'asc');
        else {
            setSortBy(column);
            setSortDir(column === 'name' ? 'asc' : 'desc');
        }
    };
    const SortIcon = ({ column }) => <span className="ml-1 text-gray-400">{sortBy === column ? (sortDir === 'asc' ? '↑' : '↓') : '⇅'}</span>;

    return <section className="overflow-hidden rounded-xl border bg-white shadow-sm">
        <div className="flex items-center justify-between border-b p-4"><h2 className="font-bold">Состав</h2><span className="text-sm text-gray-400">{roster.length}</span></div>
        <div className="overflow-x-auto"><table className="min-w-full border-collapse bg-white text-sm">
            <thead><tr className="bg-gray-100">
                <th onClick={() => handleSort('name')} className="cursor-pointer whitespace-nowrap border p-2 text-left hover:bg-gray-200">Игрок<SortIcon column="name" /></th>
                <th className="border p-2">NBA</th><th className="border p-2">GP</th><th className="border p-2">Пик</th>
                <th onClick={() => handleSort('total_z')} className="cursor-pointer whitespace-nowrap border p-2 hover:bg-gray-200">{puntCategories.length ? 'Z стратегии' : 'Total Z'}<SortIcon column="total_z" /></th>
                {CATEGORIES.map(category => <th key={category} onClick={() => handleSort(category)} className={`cursor-pointer whitespace-nowrap border p-2 hover:bg-gray-200 ${puntCategories.includes(category) ? 'opacity-50' : ''}`}>{category}<SortIcon column={category} /></th>)}
            </tr></thead>
            <tbody>{sortedRoster.map(player => {
                const total = calculateStrategyZ(player, puntCategories);
                return <tr key={player.player_id || player.name} onClick={() => onPlayerClick?.(player)} className="cursor-pointer hover:bg-gray-50">
                    <td className="whitespace-nowrap border p-2 font-medium text-blue-600 hover:underline">{player.name} <span className="text-xs font-normal text-gray-500">({player.position || '—'})</span></td>
                    <td className="border p-2 text-center">{player.nba_team || '—'}</td><td className="border p-2 text-center">{player.games_played || '—'}</td><td className="border p-2 text-center">{player.draft_pick ? `#${player.draft_pick}` : '—'}</td>
                    <td className={`border p-2 text-center font-bold ${zTextTone(total)}`}>{total.toFixed(2)}{puntCategories.length > 0 && <div className="text-xs font-normal text-gray-400">общий {calculateGeneralZ(player).toFixed(2)}</div>}</td>
                    {CATEGORIES.map(category => { const value = Number(player.z_scores?.[category] || 0); return <td key={category} className={`border p-2 text-center ${zTextTone(value)} ${puntCategories.includes(category) ? 'opacity-30' : ''}`}>{value.toFixed(2)}</td>; })}
                </tr>;
            })}</tbody>
        </table></div>
        {!roster.length && <div className="p-10 text-center text-gray-400">Состав пока пуст</div>}
    </section>;
};

const ProjectedTurns = ({ turns, simulation }) => <section className="rounded-xl border bg-white p-4 shadow-sm"><h2 className="mb-3 font-bold">Следующие ходы</h2><div className="grid gap-3 md:grid-cols-3">{turns.map(turn => { const primary = simulation?.projected_roster?.find(player => player.round === turn.round); return <div key={`${turn.round}-${turn.pick}`} className="rounded-lg border p-4"><div className="text-xs text-gray-500">R{turn.round} · #{turn.pick}</div><div className="mt-2 font-bold text-blue-700">{primary?.name || turn.targets?.[0]?.name || '—'}</div>{turn.targets?.length > 1 && <div className="mt-2 text-xs text-gray-400">{turn.targets.slice(1, 3).map(player => player.name).join(' · ')}</div>}</div>; })}</div></section>;

const SimulationView = ({ recommendations, selectedSimulation, simulationResults, rankedSimulationSlots, selectedSlotRank, effectiveSimulationRuns, simulationLoading, setSimulationSlot, puntCategories, teamCount, onPlayerClick, isPostDraft, benchmark, benchmarkLoading, benchmarkError, runBenchmark }) => {
    const activeCategoryCount = CATEGORIES.length;
    return <div className="space-y-4"><section className="rounded border bg-white p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><div className="font-bold">Слот {selectedSimulation.slot}</div><div className="text-sm text-gray-500">{recommendations.simulation.mode === 'all_slots' ? `#${selectedSlotRank} / ${rankedSimulationSlots.length}` : ''}{effectiveSimulationRuns ? ` · ${effectiveSimulationRuns}` : ''}{simulationLoading ? ' · …' : ''}</div></div>{recommendations.simulation.mode === 'all_slots' && <div className="flex flex-wrap gap-1">{simulationResults.map(result => <button key={result.slot} onClick={() => setSimulationSlot(result.slot)} className={`h-9 w-9 rounded border text-sm font-medium ${selectedSimulation.slot === result.slot ? 'border-blue-600 bg-blue-600 text-white' : 'bg-white text-gray-600'}`}>{result.slot}</button>)}</div>}</div>{!isPostDraft && selectedSimulation.round_targets?.length > 0 && <div className="mt-4 text-sm font-medium">{selectedSimulation.round_targets.map(round => round.pick).join(' · ')}</div>}</section><section className="grid grid-cols-2 gap-2 md:grid-cols-5"><MetricCard label="Категории" value={`${selectedSimulation.average_category_wins?.toFixed(2) || '—'} / ${activeCategoryCount}`} /><MetricCard label="Место" value={`${selectedSimulation.average_league_rank?.toFixed(1) || '—'} / ${teamCount}`} /><MetricCard label="Топ-4" value={`${selectedSimulation.top_four_strength_rate ?? selectedSimulation.top_four_probability ?? '—'}%`} /><MetricCard label="Top-N" value={`${selectedSimulation.projected_top_n_strength_rate ?? selectedSimulation.playoff_probability ?? '—'}%`} /><MetricCard label="GP" value={selectedSimulation.average_games_played ?? '—'} /></section>{!isPostDraft && <SimulationRosterTable recommendations={recommendations} simulation={selectedSimulation} onPlayerClick={onPlayerClick} />}<BenchmarkPanel benchmark={benchmark} loading={benchmarkLoading} error={benchmarkError} onRun={runBenchmark} disabled={isPostDraft} /><section className="rounded border bg-white p-4"><h2 className="mb-3 font-bold">Категории</h2><div className="flex flex-wrap justify-center gap-2">{CATEGORIES.map(category => { const rank = selectedSimulation.category_ranks?.[category]; const margin = selectedSimulation.category_margin?.[category]; return <div key={category} style={balancedCategoryCardStyle(CATEGORIES.length)} className={`rounded border p-3 ${puntCategories.includes(category) ? 'opacity-40' : ''}`}><div className="text-xs text-gray-500">{category} · #{rank ?? '—'}</div><div className={`font-bold ${margin > 0 ? 'text-green-600' : margin < 0 ? 'text-red-600' : 'text-gray-500'}`}>{margin != null ? `${margin > 0 ? '+' : ''}${margin.toFixed(1)}` : '—'}</div></div>; })}</div></section></div>;
};

const BenchmarkPanel = ({ benchmark, loading, error, onRun, disabled = false }) => {
    const comparisonByStrategy = Object.fromEntries((benchmark?.comparisons || []).map(row => [row.strategy, row]));
    return <section className="overflow-hidden rounded border bg-white"><div className="flex flex-wrap items-center justify-between gap-3 border-b p-4"><h2 className="font-bold">Бенчмарк</h2><button type="button" disabled={loading || disabled} onClick={onRun} className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50">{loading ? 'Счёт…' : benchmark ? 'Пересчитать' : 'Сравнить'}</button></div>{error && <div className="bg-red-50 p-4 text-sm text-red-700">{error}</div>}{benchmark && <div className="grid gap-3 p-4 md:grid-cols-3">{benchmark.strategies.map(strategy => { const comparison = comparisonByStrategy[strategy.id]; const delta = comparison?.delta_category_wins; return <div key={strategy.id} className="rounded border p-4"><div className="font-semibold">{strategy.label}</div><div className="mt-2 text-2xl font-bold">{strategy.average_category_wins.toFixed(2)} / {benchmark.categories.length}</div><div className="text-xs text-gray-500">#{strategy.average_league_rank.toFixed(2)} · top-4 {strategy.top_four_rate}%</div>{comparison && <div className={`mt-2 text-sm font-medium ${delta > 0 ? 'text-green-600' : delta < 0 ? 'text-red-600' : 'text-gray-600'}`}>{delta > 0 ? '+' : ''}{delta.toFixed(3)}</div>}</div>; })}</div>}</section>;
};

const SimulationRosterTable = ({ recommendations, simulation, onPlayerClick }) => <section className="overflow-hidden rounded border bg-white"><div className="flex items-center justify-between border-b p-4"><h2 className="font-bold">Прогон</h2><span className="text-sm text-gray-400">{simulation.projected_roster?.length || 0}</span></div><div className="overflow-x-auto"><table className="min-w-full text-sm"><thead><tr className="bg-gray-100"><th className="border p-2">R</th><th className="border p-2">Пик</th><th className="border p-2 text-left">Игрок</th><th className="border p-2">Поз.</th><th className="border p-2">GP</th><th className="border p-2">Рынок</th><th className="border p-2">Цена</th><th className="border p-2">%</th><th className="border p-2">Выбор</th></tr></thead><tbody>{(simulation.round_targets || []).map(round => { const primary = simulation.projected_roster?.find(player => player.round === round.round); const profile = recommendations.players.find(player => player.name === primary?.name); const alternatives = (round.targets || []).filter(player => player.name !== primary?.name); const price = draftPrice(primary); return <tr key={round.round} className="hover:bg-gray-50"><td className="border p-2 text-center">{round.round}</td><td className="border p-2 text-center">#{round.pick}</td><td className="border p-2">{primary ? <button onClick={() => onPlayerClick?.(profile || primary)} className="font-medium text-blue-600 hover:underline">{primary.name}</button> : '—'}{alternatives.length > 0 && <div className="mt-1 text-xs text-gray-400">{alternatives.map(player => player.name).join(' · ')}</div>}</td><td className="border p-2 text-center">{primary?.position || '—'}</td><td className="border p-2 text-center">{primary?.games_played || '—'}</td><td className="border p-2 text-center">{primary?.espn_market_pick?.toFixed(1) || '—'}</td><td className={`border p-2 text-center ${price.tone}`}>{price.label}</td><td className="border p-2 text-center">{primary ? `${primary.availability_frequency}%` : '—'}</td><td className="border p-2 text-center">{primary ? `${primary.selection_frequency}%` : '—'}</td></tr>; })}</tbody></table></div></section>;


export default DraftAssistant;
