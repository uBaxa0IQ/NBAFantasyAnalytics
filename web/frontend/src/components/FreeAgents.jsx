import React, { useState, useEffect } from 'react';
import api from '../api';

const CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'FG%', 'FT%', '3PT%', 'A/TO'];
const POSITIONS = ['PG', 'SG', 'SF', 'PF', 'C'];

const FreeAgents = ({ onPlayerClick, period, setPeriod, puntCategories, setPuntCategories }) => {
    const [teams, setTeams] = useState([]);
    const [myTeam, setMyTeam] = useState('');
    const [position, setPosition] = useState('');
    const [data, setData] = useState(null);
    const [myTeamData, setMyTeamData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [filterBetterThanMine, setFilterBetterThanMine] = useState(false);
    const [sortBy, setSortBy] = useState('total_z');
    const [sortDir, setSortDir] = useState('desc');

    useEffect(() => {
        api.get('/teams').then(res => setTeams(res.data));
    }, []);

    useEffect(() => {
        setLoading(true);
        const posParam = position ? `&position=${position}` : '';
        api.get(`/free-agents?period=${period}${posParam}`)
            .then(res => {
                setData(res.data);
                setLoading(false);
            })
            .catch(err => {
                console.error(err);
                setLoading(false);
            });
    }, [period, position]);

    useEffect(() => {
        if (myTeam && filterBetterThanMine) {
            api.get(`/analytics/${myTeam}?period=${period}`)
                .then(res => setMyTeamData(res.data))
                .catch(err => console.error(err));
        }
    }, [myTeam, period, filterBetterThanMine]);

    const handlePuntChange = (cat) => {
        setPuntCategories(prev =>
            prev.includes(cat) ? prev.filter(c => c !== cat) : [...prev, cat]
        );
    };

    const calculateTotalZ = (player) => {
        let total = 0;
        CATEGORIES.forEach(cat => {
            if (!puntCategories.includes(cat)) {
                total += player.z_scores[cat] || 0;
            }
        });
        return total;
    };

    const getMinZFromMyTeam = () => {
        if (!myTeamData || !myTeamData.players || myTeamData.players.length === 0) return -Infinity;
        const teamZScores = myTeamData.players.map(p => calculateTotalZ(p));
        return Math.min(...teamZScores);
    };

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
        } else if (sortBy === 'name') {
            return sortDir === 'asc' ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
        } else {
            valA = a.z_scores[sortBy] || 0;
            valB = b.z_scores[sortBy] || 0;
        }

        return sortDir === 'asc' ? valA - valB : valB - valA;
    }) : [];

    if (filterBetterThanMine && myTeam) {
        const minZ = getMinZFromMyTeam();
        sortedPlayers = sortedPlayers.filter(p => calculateTotalZ(p) > minZ);
    }

    const SortIcon = ({ column }) => {
        if (sortBy !== column) return <span className="text-gray-400 ml-1">⇅</span>;
        return sortDir === 'asc' ? <span className="ml-1">↑</span> : <span className="ml-1">↓</span>;
    };

    return (
        <div className="p-4">
            <div className="mb-4 flex gap-4 items-center flex-wrap">
                <select
                    className="border p-2 rounded"
                    value={period}
                    onChange={e => setPeriod(e.target.value)}
                >
                    <option value="2026_total">Весь сезон</option>
                    <option value="2026_last_30">Последние 30 дней</option>
                    <option value="2026_last_15">Последние 15 дней</option>
                    <option value="2026_last_7">Последние 7 дней</option>
                    <option value="2026_projected">Прогноз</option>
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

                <div className="flex items-center gap-2">
                    <label className="flex items-center gap-2 cursor-pointer">
                        <input
                            type="checkbox"
                            checked={filterBetterThanMine}
                            onChange={(e) => {
                                setFilterBetterThanMine(e.target.checked);
                                if (!e.target.checked) setMyTeam('');
                            }}
                        />
                        <span className="font-medium">Только лучше моих</span>
                    </label>
                    {filterBetterThanMine && (
                        <select
                            className="border p-2 rounded"
                            value={myTeam}
                            onChange={e => setMyTeam(e.target.value)}
                        >
                            <option value="">Выберите свою команду</option>
                            {teams.map(t => (
                                <option key={t.team_id} value={t.team_id}>{t.team_name}</option>
                            ))}
                        </select>
                    )}
                </div>
            </div>

            <div className="mb-4">
                <span className="font-bold mr-2">Punt Categories:</span>
                <div className="flex gap-2 flex-wrap">
                    {CATEGORIES.map(cat => (
                        <label key={cat} className="flex items-center gap-1 cursor-pointer bg-gray-100 px-2 py-1 rounded hover:bg-gray-200">
                            <input
                                type="checkbox"
                                checked={puntCategories.includes(cat)}
                                onChange={() => handlePuntChange(cat)}
                            />
                            {cat}
                        </label>
                    ))}
                </div>
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
                                <th className="p-2 border">Позиция</th>
                                <th className="p-2 border">NBA Team</th>
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

export default FreeAgents;
