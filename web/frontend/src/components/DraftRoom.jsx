import React, { useMemo, useState } from 'react';
import { LEAGUE_CATEGORIES as CATEGORIES } from '../utils/categories';

const formatStat = (category, value) => {
    if (value == null || Number.isNaN(Number(value))) return '—';
    const number = Number(value);
    if (['FG%', 'FT%', '3PT%'].includes(category)) return `${(number <= 1 ? number * 100 : number).toFixed(1)}%`;
    return number.toFixed(category === 'A/TO' ? 2 : 1);
};

const strategyZ = (player, puntCategories, categories) => (categories || CATEGORIES).reduce((total, category) => (
    puntCategories.includes(category) ? total : total + Number(player?.z_scores?.[category] || 0)
), 0);

const tone = value => {
    const score = Number(value || 0);
    if (score > 0) return 'text-green-600';
    if (score < 0) return 'text-red-600';
    return 'text-gray-400';
};

const rankTone = rank => (rank <= 4 ? 'text-green-700' : rank >= 8 ? 'text-red-700' : '');

const h2hLabel = row => (row?.matchup_wins == null ? '—' : `${row.matchup_wins}-${row.matchup_losses}-${row.matchup_ties}`);

const DraftRoom = ({
    categories = CATEGORIES,
    puntCategories = [],
    onPlayerClick,
    roundLabel,
    clockLabel,
    yourPick,
    picksUntil,
    rosterCount,
    rosterLimit,
    rankLabel,
    recordLabel,
    headerExtra,
    showHint,
    onToggleHint,
    showSimulation,
    onToggleSimulation,
    hint,
    players = [],
    onDraftPlayer,
    highlightedPlayerId,
    pickLog = [],
    standingsTitle,
    roundOptions = [],
    viewRound,
    onViewRound,
    standings = [],
    totalsAreZ = false,
    yourRoster = [],
    onInspectTeam,
    inspected,
    simulationContent,
}) => {
    const [search, setSearch] = useState('');
    const [position, setPosition] = useState('ALL');
    const [picksExpanded, setPicksExpanded] = useState(false);
    const [rosterOpen, setRosterOpen] = useState(true);
    const [leagueOpen, setLeagueOpen] = useState(true);

    const visiblePlayers = useMemo(() => players.filter(player => {
        const matchesPosition = position === 'ALL' || String(player.position || '').includes(position);
        const matchesSearch = !search || String(player.name || '').toLowerCase().includes(search.toLowerCase());
        return matchesPosition && matchesSearch;
    }), [players, search, position]);

    const picksByRound = useMemo(() => {
        const groups = new Map();
        pickLog.forEach(pick => {
            const round = pick.round || 1;
            if (!groups.has(round)) groups.set(round, []);
            groups.get(round).push(pick);
        });
        return [...groups.entries()].sort((left, right) => left[0] - right[0]).map(([round, picks]) => ({ round, picks }));
    }, [pickLog]);
    const recentPicks = picksExpanded ? null : [...pickLog].slice(-8).reverse();
    const you = standings.find(row => row.is_you);
    const focus = inspected || you;
    const roster = inspected ? (inspected.roster || []) : yourRoster;
    const rosterTitle = inspected ? inspected.team_name : 'Ваш состав';

    return (
        <div className="space-y-4">
            <section className="grid grid-cols-2 gap-3 lg:grid-cols-5">
                <Metric label="Сейчас" value={clockLabel || '—'} />
                <Metric label="Раунд" value={roundLabel || '—'} />
                <Metric label="Ваш пик" value={yourPick ? `#${yourPick}` : '—'} detail={picksUntil == null ? null : `через ${picksUntil}`} />
                <Metric label="Состав" value={`${rosterCount ?? 0} / ${rosterLimit || '—'}`} />
                <Metric label="Место" value={rankLabel || '—'} detail={recordLabel} />
            </section>

            {focus && <section>
                <div className="mb-2 text-xs text-gray-500">{focus.team_name}{focus.is_you ? ' · вы' : ''}</div>
                <div className="flex flex-wrap gap-2">{categories.map(category => {
                    const rank = focus.category_ranks?.[category];
                    const total = focus.category_totals?.[category];
                    return <div key={category} className={`min-w-24 flex-1 rounded-lg border bg-white p-2 ${puntCategories.includes(category) ? 'opacity-60' : ''}`}>
                        <div className="text-xs text-gray-500">{category}{rank ? ` · #${rank}` : ''}</div>
                        <div className={`text-sm font-bold ${rankTone(rank) || 'text-gray-700'}`}>{totalsAreZ ? (total == null || Number.isNaN(Number(total)) ? '—' : `${Number(total) > 0 ? '+' : ''}${Number(total).toFixed(1)}`) : formatStat(category, total)}</div>
                    </div>;
                })}</div>
            </section>}

            <section className="flex flex-wrap items-center justify-between gap-3">
                <div className="inline-flex rounded-lg border border-gray-300 bg-gray-50 p-1">
                    <button type="button" onClick={onToggleHint} className={`rounded-md px-3 py-1.5 text-sm ${showHint ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-600'}`}>Подсказка</button>
                    <button type="button" onClick={onToggleSimulation} className={`rounded-md px-3 py-1.5 text-sm ${showSimulation ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-600'}`}>Симуляция</button>
                </div>
                {headerExtra}
            </section>

            {showHint && hint && (
                <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-blue-200 bg-blue-50 p-4">
                    <div>
                        <div className="text-xs font-medium uppercase tracking-wide text-blue-700">{hint.label || 'Взял бы'}</div>
                        <button type="button" onClick={() => onPlayerClick?.(hint.player)} className="mt-1 text-lg font-bold text-blue-800 hover:underline">{hint.player?.name || hint.name}</button>
                        <div className="text-xs text-blue-700">{hint.player?.position || hint.position || '—'}{hint.z != null ? ` · Z ${Number(hint.z).toFixed(2)}` : ''}</div>
                    </div>
                    {hint.onTake && <button type="button" disabled={hint.disabled} onClick={hint.onTake} className="rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">Взять</button>}
                </section>
            )}

            <section className="overflow-hidden rounded-xl border bg-white">
                <div className={`flex flex-wrap items-center justify-between gap-3 p-3 ${leagueOpen ? 'border-b' : ''}`}>
                    <button type="button" onClick={() => setLeagueOpen(open => !open)} className="font-bold">{standingsTitle || 'Лига'}</button>
                    <div className="flex items-center gap-3">
                        {leagueOpen && roundOptions.length > 1 && (
                            <select value={viewRound || ''} onChange={event => onViewRound?.(Number(event.target.value))} className="rounded border p-1.5 text-sm">
                                {roundOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
                            </select>
                        )}
                        <button type="button" onClick={() => setLeagueOpen(open => !open)} className="text-sm text-blue-700">{leagueOpen ? 'Скрыть' : 'Показать'}</button>
                    </div>
                </div>
                {leagueOpen && (!standings.length ? <div className="p-8 text-center text-sm text-gray-400">Таблица появится после закрытого раунда</div> : (
                    <div className="overflow-x-auto">
                        <table className="min-w-full text-sm">
                            <thead><tr className="bg-gray-100">
                                <th className="border p-2">#</th>
                                <th className="border p-2 text-left">Команда</th>
                                <th className="border p-2">1v1</th>
                                <th className="border p-2">Кат</th>
                                {categories.map(category => <th key={category} className={`border p-2 ${puntCategories.includes(category) ? 'opacity-50' : ''}`}>{category}</th>)}
                            </tr></thead>
                            <tbody>{standings.map(row => (
                                <tr key={row.slot || row.team_id} onClick={() => onInspectTeam?.(row)} className={`cursor-pointer ${row.is_you ? 'bg-blue-50' : 'hover:bg-gray-50'}`}>
                                    <td className="border p-2 text-center font-bold">{row.league_rank ?? '—'}</td>
                                    <td className="border p-2">{row.team_name}{row.is_you ? ' · вы' : ''}</td>
                                    <td className="border p-2 text-center font-bold">{h2hLabel(row)}</td>
                                    <td className="border p-2 text-center">{row.category_wins == null ? '—' : Number(row.category_wins).toFixed(2)}</td>
                                    {categories.map(category => {
                                        const rank = row.category_ranks?.[category];
                                        return <td key={category} className={`border p-2 text-center ${rankTone(rank)} ${puntCategories.includes(category) ? 'opacity-40' : ''}`}>{rank ? `#${rank}` : '—'}</td>;
                                    })}
                                </tr>
                            ))}</tbody>
                        </table>
                    </div>
                ))}
            </section>

            <section className="overflow-hidden rounded-xl border bg-white">
                <button type="button" onClick={() => setRosterOpen(open => !open)} className="flex w-full items-center justify-between gap-3 p-3 text-left">
                    <span className="font-bold">{rosterTitle} · {roster.length}</span>
                    <span className="text-sm text-blue-700">{rosterOpen ? 'Скрыть' : 'Показать'}</span>
                </button>
                {rosterOpen && (
                    <>
                        <CategoryZTable
                            players={roster.map(player => {
                                const matched = pickLog.find(pick => (
                                    (player.player_id && (pick.player?.player_id === player.player_id || pick.playerId === player.player_id))
                                    || pick.playerName === player.name
                                    || pick.player?.name === player.name
                                    || (player.draft_pick && pick.overall === player.draft_pick)
                                ));
                                return {
                                    ...player,
                                    draft_pick: player.draft_pick ?? matched?.overall,
                                    draft_round: player.draft_round ?? matched?.round,
                                };
                            })}
                            categories={categories}
                            puntCategories={puntCategories}
                            onPlayerClick={onPlayerClick}
                            showPick
                            emptyLabel="Пусто"
                        />
                        {inspected && <button type="button" onClick={() => onInspectTeam?.(null)} className="w-full border-t p-2 text-sm text-blue-700">К своему составу</button>}
                    </>
                )}
            </section>

            <section className="overflow-hidden rounded-xl border bg-white">
                <div className="flex flex-col gap-3 border-b p-3 sm:flex-row sm:items-center sm:justify-end">
                    <select value={position} onChange={event => setPosition(event.target.value)} className="rounded border p-2 text-sm"><option value="ALL">Все позиции</option>{['PG', 'SG', 'SF', 'PF', 'C'].map(item => <option key={item} value={item}>{item}</option>)}</select>
                    <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Поиск" className="min-w-0 flex-1 rounded border p-2 text-sm sm:max-w-xs" />
                </div>
                <CategoryZTable
                    players={visiblePlayers}
                    categories={categories}
                    puntCategories={puntCategories}
                    onPlayerClick={onPlayerClick}
                    onDraftPlayer={onDraftPlayer}
                    highlightedPlayerId={highlightedPlayerId}
                    showMarket
                    emptyLabel="Нет доступных игроков"
                />
            </section>

            {!!pickLog.length && <section className="overflow-hidden rounded-xl border bg-white">
                <div className="flex items-center justify-between border-b p-3">
                    <h2 className="font-bold">{picksExpanded ? 'Все пики' : 'Последние пики'}</h2>
                    {pickLog.length > 8 && <button type="button" onClick={() => setPicksExpanded(open => !open)} className="text-sm text-blue-700">{picksExpanded ? 'Свернуть' : `Показать все · ${pickLog.length}`}</button>}
                </div>
                {picksExpanded ? picksByRound.map(group => (
                    <div key={group.round} className="border-b last:border-b-0">
                        <div className="bg-gray-50 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">Раунд {group.round}</div>
                        <div className="grid sm:grid-cols-2 lg:grid-cols-4">{group.picks.map(pick => <PickCell key={pick.overall} pick={pick} onPlayerClick={onPlayerClick} />)}</div>
                    </div>
                )) : <div className="grid sm:grid-cols-2 lg:grid-cols-4">{recentPicks.map(pick => <PickCell key={pick.overall} pick={pick} onPlayerClick={onPlayerClick} />)}</div>}
            </section>}

            {showSimulation && simulationContent}
        </div>
    );
};

const marketPick = player => {
    const value = player?.espn_market_pick ?? player?.espn_adp ?? player?.espn_roto_rank;
    return value == null || Number.isNaN(Number(value)) ? null : Number(value);
};

const CategoryZTable = ({ players, categories, puntCategories, onPlayerClick, onDraftPlayer, highlightedPlayerId, showMarket = false, showPick = false, emptyLabel }) => {
    const [sortBy, setSortBy] = useState(showPick ? 'draft_pick' : 'total_z');
    const [sortDir, setSortDir] = useState(showPick ? 'asc' : 'desc');
    const handleSort = column => {
        if (sortBy === column) setSortDir(current => current === 'asc' ? 'desc' : 'asc');
        else {
            setSortBy(column);
            setSortDir(column === 'name' || column === 'espn_market_pick' || column === 'draft_pick' ? 'asc' : 'desc');
        }
    };
    const SortIcon = ({ column }) => <span className="ml-1 text-gray-400">{sortBy === column ? (sortDir === 'asc' ? '↑' : '↓') : '⇅'}</span>;
    const sorted = useMemo(() => [...players].sort((left, right) => {
        if (sortBy === 'name') return sortDir === 'asc' ? left.name.localeCompare(right.name) : right.name.localeCompare(left.name);
        const read = player => {
            if (sortBy === 'total_z') return strategyZ(player, puntCategories, categories);
            if (sortBy === 'espn_market_pick') return marketPick(player) ?? 9999;
            if (sortBy === 'draft_pick') return Number(player.draft_pick) || 9999;
            return Number(player.z_scores?.[sortBy] || 0);
        };
        return sortDir === 'asc' ? read(left) - read(right) : read(right) - read(left);
    }), [players, sortBy, sortDir, puntCategories, categories]);
    const generalZ = player => categories.reduce((total, category) => total + Number(player.z_scores?.[category] || 0), 0);

    if (!sorted.length) return <div className="border-t p-8 text-center text-sm text-gray-400">{emptyLabel}</div>;
    return (
        <div className="overflow-x-auto border-t">
            <table className="min-w-full border-collapse bg-white text-sm">
                <thead><tr className="bg-gray-100">
                    {showPick && <th onClick={() => handleSort('draft_pick')} className="cursor-pointer whitespace-nowrap border p-2 hover:bg-gray-200">Пик<SortIcon column="draft_pick" /></th>}
                    <th onClick={() => handleSort('name')} className="cursor-pointer whitespace-nowrap border p-2 text-left hover:bg-gray-200">Игрок<SortIcon column="name" /></th>
                    {showMarket && <th onClick={() => handleSort('espn_market_pick')} className="cursor-pointer whitespace-nowrap border p-2 hover:bg-gray-200">Рынок<SortIcon column="espn_market_pick" /></th>}
                    <th onClick={() => handleSort('total_z')} className="cursor-pointer whitespace-nowrap border p-2 hover:bg-gray-200">{puntCategories.length ? 'Z стратегии' : 'Total Z'}<SortIcon column="total_z" /></th>
                    {categories.map(category => <th key={category} onClick={() => handleSort(category)} className={`cursor-pointer whitespace-nowrap border p-2 hover:bg-gray-200 ${puntCategories.includes(category) ? 'opacity-50' : ''}`}>{category}<SortIcon column={category} /></th>)}
                </tr></thead>
                <tbody>{sorted.map(player => {
                    const total = strategyZ(player, puntCategories, categories);
                    const highlighted = highlightedPlayerId != null && String(highlightedPlayerId) === String(player.player_id);
                    return (
                        <tr
                            key={player.player_id || player.name}
                            onClick={() => (onDraftPlayer || onPlayerClick)?.(player)}
                            className={`cursor-pointer ${highlighted ? 'bg-blue-50' : 'hover:bg-gray-50'}`}
                        >
                            {showPick && <td className="border p-2 text-center">{player.draft_pick ? (player.draft_round ? `${player.draft_pick} · ${player.draft_round}` : player.draft_pick) : '—'}</td>}
                            <td className="whitespace-nowrap border p-2 font-medium text-blue-600">
                                <span className="hover:underline">{player.name}</span>
                                <span className="text-xs font-normal text-gray-500"> ({player.position || '—'})</span>
                            </td>
                            {showMarket && <td className="border p-2 text-center">{marketPick(player)?.toFixed(1) || '—'}</td>}
                            <td className={`border p-2 text-center font-bold ${tone(total)}`}>
                                {total.toFixed(2)}
                                {puntCategories.length > 0 && <div className="text-xs font-normal text-gray-400">общий {generalZ(player).toFixed(2)}</div>}
                            </td>
                            {categories.map(category => {
                                const value = Number(player.z_scores?.[category] || 0);
                                return <td key={category} className={`border p-2 text-center ${tone(value)} ${puntCategories.includes(category) ? 'opacity-30' : ''}`}>{value.toFixed(2)}</td>;
                            })}
                        </tr>
                    );
                })}</tbody>
            </table>
        </div>
    );
};

const Metric = ({ label, value, detail }) => (
    <div className="rounded-xl border bg-white p-4">
        <div className="text-xs text-gray-500">{label}</div>
        <div className="mt-1 text-2xl font-bold">{value}</div>
        {detail && <div className="text-xs text-gray-400">{detail}</div>}
    </div>
);

const PickCell = ({ pick, onPlayerClick }) => (
    <div className={`border-b p-3 text-sm sm:border-r ${pick.isYou ? 'bg-blue-50' : ''}`}>
        <span className="mr-2 text-gray-400">#{pick.overall}</span>
        <button type="button" onClick={() => onPlayerClick?.(pick.player || { name: pick.playerName, player_id: pick.playerId })} className="font-medium hover:text-blue-700">{pick.playerName}</button>
        <div className="ml-8 text-xs text-gray-400">{pick.teamName}</div>
    </div>
);

export default DraftRoom;
