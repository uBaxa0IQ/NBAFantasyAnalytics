import React, { useState, useEffect } from 'react';
import api from '../api';
import { saveState, loadState, StorageKeys } from '../utils/statePersistence';

const CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'FG%', 'FT%', '3PT%', 'A/TO'];

const Analytics = ({ onPlayerClick, period, puntCategories }) => {
    const [teams, setTeams] = useState([]);
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [sortBy, setSortBy] = useState('total_z');
    const [sortDir, setSortDir] = useState('desc');
    const [selectedTeam, setSelectedTeam] = useState(() => {
        const saved = loadState(StorageKeys.ANALYTICS, {});
        return saved.selectedTeam || '';
    });

    useEffect(() => {
        api.get('/teams').then(res => setTeams(res.data));
    }, []);

    // Сохранение состояния при изменении selectedTeam
    useEffect(() => {
        saveState(StorageKeys.ANALYTICS, { selectedTeam });
    }, [selectedTeam]);

    useEffect(() => {
        if (selectedTeam) {
            setLoading(true);
            // В аналитике команды IR игроки всегда включены
            api.get(`/analytics/${selectedTeam}?period=${period}&exclude_ir=false`)
                .then(res => {
                    setData(res.data);
                    setLoading(false);
                })
                .catch(err => {
                    console.error(err);
                    setLoading(false);
                });
        }
    }, [selectedTeam, period]);


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

    const sortedPlayers = data ? [...data.players].sort((a, b) => {
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
    }) : [];

    const SortIcon = ({ column }) => {
        if (sortBy !== column) return <span className="text-gray-400 ml-1">⇅</span>;
        return sortDir === 'asc' ? <span className="ml-1">↑</span> : <span className="ml-1">↓</span>;
    };

    return (
        <div className="p-4">
            <div className="mb-4 flex gap-4 items-center flex-wrap">
                <select
                    className="border p-2 rounded"
                    value={selectedTeam}
                    onChange={e => setSelectedTeam(e.target.value)}
                >
                    <option value="">Выберите команду</option>
                    {teams.map(t => (
                        <option key={t.team_id} value={t.team_id}>{t.team_name}</option>
                    ))}
                </select>
            </div>

            {loading && <div>Загрузка...</div>}

            {data && (
                <div className="overflow-x-auto">
                    <table className="min-w-full bg-white border">
                        <thead>
                            <tr className="bg-gray-100">
                                <th
                                    className="p-2 border cursor-pointer hover:bg-gray-200"
                                    onClick={() => handleSort('name')}
                                >
                                    Игрок <SortIcon column="name" />
                                </th>
                                <th
                                    className="p-2 border cursor-pointer hover:bg-gray-200"
                                    onClick={() => handleSort('total_z')}
                                >
                                    Total Z <SortIcon column="total_z" />
                                </th>
                                {CATEGORIES.map(cat => (
                                    <th
                                        key={cat}
                                        className={`p-2 border cursor-pointer hover:bg-gray-200 ${puntCategories.includes(cat) ? 'opacity-50' : ''}`}
                                        onClick={() => handleSort(cat)}
                                    >
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
                                        {player.name} <span className="text-xs text-gray-500">({player.position})</span>
                                    </td>
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
        </div>
    );
};

export default Analytics;
