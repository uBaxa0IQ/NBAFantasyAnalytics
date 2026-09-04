import React, { useState, useEffect } from 'react';
import api from '../api';
import { saveState, loadState, StorageKeys } from '../utils/statePersistence';
import PlayerFiltersModal from './PlayerFiltersModal';
import { getTrendColor } from '../utils/trendColors';
import { LEAGUE_CATEGORIES as CATEGORIES } from '../utils/categories';
const POSITIONS = ['PG', 'SG', 'SF', 'PF', 'C'];

const FreeAgents = ({ onPlayerClick, period, puntCategories, colorByTrend = false, mainTeam, calculationEngine = 'calendar' }) => {
    const savedState = loadState(StorageKeys.FREE_AGENTS, {});
    const [position, setPosition] = useState(savedState.position || '');
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const personalized = calculationEngine === 'calendar' && mainTeam;
    const [sortBy, setSortBy] = useState(personalized ? 'calendar_fit' : 'total_z');
    const [sortDir, setSortDir] = useState('desc');
    const [isFiltersModalOpen, setIsFiltersModalOpen] = useState(false);
    const [filters, setFilters] = useState(savedState.filters || {});
    const [playerTrends, setPlayerTrends] = useState({});

    useEffect(() => {
        setSortBy(personalized ? 'calendar_fit' : 'total_z');
    }, [personalized]);

    useEffect(() => {
        setLoading(true);
        const endpoint = personalized ? `/free-agent-recommendations/${mainTeam}` : '/free-agents';
        api.get(endpoint, { params: {
            period,
            position: position || undefined,
            punt_categories: puntCategories.join(','),
        } })
            .then(res => {
                setData(res.data);
                setLoading(false);
            })
            .catch(err => {
                console.error(err);
                setLoading(false);
            });
    }, [period, position, mainTeam, puntCategories, personalized]);

    // Загружаем тренды, если включена окраска по тренду
    useEffect(() => {
        if (colorByTrend) {
            const puntCatsParam = puntCategories.length > 0 ? `&punt_categories=${puntCategories.join(',')}` : '';
            api.get(`/all-players-trends?${puntCatsParam}`)
                .then(res => {
                    setPlayerTrends(res.data || {});
                })
                .catch(err => {
                    console.error('Error fetching player trends:', err);
                    setPlayerTrends({});
                });
        } else {
            setPlayerTrends({});
        }
    }, [colorByTrend, puntCategories]);

    // Сохранение состояния при изменении
    useEffect(() => {
        saveState(StorageKeys.FREE_AGENTS, {
            position,
            filters
        });
    }, [position, filters]);


    const calculateTotalZ = (player) => {
        let total = 0;
        CATEGORIES.forEach(cat => {
            if (!puntCategories.includes(cat)) {
                total += player.z_scores[cat] || 0;
            }
        });
        return total;
    };

    const calculateGeneralZ = (player) => CATEGORIES.reduce(
        (total, cat) => total + (player.z_scores[cat] || 0),
        0,
    );

    const handleSort = (column) => {
        if (sortBy === column) {
            setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
        } else {
            setSortBy(column);
            setSortDir('desc');
        }
    };

    let sortedPlayers = data ? [...data.players].sort((a, b) => {
        let valA, valB;

        if (sortBy === 'total_z') {
            valA = calculateTotalZ(a);
            valB = calculateTotalZ(b);
        } else if (sortBy === 'calendar_fit') {
            valA = a.matchup_gain ?? a.lineup_gain ?? 0;
            valB = b.matchup_gain ?? b.lineup_gain ?? 0;
        } else if (sortBy === 'lineup_gain' || sortBy === 'selected_games') {
            valA = a[sortBy] || 0;
            valB = b[sortBy] || 0;
        } else if (sortBy === 'name') {
            return sortDir === 'asc' ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
        } else {
            valA = a.z_scores[sortBy] || 0;
            valB = b.z_scores[sortBy] || 0;
        }

        return sortDir === 'asc' ? valA - valB : valB - valA;
    }) : [];

    // Фильтры по статистике
    if (Object.keys(filters).length > 0) {
        sortedPlayers = sortedPlayers.filter(player => {
            if (!player.stats) return false;
            
            return Object.entries(filters).every(([category, minValue]) => {
                const playerValue = player.stats[category];
                if (playerValue === undefined || playerValue === null) return false;
                
                // Для процентных категорий значения могут быть в формате 0-1 или 0-100
                // Нормализуем к 0-100 для сравнения
                let normalizedPlayerValue = playerValue;
                if (['FG%', 'FT%', '3PT%'].includes(category)) {
                    // Если значение меньше 1, значит это 0-1 формат, конвертируем в проценты
                    if (normalizedPlayerValue < 1.0) {
                        normalizedPlayerValue = normalizedPlayerValue * 100;
                    }
                }
                
                return normalizedPlayerValue > minValue;
            });
        });
    }

    const SortIcon = ({ column }) => {
        if (sortBy !== column) return <span className="text-gray-400 ml-1">⇅</span>;
        return sortDir === 'asc' ? <span className="ml-1">↑</span> : <span className="ml-1">↓</span>;
    };

    const handleApplyFilters = (newFilters) => {
        setFilters(newFilters);
    };

    const hasActiveFilters = Object.keys(filters).length > 0;

    return (
        <div className="p-4">
            <div className="mb-4 flex gap-4 items-center flex-wrap">
                <select
                    className="border p-2 rounded"
                    value={position}
                    onChange={e => setPosition(e.target.value)}
                >
                    <option value="">Все позиции</option>
                    {POSITIONS.map(pos => (
                        <option key={pos} value={pos}>{pos}</option>
                    ))}
                </select>

                <button
                    onClick={() => setIsFiltersModalOpen(true)}
                    className={`px-4 py-2 border rounded font-medium transition-colors ${
                        hasActiveFilters
                            ? 'bg-blue-600 text-white border-blue-600 hover:bg-blue-700'
                            : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-100'
                    }`}
                >
                    Фильтры {hasActiveFilters && `(${Object.keys(filters).length})`}
                </button>
            </div>

            {personalized && data && (
                <div className="mb-4 p-3 rounded bg-blue-50 text-sm text-blue-900">
                    {data.note || 'Прирост после одиночной замены по оставшемуся календарю и слотам лиги.'}
                </div>
            )}

            {loading && <div>Загрузка...</div>}

            {data && (
                <div className="overflow-x-auto">
                    <table className="min-w-full bg-white border">
                        <thead>
                            <tr className="bg-gray-100">
                                <th className="p-2 border cursor-pointer hover:bg-gray-200" onClick={() => handleSort('name')}>
                                    Игрок <SortIcon column="name" />
                                </th>
                                <th className="p-2 border">Позиция</th>
                                <th className="p-2 border">NBA Team</th>
                                {personalized && (
                                    <>
                                        <th className="p-2 border cursor-pointer hover:bg-gray-200" onClick={() => handleSort('calendar_fit')}>
                                            Эффект <SortIcon column="calendar_fit" />
                                        </th>
                                        <th className="p-2 border">Кого убрать</th>
                                        <th className="p-2 border cursor-pointer hover:bg-gray-200" onClick={() => handleSort('selected_games')}>
                                            Игр в составе <SortIcon column="selected_games" />
                                        </th>
                                    </>
                                )}
                                <th className="p-2 border cursor-pointer hover:bg-gray-200" onClick={() => handleSort('total_z')}>
                                    {puntCategories.length ? 'Z стратегии' : 'Total Z'} <SortIcon column="total_z" />
                                </th>
                                {CATEGORIES.map(cat => (
                                    <th key={cat} className={`p-2 border cursor-pointer hover:bg-gray-200 ${puntCategories.includes(cat) ? 'opacity-50' : ''}`} onClick={() => handleSort(cat)}>
                                        {cat} <SortIcon column={cat} />
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {sortedPlayers.map(player => (
                                <tr
                                    key={player.name}
                                    className="hover:bg-gray-50 cursor-pointer"
                                    onClick={() => onPlayerClick && onPlayerClick(player)}
                                >
                                    <td className="p-2 border font-medium text-blue-600 hover:underline">
                                        {player.name}
                                    </td>
                                    <td className="p-2 border text-center text-sm">{player.position}</td>
                                    <td className="p-2 border text-center text-sm">{player.nba_team}</td>
                                    {personalized && (
                                        <>
                                            <td className={`p-2 border text-center font-bold ${player.lineup_gain > 0 ? 'text-green-600' : 'text-red-600'}`}>
                                                <div>{player.matchup_gain > 0 ? '+' : ''}{(player.matchup_gain ?? player.lineup_gain).toFixed(3)} {data.method === 'opponent_category_utility' ? 'балла категорий' : 'Z'}</div>
                                                <div className="text-xs font-normal text-gray-500">
                                                    {player.player_games_delta > 0 ? '+' : ''}{player.player_games_delta} player-games
                                                </div>
                                            </td>
                                            <td className="p-2 border text-center text-sm">{player.drop_player}</td>
                                            <td className="p-2 border text-center">{player.selected_games}</td>
                                        </>
                                    )}
                                    <td className="p-2 border font-bold text-center">
                                        {colorByTrend && playerTrends[player.name] !== undefined ? (
                                            <span style={{ color: getTrendColor(playerTrends[player.name]) }}>
                                                {calculateTotalZ(player).toFixed(2)}
                                            </span>
                                        ) : (
                                            calculateTotalZ(player).toFixed(2)
                                        )}
                                        {puntCategories.length > 0 && (
                                            <div className="text-xs font-normal text-gray-400">общий {calculateGeneralZ(player).toFixed(2)}</div>
                                        )}
                                    </td>
                                    {CATEGORIES.map(cat => {
                                        const val = player.z_scores[cat] || 0;
                                        const isPunted = puntCategories.includes(cat);
                                        let colorClass = val > 0 ? 'text-green-600' : 'text-red-600';
                                        if (val === 0) colorClass = 'text-gray-400';

                                        return (
                                            <td key={cat} className={`p-2 border text-center ${colorClass} ${isPunted ? 'opacity-30' : ''}`}>
                                                {val.toFixed(2)}
                                            </td>
                                        );
                                    })}
                                </tr>
                            ))}
                            {sortedPlayers.length === 0 && (
                                <tr>
                                    <td colSpan={CATEGORIES.length + (personalized ? 7 : 4)} className="p-6 text-center text-gray-500">
                                        На оставшихся игровых днях нет кандидатов, которые попадут в активный состав.
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            )}

            <PlayerFiltersModal
                isOpen={isFiltersModalOpen}
                onClose={() => setIsFiltersModalOpen(false)}
                onApply={handleApplyFilters}
                initialFilters={filters}
            />
        </div>
    );
};

export default FreeAgents;
