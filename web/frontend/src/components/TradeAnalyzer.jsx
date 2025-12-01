import React, { useState, useEffect } from 'react';
import api from '../api';
import { saveState, loadState, StorageKeys } from '../utils/statePersistence';

const CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'FG%', 'FT%', '3PT%', 'A/TO'];

import MultiTeamTradeAnalyzer from './MultiTeamTradeAnalyzer';

const TradeAnalyzer = ({ period, puntCategories, excludeIrForSimulations }) => {
    const savedState = loadState(StorageKeys.TRADE, {});
    const [tradeMode, setTradeMode] = useState(savedState.tradeMode || 'two-team'); // 'two-team' или 'multi-team'
    const [teams, setTeams] = useState([]);
    const [myTeam, setMyTeam] = useState(savedState.myTeam || '');
    const [theirTeam, setTheirTeam] = useState(savedState.theirTeam || '');
    const [myPlayers, setMyPlayers] = useState([]);
    const [theirPlayers, setTheirPlayers] = useState([]);
    const [selectedGive, setSelectedGive] = useState(savedState.selectedGive || []);
    const [selectedReceive, setSelectedReceive] = useState(savedState.selectedReceive || []);
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);
    const [viewMode, setViewMode] = useState(savedState.viewMode || 'z-scores');
    const [scopeMode, setScopeMode] = useState(savedState.scopeMode || 'team'); // 'team' или 'trade'
    const [selectedTeamForTable, setSelectedTeamForTable] = useState('my_team'); // 'my_team' или 'their_team'
    const [isCategoryDetailsExpanded, setIsCategoryDetailsExpanded] = useState(false);

    useEffect(() => {
        api.get('/teams').then(res => setTeams(res.data));
    }, []);

    // Сохранение состояния при изменении
    useEffect(() => {
        saveState(StorageKeys.TRADE, {
            tradeMode,
            myTeam,
            theirTeam,
            selectedGive,
            selectedReceive,
            viewMode,
            scopeMode
        });
    }, [tradeMode, myTeam, theirTeam, selectedGive, selectedReceive, viewMode, scopeMode]);

    useEffect(() => {
        if (myTeam) {
            // В аналитике команды IR игроки всегда включены
            api.get(`/analytics/${myTeam}?period=${period}&exclude_ir=false`)
                .then(res => setMyPlayers(res.data.players))
                .catch(err => console.error(err));
        } else {
            setMyPlayers([]);
        }
        // Не сбрасываем selectedGive, так как состояние сохраняется
    }, [myTeam, period]);

    useEffect(() => {
        if (theirTeam) {
            // В аналитике команды IR игроки всегда включены
            api.get(`/analytics/${theirTeam}?period=${period}&exclude_ir=false`)
                .then(res => setTheirPlayers(res.data.players))
                .catch(err => console.error(err));
        } else {
            setTheirPlayers([]);
        }
        // Не сбрасываем selectedReceive, так как состояние сохраняется
    }, [theirTeam, period]);

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
            exclude_ir: excludeIrForSimulations
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
                    puntCategories={puntCategories}
                    excludeIrForSimulations={excludeIrForSimulations}
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
                                
                                {/* Детализация по категориям - Коллапсируемый блок */}
                                <div className="bg-white border rounded-lg p-6 shadow-sm mb-6">
                                    <div className="flex justify-between items-center mb-4">
                                        <h3 className="text-lg font-semibold text-gray-700">
                                            {viewMode === 'z-scores' ? 'Детализация по категориям (Z-scores)' : 'Детализация по категориям (реальные значения)'}
                                        </h3>
                                        <button
                                            onClick={() => setIsCategoryDetailsExpanded(!isCategoryDetailsExpanded)}
                                            className="text-gray-500 hover:text-gray-700 text-sm font-medium"
                                        >
                                            {isCategoryDetailsExpanded ? 'Скрыть' : 'Показать'} таблицу
                                        </button>
                                    </div>
                                    
                                    {isCategoryDetailsExpanded && (
                                        <div>
                                            {/* Переключатель команд */}
                                            <div className="mb-4 flex items-center justify-center gap-4">
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
                                            
                                            {/* Таблица */}
                                            <div className="overflow-x-auto">
                                                <table className="min-w-full bg-white border">
                                                    <thead>
                                                        <tr className="bg-gray-100">
                                                            <th className="p-3 border text-left font-semibold">Категория</th>
                                                            <th className="p-3 border text-center font-semibold">До</th>
                                                            <th className="p-3 border text-center font-semibold">После</th>
                                                            <th className="p-3 border text-center font-semibold">Δ</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody>
                                                        {Object.entries(viewMode === 'z-scores' 
                                                            ? (selectedTeamForTable === 'my_team' ? myData.categories : theirData.categories)
                                                            : (selectedTeamForTable === 'my_team' ? myData.raw_categories : theirData.raw_categories)
                                                        ).map(([cat, data]) => (
                                                            <tr key={cat} className="hover:bg-gray-50">
                                                                <td className="p-3 border font-medium">{cat}</td>
                                                                <td className="p-3 border text-center">{data.before}</td>
                                                                <td className="p-3 border text-center">{data.after}</td>
                                                                <td className={`p-3 border text-center font-bold ${data.delta > 0 ? 'text-green-600' : data.delta < 0 ? 'text-red-600' : 'text-gray-600'}`}>
                                                                    {data.delta > 0 ? '+' : ''}{data.delta}
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </>
                        );
                    })()}
                    
                    {/* Category Rankings Changes - Collapsible Block */}
                    {result.category_rankings && (
                        <CategoryRankingsChanges 
                            categoryRankings={result.category_rankings}
                            myTeamName={result.my_team.name}
                            theirTeamName={result.their_team.name}
                        />
                    )}
                </div>
            )}
        </div>
    );
};

// Компонент для отображения изменений позиций по категориям
const CategoryRankingsChanges = ({ categoryRankings, myTeamName, theirTeamName }) => {
    const [isExpanded, setIsExpanded] = useState(false);
    const [selectedTeam, setSelectedTeam] = useState('my_team');
    
    // Получаем все категории для полной таблицы
    const allCategories = Object.keys(categoryRankings.my_team || {});
    
    // Функция для получения цвета бейджа позиции (как в CategoryRankings)
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
                            value={selectedTeam}
                            onChange={(e) => setSelectedTeam(e.target.value)}
                            className="border p-2 rounded text-sm font-medium min-w-[200px]"
                        >
                            <option value="my_team">{myTeamName}</option>
                            <option value="their_team">{theirTeamName}</option>
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
                                    const data = selectedTeam === 'my_team' 
                                        ? categoryRankings.my_team[cat]
                                        : categoryRankings.their_team[cat];
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

export default TradeAnalyzer;
