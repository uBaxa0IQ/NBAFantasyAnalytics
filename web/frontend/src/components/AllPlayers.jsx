import React, { useState, useEffect } from 'react';
import api from '../api';
import { saveState, loadState, StorageKeys } from '../utils/statePersistence';
import PlayerFiltersModal from './PlayerFiltersModal';

const CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'FG%', 'FT%', '3PT%', 'A/TO'];
const POSITIONS = ['PG', 'SG', 'SF', 'PF', 'C'];

const AllPlayers = ({ onPlayerClick, period, puntCategories, simulationMode }) => {
    const savedState = loadState(StorageKeys.ALL_PLAYERS, {});
    const [teams, setTeams] = useState([]);
    const [selectedTeam, setSelectedTeam] = useState(savedState.selectedTeam || '');
    const [position, setPosition] = useState(savedState.position || '');
    const [searchQuery, setSearchQuery] = useState(savedState.searchQuery || '');
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [sortBy, setSortBy] = useState(savedState.sortBy || 'total_z');
    const [sortDir, setSortDir] = useState(savedState.sortDir || 'desc');
    const [isFiltersModalOpen, setIsFiltersModalOpen] = useState(false);
    const [filters, setFilters] = useState(savedState.filters || {});

    useEffect(() => {
        api.get('/teams').then(res => setTeams(res.data));
    }, []);

    useEffect(() => {
        setLoading(true);
        
        // Определяем exclude_ir на основе simulation_mode
        const exclude_ir = (simulationMode === 'exclude_ir');
        
        api.get(`/all-players?period=${period}&exclude_ir=${exclude_ir}`)
            .then(res => {
                setData(res.data);
                setLoading(false);
            })
            .catch(err => {
                console.error(err);
                setLoading(false);
            });
    }, [period, simulationMode]);

    // Сохранение состояния при изменении
    useEffect(() => {
        saveState(StorageKeys.ALL_PLAYERS, {
            selectedTeam,
            position,
            searchQuery,
            sortBy,
            sortDir,
            filters
        });
    }, [selectedTeam, position, searchQuery, sortBy, sortDir, filters]);


    const calculateTotalZ = (player) => {
        let total = 0;
        CATEGORIES.forEach(cat => {
            if (!puntCategories.includes(cat)) {
                total += player.z_scores[cat] || 0;
            }
        });
        return total;
    };

    const handleSort = (column) => {
        if (sortBy === column) {
            setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
        } else {
            setSortBy(column);
            setSortDir('desc');
        }
    };

    let filteredPlayers = data ? [...data.players] : [];

    // Фильтр по команде
    if (selectedTeam) {
        filteredPlayers = filteredPlayers.filter(p => p.fantasy_team_id === parseInt(selectedTeam));
    }

    // Фильтр по позиции
    if (position) {
        filteredPlayers = filteredPlayers.filter(p => p.position && p.position.includes(position));
    }

    // Фильтр по имени
    if (searchQuery) {
        filteredPlayers = filteredPlayers.filter(p =>
            p.name.toLowerCase().includes(searchQuery.toLowerCase())
        );
    }

    // Фильтры по статистике
    if (Object.keys(filters).length > 0) {
        filteredPlayers = filteredPlayers.filter(player => {
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

    // Сортировка
    filteredPlayers.sort((a, b) => {
        let valA, valB;

        if (sortBy === 'total_z') {
            valA = calculateTotalZ(a);
            valB = calculateTotalZ(b);
        } else if (sortBy === 'name') {
            return sortDir === 'asc' ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
        } else {
            valA = a.z_scores[sortBy] || 0;
            valB = b.z_scores[sortBy] || 0;
        }

        return sortDir === 'asc' ? valA - valB : valB - valA;
    });

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
                    value={selectedTeam}
                    onChange={e => setSelectedTeam(e.target.value)}
                >
                    <option value="">Все команды</option>
                    {teams.map(t => (
                        <option key={t.team_id} value={t.team_id}>{t.team_name}</option>
                    ))}
                </select>

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

                <input
                    type="text"
                    placeholder="Поиск по имени..."
                    className="border p-2 rounded flex-1 min-w-[200px]"
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                />

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

            {loading && <div>Загрузка...</div>}

            {data && (
                <div className="overflow-x-auto">
                    <table className="min-w-full bg-white border">
                        <thead>
                            <tr className="bg-gray-100">
                                <th className="p-2 border cursor-pointer hover:bg-gray-200" onClick={() => handleSort('name')}>
                                    Игрок <SortIcon column="name" />
                                </th>
                                <th className="p-2 border">Поз.</th>
                                <th className="p-2 border">NBA</th>
                                <th className="p-2 border">Fantasy Команда</th>
                                <th className="p-2 border cursor-pointer hover:bg-gray-200" onClick={() => handleSort('total_z')}>
                                    Total Z <SortIcon column="total_z" />
                                </th>
                                {CATEGORIES.map(cat => (
                                    <th key={cat} className={`p-2 border cursor-pointer hover:bg-gray-200 ${puntCategories.includes(cat) ? 'opacity-50' : ''}`} onClick={() => handleSort(cat)}>
                                        {cat} <SortIcon column={cat} />
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {filteredPlayers.map(player => (
                                <tr
                                    key={`${player.name}-${player.fantasy_team_id}`}
                                    className="hover:bg-gray-50 cursor-pointer"
                                    onClick={() => onPlayerClick && onPlayerClick(player)}
                                >
                                    <td className="p-2 border font-medium text-blue-600 hover:underline">
                                        {player.name}
                                    </td>
                                    <td className="p-2 border text-center text-sm">{player.position}</td>
                                    <td className="p-2 border text-center text-sm">{player.nba_team}</td>
                                    <td className="p-2 border text-sm">{player.fantasy_team}</td>
                                    <td className="p-2 border font-bold text-center">
                                        {calculateTotalZ(player).toFixed(2)}
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

export default AllPlayers;
