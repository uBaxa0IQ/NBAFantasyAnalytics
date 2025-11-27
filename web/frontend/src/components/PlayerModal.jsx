import React, { useState, useEffect } from 'react';
import api from '../api';
import PlayerBalanceRadar from './PlayerBalanceRadar';

const PlayerModal = ({ player, onClose }) => {
    const [trends, setTrends] = useState(null);
    const [loadingTrends, setLoadingTrends] = useState(false);
    const [activeTab, setActiveTab] = useState('radar'); // 'radar', 'current' или 'trends'
    const [statsView, setStatsView] = useState('z-scores'); // 'z-scores' или 'raw'
    const [rawStats, setRawStats] = useState(null);
    const [loadingStats, setLoadingStats] = useState(false);
    const [radarPeriod, setRadarPeriod] = useState('2026_total');

    useEffect(() => {
        if (player && activeTab === 'trends') {
            setLoadingTrends(true);
            api.get(`/player/${encodeURIComponent(player.name)}/trends`)
                .then(res => {
                    setTrends(res.data);
                    setLoadingTrends(false);
                })
                .catch(err => {
                    console.error('Error fetching player trends:', err);
                    setLoadingTrends(false);
                });
        }
    }, [player, activeTab]);

    // Загружаем статистику, если её нет в объекте player
    useEffect(() => {
        if (player && activeTab === 'current' && statsView === 'raw' && !player.stats) {
            setLoadingStats(true);
            // Пытаемся получить статистику из all-players эндпоинта
            api.get(`/all-players?period=2026_total`)
                .then(res => {
                    const allPlayers = res.data.players || [];
                    const foundPlayer = allPlayers.find(p => p.name === player.name);
                    if (foundPlayer && foundPlayer.stats) {
                        setRawStats(foundPlayer.stats);
                    }
                    setLoadingStats(false);
                })
                .catch(err => {
                    console.error('Error fetching player stats:', err);
                    setLoadingStats(false);
                });
        } else if (player && player.stats) {
            setRawStats(player.stats);
        }
    }, [player, activeTab, statsView]);

    if (!player) return null;

    const zScores = player.z_scores || {};
    const stats = rawStats || player.stats || {};
    
    // Категории для отображения
    const CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'FG%', 'FT%', '3PT%', 'A/TO'];
    
    // Форматирование значения для отображения
    const formatStatValue = (category, value) => {
        if (value === undefined || value === null) return 'N/A';
        if (category === 'FG%' || category === 'FT%' || category === '3PT%') {
            // Проценты: ESPN API возвращает в формате 0.0-1.0, конвертируем в проценты
            const numValue = typeof value === 'number' ? value : parseFloat(value);
            // Если значение больше 1, значит уже в процентах (0-100)
            if (numValue > 1.0) {
                return `${numValue.toFixed(1)}%`;
            } else {
                return `${(numValue * 100).toFixed(1)}%`;
            }
        } else if (category === 'A/TO') {
            return value.toFixed(2);
        } else {
            // Для целых чисел (PTS, REB, AST и т.д.) показываем без десятичных
            if (category === 'PTS' || category === 'REB' || category === 'AST' || 
                category === 'STL' || category === 'BLK' || category === '3PM' || category === 'DD') {
                return Math.round(value).toString();
            }
            return value.toFixed(1);
        }
    };

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={onClose}>
            <div className="bg-white rounded-lg shadow-xl max-w-5xl w-full max-h-[90vh] overflow-y-auto m-4" onClick={e => e.stopPropagation()}>
                <div className="p-6">
                    {/* Header */}
                    <div className="flex justify-between items-start mb-6">
                        <div>
                            <h2 className="text-2xl font-bold">{player.name}</h2>
                            <div className="flex gap-4 mt-2 text-sm text-gray-600">
                                <span>Позиция: <strong>{player.position}</strong></span>
                                <span>NBA Team: <strong>{player.nba_team}</strong></span>
                                {player.fantasy_team && (
                                    <span>Fantasy Team: <strong>{player.fantasy_team}</strong></span>
                                )}
                            </div>
                        </div>
                        <button
                            onClick={onClose}
                            className="text-gray-500 hover:text-gray-700 text-2xl font-bold"
                        >
                            ×
                        </button>
                    </div>

                    {/* Tabs */}
                    <div className="mb-4 border-b">
                        <div className="flex gap-2">
                            <button
                                onClick={() => setActiveTab('radar')}
                                className={`px-4 py-2 font-medium transition-colors ${
                                    activeTab === 'radar'
                                        ? 'border-b-2 border-blue-600 text-blue-600'
                                        : 'text-gray-500 hover:text-gray-700'
                                }`}
                            >
                                Радар
                            </button>
                            <button
                                onClick={() => setActiveTab('current')}
                                className={`px-4 py-2 font-medium transition-colors ${
                                    activeTab === 'current'
                                        ? 'border-b-2 border-blue-600 text-blue-600'
                                        : 'text-gray-500 hover:text-gray-700'
                                }`}
                            >
                                Текущая статистика
                            </button>
                            <button
                                onClick={() => setActiveTab('trends')}
                                className={`px-4 py-2 font-medium transition-colors ${
                                    activeTab === 'trends'
                                        ? 'border-b-2 border-blue-600 text-blue-600'
                                        : 'text-gray-500 hover:text-gray-700'
                                }`}
                            >
                                Тренды
                            </button>
                        </div>
                    </div>

                    {/* Radar Tab */}
                    {activeTab === 'radar' && (
                        <div>
                            <div className="flex items-center justify-between mb-4">
                                <h3 className="text-lg font-semibold">Баланс по категориям</h3>
                                <div>
                                    <label className="mr-2 text-sm text-gray-600">Период:</label>
                                    <select 
                                        className="border p-2 rounded text-sm" 
                                        value={radarPeriod} 
                                        onChange={e => setRadarPeriod(e.target.value)}
                                    >
                                        <option value="2026_total">Весь сезон</option>
                                        <option value="2026_last_30">Последние 30 дней</option>
                                        <option value="2026_last_15">Последние 15 дней</option>
                                        <option value="2026_last_7">Последние 7 дней</option>
                                        <option value="2026_projected">Прогноз</option>
                                    </select>
                                </div>
                            </div>
                            <PlayerBalanceRadar 
                                playerName={player.name} 
                                period={radarPeriod}
                            />
                        </div>
                    )}

                    {/* Current Stats Tab */}
                    {activeTab === 'current' && (
                        <div>
                            <div className="flex items-center justify-between mb-4">
                                <h3 className="text-lg font-semibold">
                                    {statsView === 'z-scores' ? 'Z-Scores' : 'Обычная статистика'}
                                </h3>
                                <div className="inline-flex rounded-lg border border-gray-300 bg-white p-1">
                                    <button
                                        onClick={() => setStatsView('z-scores')}
                                        className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
                                            statsView === 'z-scores'
                                                ? 'bg-blue-600 text-white'
                                                : 'text-gray-700 hover:bg-gray-100'
                                        }`}
                                    >
                                        Z-Scores
                                    </button>
                                    <button
                                        onClick={() => setStatsView('raw')}
                                        className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
                                            statsView === 'raw'
                                                ? 'bg-blue-600 text-white'
                                                : 'text-gray-700 hover:bg-gray-100'
                                        }`}
                                    >
                                        Статистика
                                    </button>
                                </div>
                            </div>
                            
                            {statsView === 'z-scores' ? (
                                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                                    {Object.entries(zScores).map(([cat, val]) => {
                                        let colorClass = val > 0 ? 'text-green-600' : 'text-red-600';
                                        if (val === 0) colorClass = 'text-gray-400';

                                        return (
                                            <div key={cat} className="bg-gray-50 p-3 rounded">
                                                <div className="text-sm text-gray-600">{cat}</div>
                                                <div className={`text-xl font-bold ${colorClass}`}>
                                                    {typeof val === 'number' ? val.toFixed(2) : val}
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            ) : (
                                <>
                                    {loadingStats ? (
                                        <div className="text-center text-gray-500 py-8">Загрузка статистики...</div>
                                    ) : (
                                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                                            {CATEGORIES.map(cat => {
                                                const value = stats[cat];
                                                if (value === undefined || value === null) return null;
                                                
                                                return (
                                                    <div key={cat} className="bg-gray-50 p-3 rounded">
                                                        <div className="text-sm text-gray-600">{cat}</div>
                                                        <div className="text-xl font-bold text-gray-800">
                                                            {formatStatValue(cat, value)}
                                                        </div>
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    )}

                    {/* Trends Tab */}
                    {activeTab === 'trends' && (
                        <div>
                            <h3 className="text-lg font-semibold mb-4">Тренды по периодам</h3>
                            {loadingTrends ? (
                                <div className="text-center text-gray-500 py-8">Загрузка трендов...</div>
                            ) : trends && trends.trends && trends.trends.length > 0 ? (
                                <div className="overflow-x-auto">
                                    <table className="min-w-full text-sm">
                                        <thead>
                                            <tr className="bg-gray-100 border-b">
                                                <th className="px-4 py-3 text-left font-semibold">Период</th>
                                                <th className="px-4 py-3 text-center font-semibold">Total Z</th>
                                                {Object.keys(trends.trends[0].z_scores || {}).map(cat => (
                                                    <th key={cat} className="px-4 py-3 text-center font-semibold">{cat}</th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {trends.trends.map((point, idx) => {
                                                // Определяем изменение относительно "Весь сезон" (базовый период)
                                                let changeIndicator = '';
                                                // Находим период "Весь сезон" явно
                                                const basePeriod = trends.trends.find(p => p.period === 'Весь сезон');
                                                
                                                if (basePeriod && point.period !== 'Весь сезон') {
                                                    const change = point.total_z - basePeriod.total_z;
                                                    if (change > 0) {
                                                        changeIndicator = `+${change.toFixed(2)}`;
                                                    } else if (change < 0) {
                                                        changeIndicator = change.toFixed(2);
                                                    }
                                                }
                                                
                                                return (
                                                    <tr key={idx} className="border-b hover:bg-gray-50">
                                                        <td className="px-4 py-3 font-medium">{point.period}</td>
                                                        <td className="px-4 py-3 text-center">
                                                            <div className="font-bold">{point.total_z}</div>
                                                            {changeIndicator && (
                                                                <div className={`text-xs ${changeIndicator.startsWith('+') ? 'text-green-600' : 'text-red-600'}`} title="Изменение относительно всего сезона">
                                                                    {changeIndicator}
                                                                </div>
                                                            )}
                                                        </td>
                                                        {Object.entries(point.z_scores || {}).map(([cat, val]) => {
                                                            const colorClass = val > 0 ? 'text-green-600' : val < 0 ? 'text-red-600' : 'text-gray-400';
                                                            return (
                                                                <td key={cat} className={`px-4 py-3 text-center ${colorClass}`}>
                                                                    {typeof val === 'number' ? val.toFixed(2) : val}
                                                                </td>
                                                            );
                                                        })}
                                                    </tr>
                                                );
                                            })}
                                        </tbody>
                                    </table>
                                </div>
                            ) : (
                                <div className="text-center text-gray-500 py-8">Нет данных о трендах</div>
                            )}
                        </div>
                    )}

                    {/* Close Button */}
                    <div className="mt-6 flex justify-end">
                        <button
                            onClick={onClose}
                            className="bg-blue-600 text-white px-6 py-2 rounded hover:bg-blue-700"
                        >
                            Закрыть
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default PlayerModal;
