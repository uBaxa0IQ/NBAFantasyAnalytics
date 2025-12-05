import React, { useState, useEffect } from 'react';
import api from '../api';
import { saveState, loadState, StorageKeys } from '../utils/statePersistence';

const CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'FG%', 'FT%', '3PT%', 'A/TO'];

const MultiTeamTradeAnalyzer = ({ period, puntCategories, simulationMode, mainTeam }) => {
    const savedState = loadState(StorageKeys.MULTITEAM_TRADE, {});
    const [teams, setTeams] = useState([]);
    const [teamTrades, setTeamTrades] = useState(savedState.teamTrades || [{ teamId: '', give: [], receive: [] }]);
    const [teamPlayers, setTeamPlayers] = useState({}); // teamId -> players[]
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);
    const [viewMode, setViewMode] = useState(savedState.viewMode || 'z-scores');
    const [validationErrors, setValidationErrors] = useState([]);
    const [selectedTeamForTable, setSelectedTeamForTable] = useState(savedState.selectedTeamForTable || null);

    useEffect(() => {
        api.get('/teams').then(res => setTeams(res.data));
    }, []);

    // Сохранение состояния при изменении
    useEffect(() => {
        saveState(StorageKeys.MULTITEAM_TRADE, {
            teamTrades,
            selectedTeamForTable,
            viewMode
        });
    }, [teamTrades, selectedTeamForTable, viewMode]);

    // Загружаем игроков для выбранных команд
    useEffect(() => {
        const loadPlayers = async () => {
            const newTeamPlayers = {};
            for (const trade of teamTrades) {
                if (trade.teamId) {
                    try {
                        // В аналитике команды IR игроки всегда включены
                        const res = await api.get(`/analytics/${trade.teamId}?period=${period}&exclude_ir=false`);
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
    }, [teamTrades.map(t => t.teamId).join(','), period]);

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

        // Формируем тело запроса
        const requestBody = {
            trades,
            period,
            punt_categories: puntCategories,
            simulation_mode: simulationMode
        };
        
        // Если режим top_n, добавляем дополнительные параметры
        if (simulationMode === 'top_n') {
            requestBody.top_n_players = 13;
            // Загружаем выбранных игроков из localStorage для всех команд
            const customTeamPlayers = {};
            
            for (const trade of teamTrades) {
                if (trade.teamId && mainTeam && trade.teamId === mainTeam) {
                    const saved = localStorage.getItem(`customTeamPlayers_${trade.teamId}`);
                    if (saved) {
                        try {
                            const customPlayers = JSON.parse(saved);
                            if (customPlayers.length > 0) {
                                customTeamPlayers[parseInt(trade.teamId)] = customPlayers;
                            }
                        } catch (e) {
                            console.error(`Error parsing custom players for team ${trade.teamId}:`, e);
                        }
                    }
                }
            }
            
            if (Object.keys(customTeamPlayers).length > 0) {
                requestBody.custom_team_players = customTeamPlayers;
            }
        }
        
        api.post('/multi-team-trade-analysis', requestBody)
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


    // Получаем всех игроков, участвующих в трейде (для отображения в других командах)
    const getAllTradedPlayers = () => {
        const allGiven = teamTrades.flatMap(t => t.give);
        const allReceived = teamTrades.flatMap(t => t.receive);
        return [...new Set([...allGiven, ...allReceived])];
    };

    const tradedPlayers = getAllTradedPlayers();

    return (
        <div className="p-4">

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
                    
                    {/* Category Rankings Changes */}
                    {result.category_rankings && (
                        <MultiTeamCategoryRankingsChanges 
                            categoryRankings={result.category_rankings}
                            teams={result.teams}
                        />
                    )}
                </div>
            )}
        </div>
    );
};

// Компонент для отображения изменений позиций по категориям в мультитрейде
const MultiTeamCategoryRankingsChanges = ({ categoryRankings, teams }) => {
    const [isExpanded, setIsExpanded] = useState(false);
    const [selectedTeamId, setSelectedTeamId] = useState(teams && teams.length > 0 ? teams[0].team_id : null);
    
    if (!teams || teams.length === 0 || !selectedTeamId) return null;
    
    const selectedTeamRankings = categoryRankings[selectedTeamId] || {};
    const allCategories = Object.keys(selectedTeamRankings);
    const selectedTeamName = teams.find(t => t.team_id === selectedTeamId)?.team_name || '';
    
    // Функция для получения цвета бейджа позиции
    const getRankBadgeColor = (rank) => {
        if (rank === 1) return 'bg-yellow-500 text-white';
        if (rank === 2) return 'bg-gray-400 text-white';
        if (rank === 3) return 'bg-orange-500 text-white';
        return 'bg-gray-300 text-gray-700';
    };
    
    // Функция для получения цвета изменения
    const getRankChangeColor = (delta) => {
        if (delta < 0) return 'text-green-600 font-semibold'; // Улучшение (меньше = лучше)
        if (delta > 0) return 'text-red-600 font-semibold'; // Ухудшение
        return 'text-gray-500'; // Без изменений
    };
    
    // Функция для форматирования изменения
    const formatDelta = (delta) => {
        if (delta === 0) return '—';
        const sign = delta < 0 ? '-' : '+';
        return `${sign}${Math.abs(delta)}`;
    };
    
    return (
        <div className="bg-white border rounded-lg p-6 shadow-sm mt-6">
            <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-semibold text-gray-700">Изменения позиций по категориям</h3>
                <button
                    onClick={() => setIsExpanded(!isExpanded)}
                    className="text-gray-500 hover:text-gray-700 text-sm font-medium"
                >
                    {isExpanded ? 'Скрыть' : 'Показать'} таблицу
                </button>
            </div>
            
            {isExpanded && (
                <div>
                    {/* Переключатель команд */}
                    <div className="mb-4 flex items-center justify-center gap-4">
                        <select
                            value={selectedTeamId}
                            onChange={(e) => setSelectedTeamId(parseInt(e.target.value))}
                            className="border p-2 rounded text-sm font-medium min-w-[200px]"
                        >
                            {teams.map(team => (
                                <option key={team.team_id} value={team.team_id}>
                                    {team.team_name}
                                </option>
                            ))}
                        </select>
                    </div>
                    
                    {/* Таблица для выбранной команды */}
                    <div className="overflow-x-auto">
                        <table className="min-w-full bg-white border">
                            <thead>
                                <tr className="bg-gray-100">
                                    <th className="p-3 border text-left font-semibold">Категория</th>
                                    <th className="p-3 border text-center font-semibold">До</th>
                                    <th className="p-3 border text-center font-semibold">После</th>
                                    <th className="p-3 border text-center font-semibold">Изменение</th>
                                </tr>
                            </thead>
                            <tbody>
                                {allCategories.map((cat) => {
                                    const data = selectedTeamRankings[cat];
                                    if (!data) return null;
                                    return (
                                        <tr 
                                            key={cat} 
                                            className={`hover:bg-gray-50 ${
                                                data.delta !== 0 ? 'bg-yellow-50' : ''
                                            }`}
                                        >
                                            <td className="p-3 border font-medium">{cat}</td>
                                            <td className="p-3 border text-center">
                                                <span className={`inline-block px-3 py-1 rounded-full text-sm font-bold ${getRankBadgeColor(data.before)}`}>
                                                    {data.before}
                                                </span>
                                            </td>
                                            <td className="p-3 border text-center">
                                                <span className={`inline-block px-3 py-1 rounded-full text-sm font-bold ${getRankBadgeColor(data.after)}`}>
                                                    {data.after}
                                                </span>
                                            </td>
                                            <td className={`p-3 border text-center ${getRankChangeColor(data.delta)}`}>
                                                {formatDelta(data.delta)}
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
};

export default MultiTeamTradeAnalyzer;

