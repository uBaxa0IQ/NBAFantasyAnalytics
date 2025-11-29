import React, { useState, useEffect } from 'react';
import api from '../api';

const CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'FG%', 'FT%', '3PT%', 'A/TO'];

import MultiTeamTradeAnalyzer from './MultiTeamTradeAnalyzer';

const TradeAnalyzer = ({ period, setPeriod, puntCategories, setPuntCategories }) => {
    const [tradeMode, setTradeMode] = useState('two-team'); // 'two-team' или 'multi-team'
    const [teams, setTeams] = useState([]);
    const [myTeam, setMyTeam] = useState('');
    const [theirTeam, setTheirTeam] = useState('');
    const [myPlayers, setMyPlayers] = useState([]);
    const [theirPlayers, setTheirPlayers] = useState([]);
    const [selectedGive, setSelectedGive] = useState([]);
    const [selectedReceive, setSelectedReceive] = useState([]);
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);
    const [viewMode, setViewMode] = useState('z-scores');
    const [scopeMode, setScopeMode] = useState('team'); // 'team' или 'trade'
    const [excludeIr, setExcludeIr] = useState(false);
    const [selectedTeamForTable, setSelectedTeamForTable] = useState('my_team'); // 'my_team' или 'their_team'

    useEffect(() => {
        api.get('/teams').then(res => setTeams(res.data));
    }, []);

    useEffect(() => {
        if (myTeam) {
            api.get(`/analytics/${myTeam}?period=${period}&exclude_ir=${excludeIr}`)
                .then(res => setMyPlayers(res.data.players))
                .catch(err => console.error(err));
        } else {
            setMyPlayers([]);
        }
        setSelectedGive([]);
    }, [myTeam, period, excludeIr]);

    useEffect(() => {
        if (theirTeam) {
            api.get(`/analytics/${theirTeam}?period=${period}&exclude_ir=${excludeIr}`)
                .then(res => setTheirPlayers(res.data.players))
                .catch(err => console.error(err));
        } else {
            setTheirPlayers([]);
        }
        setSelectedReceive([]);
    }, [theirTeam, period, excludeIr]);

    const handleToggleGive = (playerName) => {
        setSelectedGive(prev =>
            prev.includes(playerName) ? prev.filter(n => n !== playerName) : [...prev, playerName]
        );
    };

    const handleToggleReceive = (playerName) => {
        setSelectedReceive(prev =>
            prev.includes(playerName) ? prev.filter(n => n !== playerName) : [...prev, playerName]
        );
    };

    const handleAnalyze = () => {
        if (!myTeam || !theirTeam) {
            alert('Выберите обе команды');
            return;
        }
        if (selectedGive.length === 0 && selectedReceive.length === 0) {
            alert('Выберите хотя бы одного игрока');
            return;
        }

        setLoading(true);
        api.post('/trade-analysis', {
            my_team_id: parseInt(myTeam),
            their_team_id: parseInt(theirTeam),
            i_give: selectedGive,
            i_receive: selectedReceive,
            period,
            punt_categories: puntCategories,
            scope_mode: scopeMode,
            exclude_ir: excludeIr
        })
            .then(res => {
                setResult(res.data);
                setLoading(false);
            })
            .catch(err => {
                console.error(err);
                setLoading(false);
                alert('Ошибка анализа трейда');
            });
    };

    const handlePuntChange = (cat) => {
        setPuntCategories(prev =>
            prev.includes(cat) ? prev.filter(c => c !== cat) : [...prev, cat]
        );
    };

    // Если выбран мультикомандный режим, показываем соответствующий компонент
    if (tradeMode === 'multi-team') {
        return (
            <div>
                <div className="mb-4 flex justify-center gap-4">
                    <div className="inline-flex rounded-lg border border-gray-300 bg-white p-1">
                        <button
                            onClick={() => setTradeMode('two-team')}
                            className={`px-4 py-2 rounded-md font-medium transition-colors ${
                                tradeMode === 'two-team' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'
                            }`}
                        >
                            2 команды
                        </button>
                        <button
                            onClick={() => setTradeMode('multi-team')}
                            className={`px-4 py-2 rounded-md font-medium transition-colors ${
                                tradeMode === 'multi-team' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'
                            }`}
                        >
                            Мультикомандный
                        </button>
                    </div>
                </div>
                <MultiTeamTradeAnalyzer
                    period={period}
                    setPeriod={setPeriod}
                    puntCategories={puntCategories}
                    setPuntCategories={setPuntCategories}
                />
            </div>
        );
    }

    return (
        <div className="p-4">
            <div className="mb-4 flex justify-center gap-4">
                <div className="inline-flex rounded-lg border border-gray-300 bg-white p-1">
                    <button
                        onClick={() => setTradeMode('two-team')}
                        className={`px-4 py-2 rounded-md font-medium transition-colors ${
                            tradeMode === 'two-team' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'
                        }`}
                    >
                        2 команды
                    </button>
                    <button
                        onClick={() => setTradeMode('multi-team')}
                        className={`px-4 py-2 rounded-md font-medium transition-colors ${
                            tradeMode === 'multi-team' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'
                        }`}
                    >
                        Мультикомандный
                    </button>
                </div>
            </div>
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
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                <div className="border rounded p-4">
                    <div className="mb-3">
                        <label className="block font-bold mb-2">Моя команда:</label>
                        <select className="border p-2 rounded w-full" value={myTeam} onChange={e => setMyTeam(e.target.value)}>
                            <option value="">Выберите команду</option>
                            {teams.map(t => (<option key={t.team_id} value={t.team_id}>{t.team_name}</option>))}
                        </select>
                    </div>
                    {myTeam && (<>
                        <h3 className="font-bold mb-2">Я отдаю:</h3>
                        <div className="space-y-1 max-h-64 overflow-y-auto">
                            {myPlayers.map(player => (
                                <label key={player.name} className={`flex items-center gap-2 p-2 rounded cursor-pointer ${selectedGive.includes(player.name) ? 'bg-blue-100' : 'hover:bg-gray-100'}`}>
                                    <input type="checkbox" checked={selectedGive.includes(player.name)} onChange={() => handleToggleGive(player.name)} />
                                    <span className="flex-1">{player.name}</span>
                                </label>
                            ))}
                        </div>
                    </>)}
                </div>
                <div className="border rounded p-4">
                    <div className="mb-3">
                        <label className="block font-bold mb-2">Их команда:</label>
                        <select className="border p-2 rounded w-full" value={theirTeam} onChange={e => setTheirTeam(e.target.value)}>
                            <option value="">Выберите команду</option>
                            {teams.map(t => (<option key={t.team_id} value={t.team_id}>{t.team_name}</option>))}
                        </select>
                    </div>
                    {theirTeam && (<>
                        <h3 className="font-bold mb-2">Я получаю:</h3>
                        <div className="space-y-1 max-h-64 overflow-y-auto">
                            {theirPlayers.map(player => (
                                <label key={player.name} className={`flex items-center gap-2 p-2 rounded cursor-pointer ${selectedReceive.includes(player.name) ? 'bg-green-100' : 'hover:bg-gray-100'}`}>
                                    <input type="checkbox" checked={selectedReceive.includes(player.name)} onChange={() => handleToggleReceive(player.name)} />
                                    <span className="flex-1">{player.name}</span>
                                </label>
                            ))}
                        </div>
                    </>)}
                </div>
            </div>
            <div className="mb-6 text-center">
                <button onClick={handleAnalyze} disabled={loading} className="bg-blue-600 text-white px-8 py-3 rounded-lg hover:bg-blue-700 disabled:bg-gray-400 font-bold text-lg">
                    {loading ? 'Анализ...' : 'Анализировать трейд'}
                </button>
            </div>
            {result && (
                <div className="border-t pt-6">
                    <h2 className="text-2xl font-bold mb-4 text-center">Результат анализа</h2>
                    <div className="flex justify-center gap-4 mb-6 flex-wrap">
                        <div className="inline-flex rounded-lg border border-gray-300 bg-white p-1">
                            <button onClick={() => setScopeMode('team')} className={`px-4 py-2 rounded-md font-medium transition-colors ${scopeMode === 'team' ? 'bg-green-600 text-white' : 'text-gray-700 hover:bg-gray-100'}`}>
                                Вся команда
                            </button>
                            <button onClick={() => setScopeMode('trade')} className={`px-4 py-2 rounded-md font-medium transition-colors ${scopeMode === 'trade' ? 'bg-green-600 text-white' : 'text-gray-700 hover:bg-gray-100'}`}>
                                Только трейд
                            </button>
                        </div>
                        <div className="inline-flex rounded-lg border border-gray-300 bg-white p-1">
                            <button onClick={() => setViewMode('z-scores')} className={`px-4 py-2 rounded-md font-medium transition-colors ${viewMode === 'z-scores' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'}`}>
                                Z-Scores
                            </button>
                            <button onClick={() => setViewMode('raw-stats')} className={`px-4 py-2 rounded-md font-medium transition-colors ${viewMode === 'raw-stats' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'}`}>
                                Реальные значения
                            </button>
                        </div>
                    </div>
                    {result.simulation_ranks && (
                        <div className="mb-6 border rounded-lg p-4 bg-gray-50">
                            <h3 className="text-lg font-bold mb-3 text-center">Места в симуляции</h3>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div className="border rounded p-3 bg-white">
                                    <h4 className="font-bold mb-2 text-center">По Z-score</h4>
                                    <div className="space-y-2">
                                        <div className="flex justify-between items-center">
                                            <span className="text-gray-600">{result.my_team.name}:</span>
                                            <span className="font-medium">
                                                {result.simulation_ranks.z_scores.my_team.before !== null ? (
                                                    <>
                                                        {result.simulation_ranks.z_scores.my_team.before} → {result.simulation_ranks.z_scores.my_team.after}
                                                        {result.simulation_ranks.z_scores.my_team.delta !== null && (
                                                            <span className={`ml-2 ${result.simulation_ranks.z_scores.my_team.delta < 0 ? 'text-green-600' : result.simulation_ranks.z_scores.my_team.delta > 0 ? 'text-red-600' : 'text-gray-600'}`}>
                                                                ({result.simulation_ranks.z_scores.my_team.delta < 0 ? '' : '+'}{result.simulation_ranks.z_scores.my_team.delta})
                                                            </span>
                                                        )}
                                                    </>
                                                ) : 'N/A'}
                                            </span>
                                        </div>
                                        <div className="flex justify-between items-center">
                                            <span className="text-gray-600">{result.their_team.name}:</span>
                                            <span className="font-medium">
                                                {result.simulation_ranks.z_scores.their_team.before !== null ? (
                                                    <>
                                                        {result.simulation_ranks.z_scores.their_team.before} → {result.simulation_ranks.z_scores.their_team.after}
                                                        {result.simulation_ranks.z_scores.their_team.delta !== null && (
                                                            <span className={`ml-2 ${result.simulation_ranks.z_scores.their_team.delta < 0 ? 'text-green-600' : result.simulation_ranks.z_scores.their_team.delta > 0 ? 'text-red-600' : 'text-gray-600'}`}>
                                                                ({result.simulation_ranks.z_scores.their_team.delta < 0 ? '' : '+'}{result.simulation_ranks.z_scores.their_team.delta})
                                                            </span>
                                                        )}
                                                    </>
                                                ) : 'N/A'}
                                            </span>
                                        </div>
                                    </div>
                                </div>
                                <div className="border rounded p-3 bg-white">
                                    <h4 className="font-bold mb-2 text-center">По статистике (avg)</h4>
                                    <div className="space-y-2">
                                        <div className="flex justify-between items-center">
                                            <span className="text-gray-600">{result.my_team.name}:</span>
                                            <span className="font-medium">
                                                {result.simulation_ranks.team_stats_avg.my_team.before !== null ? (
                                                    <>
                                                        {result.simulation_ranks.team_stats_avg.my_team.before} → {result.simulation_ranks.team_stats_avg.my_team.after}
                                                        {result.simulation_ranks.team_stats_avg.my_team.delta !== null && (
                                                            <span className={`ml-2 ${result.simulation_ranks.team_stats_avg.my_team.delta < 0 ? 'text-green-600' : result.simulation_ranks.team_stats_avg.my_team.delta > 0 ? 'text-red-600' : 'text-gray-600'}`}>
                                                                ({result.simulation_ranks.team_stats_avg.my_team.delta < 0 ? '' : '+'}{result.simulation_ranks.team_stats_avg.my_team.delta})
                                                            </span>
                                                        )}
                                                    </>
                                                ) : 'N/A'}
                                            </span>
                                        </div>
                                        <div className="flex justify-between items-center">
                                            <span className="text-gray-600">{result.their_team.name}:</span>
                                            <span className="font-medium">
                                                {result.simulation_ranks.team_stats_avg.their_team.before !== null ? (
                                                    <>
                                                        {result.simulation_ranks.team_stats_avg.their_team.before} → {result.simulation_ranks.team_stats_avg.their_team.after}
                                                        {result.simulation_ranks.team_stats_avg.their_team.delta !== null && (
                                                            <span className={`ml-2 ${result.simulation_ranks.team_stats_avg.their_team.delta < 0 ? 'text-green-600' : result.simulation_ranks.team_stats_avg.their_team.delta > 0 ? 'text-red-600' : 'text-gray-600'}`}>
                                                                ({result.simulation_ranks.team_stats_avg.their_team.delta < 0 ? '' : '+'}{result.simulation_ranks.team_stats_avg.their_team.delta})
                                                            </span>
                                                        )}
                                                    </>
                                                ) : 'N/A'}
                                            </span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}
                    {(() => {
                        const myData = scopeMode === 'team' ? result.my_team : result.my_trade;
                        const theirData = scopeMode === 'team' ? result.their_team : result.their_trade;
                        
                        return (
                            <>
                                {viewMode === 'z-scores' && (
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                                        <div className="border rounded-lg p-6 bg-white">
                                            <h3 className="text-xl font-bold mb-4">{myData.name}</h3>
                                            <div className="space-y-2">
                                                <div className="flex justify-between items-center">
                                                    <span className="text-gray-600">Total Z до:</span>
                                                    <span className="font-bold text-lg">{myData.before_z}</span>
                                                </div>
                                                <div className="flex justify-between items-center">
                                                    <span className="text-gray-600">Total Z после:</span>
                                                    <span className="font-bold text-lg">{myData.after_z}</span>
                                                </div>
                                                <div className="flex justify-between items-center border-t pt-2">
                                                    <span className="font-bold">Изменение (Δ):</span>
                                                    <span className={`font-bold text-xl ${myData.delta > 0 ? 'text-green-600' : myData.delta < 0 ? 'text-red-600' : 'text-gray-600'}`}>
                                                        {myData.delta > 0 ? '+' : ''}{myData.delta}
                                                    </span>
                                                </div>
                                            </div>
                                        </div>
                                        <div className="border rounded-lg p-6 bg-white">
                                            <h3 className="text-xl font-bold mb-4">{theirData.name}</h3>
                                            <div className="space-y-2">
                                                <div className="flex justify-between items-center">
                                                    <span className="text-gray-600">Total Z до:</span>
                                                    <span className="font-bold text-lg">{theirData.before_z}</span>
                                                </div>
                                                <div className="flex justify-between items-center">
                                                    <span className="text-gray-600">Total Z после:</span>
                                                    <span className="font-bold text-lg">{theirData.after_z}</span>
                                                </div>
                                                <div className="flex justify-between items-center border-t pt-2">
                                                    <span className="font-bold">Изменение (Δ):</span>
                                                    <span className={`font-bold text-xl ${theirData.delta > 0 ? 'text-green-600' : theirData.delta < 0 ? 'text-red-600' : 'text-gray-600'}`}>
                                                        {theirData.delta > 0 ? '+' : ''}{theirData.delta}
                                                    </span>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                )}
                                <div className="mb-4 flex items-center justify-center gap-4 flex-wrap">
                                    <h3 className="text-xl font-bold">
                                        {viewMode === 'z-scores' ? 'Детализация по категориям (Z-scores)' : 'Детализация по категориям (реальные значения)'}
                                    </h3>
                                    <select
                                        value={selectedTeamForTable}
                                        onChange={(e) => setSelectedTeamForTable(e.target.value)}
                                        className="border p-2 rounded text-sm font-medium min-w-[200px]"
                                    >
                                        <option value="my_team">
                                            {scopeMode === 'team' ? result.my_team.name : 'Игроки трейда (я отдаю)'}
                                        </option>
                                        <option value="their_team">
                                            {scopeMode === 'team' ? result.their_team.name : 'Игроки трейда (я получаю)'}
                                        </option>
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
                                            {Object.entries(viewMode === 'z-scores' 
                                                ? (selectedTeamForTable === 'my_team' ? myData.categories : theirData.categories)
                                                : (selectedTeamForTable === 'my_team' ? myData.raw_categories : theirData.raw_categories)
                                            ).map(([cat, data]) => (
                                                <tr key={cat} className="hover:bg-gray-50">
                                                    <td className="p-2 border font-medium">{cat}</td>
                                                    <td className="p-2 border text-center">{data.before}</td>
                                                    <td className="p-2 border text-center">{data.after}</td>
                                                    <td className={`p-2 border text-center font-bold ${data.delta > 0 ? 'text-green-600' : data.delta < 0 ? 'text-red-600' : 'text-gray-600'}`}>
                                                        {data.delta > 0 ? '+' : ''}{data.delta}
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </>
                        );
                    })()}
                </div>
            )}
        </div>
    );
};

export default TradeAnalyzer;
