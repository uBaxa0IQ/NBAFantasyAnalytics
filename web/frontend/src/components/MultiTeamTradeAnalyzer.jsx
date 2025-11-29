import React, { useState, useEffect } from 'react';
import api from '../api';

const CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'FG%', 'FT%', '3PT%', 'A/TO'];

const MultiTeamTradeAnalyzer = ({ period, setPeriod, puntCategories, setPuntCategories }) => {
    const [teams, setTeams] = useState([]);
    const [teamTrades, setTeamTrades] = useState([{ teamId: '', give: [], receive: [] }]);
    const [teamPlayers, setTeamPlayers] = useState({}); // teamId -> players[]
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);
    const [viewMode, setViewMode] = useState('z-scores');
    const [excludeIr, setExcludeIr] = useState(false);
    const [validationErrors, setValidationErrors] = useState([]);
    const [selectedTeamForTable, setSelectedTeamForTable] = useState(null);

    useEffect(() => {
        api.get('/teams').then(res => setTeams(res.data));
    }, []);

    // Загружаем игроков для выбранных команд
    useEffect(() => {
        const loadPlayers = async () => {
            const newTeamPlayers = {};
            for (const trade of teamTrades) {
                if (trade.teamId) {
                    try {
                        const res = await api.get(`/analytics/${trade.teamId}?period=${period}&exclude_ir=${excludeIr}`);
                        newTeamPlayers[trade.teamId] = res.data.players;
                    } catch (err) {
                        console.error(`Error loading players for team ${trade.teamId}:`, err);
                        newTeamPlayers[trade.teamId] = [];
                    }
                }
            }
            setTeamPlayers(newTeamPlayers);
        };
        loadPlayers();
    }, [teamTrades.map(t => t.teamId).join(','), period, excludeIr]);

    // Инициализация выбранной команды для таблицы при получении результата
    useEffect(() => {
        if (result && result.teams && result.teams.length > 0 && !selectedTeamForTable) {
            setSelectedTeamForTable(result.teams[0].team_id);
        }
    }, [result]);

    const addTeam = () => {
        setTeamTrades([...teamTrades, { teamId: '', give: [], receive: [] }]);
    };

    const removeTeam = (index) => {
        if (teamTrades.length > 1) {
            const newTrades = teamTrades.filter((_, i) => i !== index);
            setTeamTrades(newTrades);
            setResult(null);
        }
    };

    const updateTeamId = (index, teamId) => {
        const newTrades = [...teamTrades];
        newTrades[index] = { ...newTrades[index], teamId, give: [], receive: [] };
        setTeamTrades(newTrades);
        setResult(null);
    };

    const togglePlayerGive = (teamIndex, playerName) => {
        const newTrades = [...teamTrades];
        const trade = newTrades[teamIndex];
        if (trade.give.includes(playerName)) {
            trade.give = trade.give.filter(n => n !== playerName);
        } else {
            trade.give = [...trade.give, playerName];
        }
        setTeamTrades(newTrades);
        setResult(null);
    };

    const togglePlayerReceive = (teamIndex, playerName) => {
        const newTrades = [...teamTrades];
        const trade = newTrades[teamIndex];
        if (trade.receive.includes(playerName)) {
            trade.receive = trade.receive.filter(n => n !== playerName);
        } else {
            trade.receive = [...trade.receive, playerName];
        }
        setTeamTrades(newTrades);
        setResult(null);
    };

    const handleAnalyze = () => {
        // Валидация
        const errors = [];
        
        // Проверка, что все команды выбраны
        const emptyTeams = teamTrades.filter(t => !t.teamId);
        if (emptyTeams.length > 0) {
            errors.push('Выберите все команды');
        }

        // Проверка уникальности команд
        const teamIds = teamTrades.map(t => t.teamId).filter(id => id);
        if (teamIds.length !== new Set(teamIds).size) {
            errors.push('Команды не должны повторяться');
        }

        // Проверка, что есть хотя бы один трейд
        const hasTrades = teamTrades.some(t => t.give.length > 0 || t.receive.length > 0);
        if (!hasTrades) {
            errors.push('Выберите хотя бы одного игрока для трейда');
        }

        if (errors.length > 0) {
            setValidationErrors(errors);
            return;
        }

        setValidationErrors([]);
        setLoading(true);

        // Формируем запрос
        const trades = teamTrades
            .filter(t => t.teamId)
            .map(t => ({
                team_id: parseInt(t.teamId),
                give: t.give,
                receive: t.receive
            }));

        api.post('/multi-team-trade-analysis', {
            trades,
            period,
            punt_categories: puntCategories,
            exclude_ir: excludeIr
        })
            .then(res => {
                if (res.data.error) {
                    setValidationErrors(res.data.validation_errors || [res.data.error]);
                    setResult(null);
                } else {
                    setResult(res.data);
                }
                setLoading(false);
            })
            .catch(err => {
                console.error(err);
                setLoading(false);
                if (err.response?.data?.validation_errors) {
                    setValidationErrors(err.response.data.validation_errors);
                } else {
                    setValidationErrors(['Ошибка анализа трейда']);
                }
                setResult(null);
            });
    };

    const handlePuntChange = (cat) => {
        setPuntCategories(prev =>
            prev.includes(cat) ? prev.filter(c => c !== cat) : [...prev, cat]
        );
    };

    // Получаем всех игроков, участвующих в трейде (для отображения в других командах)
    const getAllTradedPlayers = () => {
        const allGiven = teamTrades.flatMap(t => t.give);
        const allReceived = teamTrades.flatMap(t => t.receive);
        return [...new Set([...allGiven, ...allReceived])];
    };

    const tradedPlayers = getAllTradedPlayers();

    return (
        <div className="p-4">
            <div className="mb-4 flex gap-4 items-center flex-wrap">
                <div>
                    <label className="mr-2 font-bold">Период:</label>
                    <select className="border p-2 rounded" value={period} onChange={e => setPeriod(e.target.value)}>
                        <option value="2026_total">Весь сезон</option>
                        <option value="2026_last_30">Последние 30 дней</option>
                        <option value="2026_last_15">Последние 15 дней</option>
                        <option value="2026_last_7">Последние 7 дней</option>
                        <option value="2026_projected">Прогноз</option>
                    </select>
                </div>
            </div>
            <div className="mb-4">
                <span className="font-bold mr-2">Punt Categories:</span>
                <div className="flex gap-2 flex-wrap">
                    {CATEGORIES.map(cat => (
                        <label key={cat} className="flex items-center gap-1 cursor-pointer bg-gray-100 px-2 py-1 rounded hover:bg-gray-200">
                            <input type="checkbox" checked={puntCategories.includes(cat)} onChange={() => handlePuntChange(cat)} />
                            {cat}
                        </label>
                    ))}
                </div>
            </div>
            <div className="mb-4">
                <label className="flex items-center gap-2 cursor-pointer bg-gray-100 px-3 py-2 rounded hover:bg-gray-200 inline-block">
                    <input
                        type="checkbox"
                        checked={excludeIr}
                        onChange={e => setExcludeIr(e.target.checked)}
                    />
                    <span className="font-medium">Исключить IR игроков</span>
                </label>
            </div>

            {/* Ошибки валидации */}
            {validationErrors.length > 0 && (
                <div className="mb-4 p-3 bg-red-100 border border-red-400 text-red-700 rounded">
                    <div className="font-bold mb-1">Ошибки валидации:</div>
                    <ul className="list-disc list-inside">
                        {validationErrors.map((error, idx) => (
                            <li key={idx}>{error}</li>
                        ))}
                    </ul>
                </div>
            )}

            {/* Команды */}
            <div className="mb-6">
                <div className="flex justify-between items-center mb-4">
                    <h2 className="text-xl font-bold">Команды в трейде</h2>
                    <button
                        onClick={addTeam}
                        className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700"
                    >
                        + Добавить команду
                    </button>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {teamTrades.map((trade, index) => (
                        <div key={index} className="border rounded p-4 bg-white">
                            <div className="flex justify-between items-center mb-3">
                                <h3 className="font-bold">Команда {index + 1}</h3>
                                {teamTrades.length > 1 && (
                                    <button
                                        onClick={() => removeTeam(index)}
                                        className="text-red-600 hover:text-red-800 font-bold"
                                    >
                                        ×
                                    </button>
                                )}
                            </div>
                            <div className="mb-3">
                                <select
                                    className="border p-2 rounded w-full"
                                    value={trade.teamId}
                                    onChange={e => updateTeamId(index, e.target.value)}
                                >
                                    <option value="">Выберите команду</option>
                                    {teams.map(t => (
                                        <option key={t.team_id} value={t.team_id}>
                                            {t.team_name}
                                        </option>
                                    ))}
                                </select>
                            </div>
                            {trade.teamId && teamPlayers[trade.teamId] && (
                                <>
                                    <div className="mb-3">
                                        <h4 className="font-semibold mb-2 text-sm text-red-600">Отдает:</h4>
                                        <div className="space-y-1 max-h-64 overflow-y-auto border rounded p-2">
                                            {teamPlayers[trade.teamId].map(player => (
                                                <label
                                                    key={player.name}
                                                    className={`flex items-center gap-2 p-1 rounded cursor-pointer text-sm ${
                                                        trade.give.includes(player.name) ? 'bg-red-100' : 'hover:bg-gray-50'
                                                    }`}
                                                >
                                                    <input
                                                        type="checkbox"
                                                        checked={trade.give.includes(player.name)}
                                                        onChange={() => togglePlayerGive(index, player.name)}
                                                    />
                                                    <span>{player.name}</span>
                                                </label>
                                            ))}
                                        </div>
                                    </div>
                                    <div>
                                        <h4 className="font-semibold mb-2 text-sm text-green-600">Получает:</h4>
                                        <div className="space-y-1 max-h-64 overflow-y-auto border rounded p-2">
                                            {tradedPlayers.map(playerName => (
                                                <label
                                                    key={playerName}
                                                    className={`flex items-center gap-2 p-1 rounded cursor-pointer text-sm ${
                                                        trade.receive.includes(playerName) ? 'bg-green-100' : 'hover:bg-gray-50'
                                                    }`}
                                                >
                                                    <input
                                                        type="checkbox"
                                                        checked={trade.receive.includes(playerName)}
                                                        onChange={() => togglePlayerReceive(index, playerName)}
                                                    />
                                                    <span>{playerName}</span>
                                                </label>
                                            ))}
                                        </div>
                                    </div>
                                </>
                            )}
                        </div>
                    ))}
                </div>
            </div>

            <div className="mb-6 text-center">
                <button
                    onClick={handleAnalyze}
                    disabled={loading}
                    className="bg-blue-600 text-white px-8 py-3 rounded-lg hover:bg-blue-700 disabled:bg-gray-400 font-bold text-lg"
                >
                    {loading ? 'Анализ...' : 'Анализировать трейд'}
                </button>
            </div>

            {/* Результаты */}
            {result && result.teams && (
                <div className="border-t pt-6">
                    <h2 className="text-2xl font-bold mb-4 text-center">Результат анализа</h2>
                    <div className="flex justify-center gap-4 mb-6 flex-wrap">
                        <div className="inline-flex rounded-lg border border-gray-300 bg-white p-1">
                            <button
                                onClick={() => setViewMode('z-scores')}
                                className={`px-4 py-2 rounded-md font-medium transition-colors ${
                                    viewMode === 'z-scores' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'
                                }`}
                            >
                                Z-Scores
                            </button>
                            <button
                                onClick={() => setViewMode('raw-stats')}
                                className={`px-4 py-2 rounded-md font-medium transition-colors ${
                                    viewMode === 'raw-stats' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'
                                }`}
                            >
                                Реальные значения
                            </button>
                        </div>
                    </div>

                    {/* Симуляция мест */}
                    {result.simulation_ranks && (
                        <div className="mb-6 border rounded-lg p-4 bg-gray-50">
                            <h3 className="text-lg font-bold mb-3 text-center">Места в симуляции</h3>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div className="border rounded p-3 bg-white">
                                    <h4 className="font-bold mb-2 text-center">По Z-score</h4>
                                    <div className="space-y-2">
                                        {result.teams.map(team => {
                                            const rank = result.simulation_ranks.z_scores[team.team_id];
                                            return (
                                                <div key={team.team_id} className="flex justify-between items-center">
                                                    <span className="text-gray-600">{team.team_name}:</span>
                                                    <span className="font-medium">
                                                        {rank?.before !== null ? (
                                                            <>
                                                                {rank.before} → {rank.after}
                                                                {rank.delta !== null && (
                                                                    <span className={`ml-2 ${
                                                                        rank.delta < 0 ? 'text-green-600' :
                                                                        rank.delta > 0 ? 'text-red-600' : 'text-gray-600'
                                                                    }`}>
                                                                        ({rank.delta < 0 ? '' : '+'}{rank.delta})
                                                                    </span>
                                                                )}
                                                            </>
                                                        ) : 'N/A'}
                                                    </span>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                                <div className="border rounded p-3 bg-white">
                                    <h4 className="font-bold mb-2 text-center">По статистике (avg)</h4>
                                    <div className="space-y-2">
                                        {result.teams.map(team => {
                                            const rank = result.simulation_ranks.team_stats_avg[team.team_id];
                                            return (
                                                <div key={team.team_id} className="flex justify-between items-center">
                                                    <span className="text-gray-600">{team.team_name}:</span>
                                                    <span className="font-medium">
                                                        {rank?.before !== null ? (
                                                            <>
                                                                {rank.before} → {rank.after}
                                                                {rank.delta !== null && (
                                                                    <span className={`ml-2 ${
                                                                        rank.delta < 0 ? 'text-green-600' :
                                                                        rank.delta > 0 ? 'text-red-600' : 'text-gray-600'
                                                                    }`}>
                                                                        ({rank.delta < 0 ? '' : '+'}{rank.delta})
                                                                    </span>
                                                                )}
                                                            </>
                                                        ) : 'N/A'}
                                                    </span>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Результаты по командам */}
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-6">
                        {result.teams.map(team => (
                            <div key={team.team_id} className="border rounded-lg p-6 bg-white">
                                <h3 className="text-xl font-bold mb-4">{team.team_name}</h3>
                                <div className="space-y-2 mb-4">
                                    <div className="flex justify-between items-center">
                                        <span className="text-gray-600">Total Z до:</span>
                                        <span className="font-bold text-lg">{team.before_z}</span>
                                    </div>
                                    <div className="flex justify-between items-center">
                                        <span className="text-gray-600">Total Z после:</span>
                                        <span className="font-bold text-lg">{team.after_z}</span>
                                    </div>
                                    <div className="flex justify-between items-center border-t pt-2">
                                        <span className="font-bold">Изменение (Δ):</span>
                                        <span className={`font-bold text-xl ${
                                            team.delta > 0 ? 'text-green-600' :
                                            team.delta < 0 ? 'text-red-600' : 'text-gray-600'
                                        }`}>
                                            {team.delta > 0 ? '+' : ''}{team.delta}
                                        </span>
                                    </div>
                                </div>
                                {team.players_given.length > 0 && (
                                    <div className="mb-2">
                                        <span className="text-sm text-gray-600">Отдает: </span>
                                        <span className="text-sm font-medium">{team.players_given.join(', ')}</span>
                                    </div>
                                )}
                                {team.players_received.length > 0 && (
                                    <div className="mb-2">
                                        <span className="text-sm text-gray-600">Получает: </span>
                                        <span className="text-sm font-medium">{team.players_received.join(', ')}</span>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>

                    {/* Детализация по категориям с переключателем команды */}
                    {result.teams.length > 0 && selectedTeamForTable && (() => {
                        const selectedTeam = result.teams.find(t => t.team_id === selectedTeamForTable) || result.teams[0];
                        if (!selectedTeam) return null;
                        return (
                            <div>
                                <div className="mb-4 flex items-center justify-center gap-4 flex-wrap">
                                    <h3 className="text-xl font-bold">
                                        Детализация по категориям ({viewMode === 'z-scores' ? 'Z-scores' : 'реальные значения'})
                                    </h3>
                                    <select
                                        value={selectedTeamForTable}
                                        onChange={(e) => setSelectedTeamForTable(parseInt(e.target.value))}
                                        className="border p-2 rounded text-sm font-medium min-w-[200px]"
                                    >
                                        {result.teams.map(team => (
                                            <option key={team.team_id} value={team.team_id}>
                                                {team.team_name}
                                            </option>
                                        ))}
                                    </select>
                                </div>
                                <div className="overflow-x-auto">
                                    <table className="min-w-full bg-white border">
                                        <thead>
                                            <tr className="bg-gray-100">
                                                <th className="p-2 border">Категория</th>
                                                <th className="p-2 border">До</th>
                                                <th className="p-2 border">После</th>
                                                <th className="p-2 border">Δ</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {Object.entries(viewMode === 'z-scores' ? selectedTeam.categories : selectedTeam.raw_categories).map(([cat, data]) => (
                                                <tr key={cat} className="hover:bg-gray-50">
                                                    <td className="p-2 border font-medium">{cat}</td>
                                                    <td className="p-2 border text-center">{data.before}</td>
                                                    <td className="p-2 border text-center">{data.after}</td>
                                                    <td className={`p-2 border text-center font-bold ${
                                                        data.delta > 0 ? 'text-green-600' :
                                                        data.delta < 0 ? 'text-red-600' : 'text-gray-600'
                                                    }`}>
                                                        {data.delta > 0 ? '+' : ''}{data.delta}
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        );
                    })()}
                </div>
            )}
        </div>
    );
};

export default MultiTeamTradeAnalyzer;

