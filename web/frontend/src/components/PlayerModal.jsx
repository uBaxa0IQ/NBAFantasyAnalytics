import React, { useState, useEffect } from 'react';
import api from '../api';
import PlayerBalanceRadar from './PlayerBalanceRadar';
import PlayerTrendsChart from './PlayerTrendsChart';
import { getSeasonConfig } from '../utils/periods';
import { LEAGUE_CATEGORIES as CATEGORIES } from '../utils/categories';

const PlayerModal = ({ player, onClose, onAddToComparison, onRemoveFromComparison, isInComparison = false }) => {
    const periods = React.useMemo(() => getSeasonConfig().periods, []);
    const [trends, setTrends] = useState(null);
    const [loadingTrends, setLoadingTrends] = useState(false);
    const isDraftProfile = player?.analysis_context === 'draft';
    const [activeTab, setActiveTab] = useState(isDraftProfile ? 'current' : 'radar');
    const [statsView, setStatsView] = useState('z-scores'); // 'z-scores' или 'raw'
    const [rawStats, setRawStats] = useState(null);
    const [loadingStats, setLoadingStats] = useState(false);
    const [radarPeriod, setRadarPeriod] = useState(periods.total);

    useEffect(() => {
        if (player && activeTab === 'trends' && !isDraftProfile) {
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
    }, [player, activeTab, isDraftProfile]);

    // Загружаем статистику, если её нет в объекте player
    useEffect(() => {
        if (player && activeTab === 'current' && statsView === 'raw' && !player.stats) {
            setLoadingStats(true);
            // Пытаемся получить статистику из all-players эндпоинта
            api.get(`/all-players?period=${periods.total}`)
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
    }, [player, activeTab, statsView, periods.total]);

    if (!player) return null;

    const zScores = player.z_scores || {};
    const stats = rawStats || player.stats || {};
    
    // Категории для отображения
    
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
            // Для счетных категорий (PTS, REB, AST и т.д.) показываем с одним знаком после запятой
            if (category === 'PTS' || category === 'REB' || category === 'AST' || 
                category === 'STL' || category === 'BLK' || category === '3PM' || category === 'DD') {
                return value.toFixed(1);
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
                                {isDraftProfile && <span>GP: <strong>{player.games_played || player.stats?.GP || '—'}</strong></span>}
                                {isDraftProfile && player.espn_adp != null && <span>ESPN ADP: <strong>{player.espn_adp.toFixed(1)}</strong></span>}
                            </div>
                            {isDraftProfile && <div className="mt-2 text-xs text-gray-500">Профиль для драфта · источник статистики: {player.stats_source || 'проекция / прошлый сезон'}</div>}
                        </div>
                        <div className="flex items-center gap-3">
                            {onAddToComparison && (
                                <button
                                    onClick={() => {
                                        if (isInComparison) {
                                            onRemoveFromComparison?.(player.name);
                                        } else {
                                            onAddToComparison(player);
                                        }
                                    }}
                                    className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
                                        isInComparison
                                            ? 'bg-red-100 text-red-700 hover:bg-red-200'
                                            : 'bg-blue-100 text-blue-700 hover:bg-blue-200'
                                    }`}
                                >
                                    {isInComparison ? 'Убрать из сравнения' : 'Добавить к сравнению'}
                                </button>
                            )}
                            <button
                                onClick={onClose}
                                className="text-gray-500 hover:text-gray-700 text-2xl font-bold"
                            >
                                ×
                            </button>
                        </div>
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
                            {!isDraftProfile && <button
                                onClick={() => setActiveTab('trends')}
                                className={`px-4 py-2 font-medium transition-colors ${activeTab === 'trends' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500 hover:text-gray-700'}`}
                            >Тренды</button>}
                        </div>
                    </div>

                    {/* Radar Tab */}
                    {activeTab === 'radar' && (
                        <div>
                            <div className="flex items-center justify-between mb-4">
                                <h3 className="text-lg font-semibold">Баланс по категориям</h3>
                                {!isDraftProfile && <div>
                                    <label className="mr-2 text-sm text-gray-600">Период:</label>
                                    <select 
                                        className="border p-2 rounded text-sm" 
                                        value={radarPeriod} 
                                        onChange={e => setRadarPeriod(e.target.value)}
                                    >
                                        <option value={periods.total}>Весь сезон</option>
                                        <option value={periods.last_30}>Последние 30 дней</option>
                                        <option value={periods.last_15}>Последние 15 дней</option>
                                        <option value={periods.last_7}>Последние 7 дней</option>
                                        <option value={periods.weighted}>Взвешенный (Универсальный)</option>
                                    </select>
                                </div>}
                            </div>
                            <PlayerBalanceRadar 
                                playerName={player.name} 
                                period={radarPeriod}
                                fallbackZScores={isDraftProfile ? zScores : null}
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
                            {loadingTrends ? (
                                <div className="text-center text-gray-500 py-8">Загрузка трендов...</div>
                            ) : trends && trends.trends && trends.trends.length > 0 ? (
                                <PlayerTrendsChart trendsData={trends} />
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
