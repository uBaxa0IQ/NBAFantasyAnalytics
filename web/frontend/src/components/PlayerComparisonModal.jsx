import React, { useState, useEffect } from 'react';
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Legend } from 'recharts';
import api from '../api';

const CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'FG%', 'FT%', '3PT%', 'A/TO'];
const COLORS = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6'];

const PlayerComparisonModal = ({ players, onClose }) => {
    const [comparisonData, setComparisonData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [period, setPeriod] = useState('2026_total');
    const [statsView, setStatsView] = useState('z-scores'); // 'z-scores' или 'raw'

    useEffect(() => {
        if (!players || players.length === 0) {
            setLoading(false);
            return;
        }

        const fetchComparisonData = async () => {
            setLoading(true);
            try {
                // Загружаем данные для каждого игрока (радар и статистику)
                const balancePromises = players.map(player =>
                    api.get(`/player/${encodeURIComponent(player.name)}/balance`, {
                        params: { period }
                    }).catch(() => ({ data: { data: [] } }))
                );

                // Загружаем статистику из all-players для получения raw stats
                const allPlayersResponse = await api.get(`/all-players?period=${period}`).catch(() => ({ data: { players: [] } }));
                const allPlayersMap = {};
                (allPlayersResponse.data.players || []).forEach(p => {
                    allPlayersMap[p.name] = p.stats || {};
                });

                const balanceResponses = await Promise.all(balancePromises);
                const data = balanceResponses.map((res, idx) => {
                    const radarData = res.data.data || [];
                    // Преобразуем radarData в объект z_scores для использования в таблице
                    const z_scores = radarData.reduce((acc, item) => {
                        acc[item.category] = item.value;
                        return acc;
                    }, {});
                    
                    return {
                        ...players[idx],
                        radarData: radarData,
                        z_scores: z_scores,
                        stats: allPlayersMap[players[idx].name] || players[idx].stats || {}
                    };
                });

                setComparisonData(data);
            } catch (err) {
                console.error('Error fetching comparison data:', err);
            } finally {
                setLoading(false);
            }
        };

        fetchComparisonData();
    }, [players, period]);

    // Подготовка данных для радара (объединение всех игроков)
    const getRadarData = () => {
        if (!comparisonData || comparisonData.length === 0) return [];

        const radarDataMap = {};
        
        comparisonData.forEach((playerData, playerIdx) => {
            playerData.radarData.forEach(item => {
                if (!radarDataMap[item.category]) {
                    radarDataMap[item.category] = { category: item.category };
                }
                radarDataMap[item.category][`player${playerIdx}`] = item.value;
            });
        });

        return Object.values(radarDataMap);
    };

    const radarData = getRadarData();

    // Форматирование значения для таблицы
    const formatStatValue = (category, value) => {
        if (value === undefined || value === null) return 'N/A';
        if (category === 'FG%' || category === 'FT%' || category === '3PT%') {
            const numValue = typeof value === 'number' ? value : parseFloat(value);
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
            <div className="bg-white rounded-lg shadow-xl max-w-7xl w-full max-h-[90vh] overflow-y-auto m-4" onClick={e => e.stopPropagation()}>
                <div className="p-6">
                    {/* Header */}
                    <div className="flex justify-between items-start mb-6">
                        <div>
                            <h2 className="text-2xl font-bold">Сравнение игроков</h2>
                            <div className="mt-2 text-sm text-gray-600">
                                {players.length} {players.length === 1 ? 'игрок' : players.length < 5 ? 'игрока' : 'игроков'}
                            </div>
                        </div>
                        <div className="flex items-center gap-4">
                            <div>
                                <label className="mr-2 text-sm text-gray-600">Период:</label>
                                <select 
                                    className="border p-2 rounded text-sm" 
                                    value={period} 
                                    onChange={e => setPeriod(e.target.value)}
                                >
                                    <option value="2026_total">Весь сезон</option>
                                    <option value="2026_last_30">Последние 30 дней</option>
                                    <option value="2026_last_15">Последние 15 дней</option>
                                    <option value="2026_last_7">Последние 7 дней</option>
                                    <option value="2026_projected">Прогноз</option>
                                </select>
                            </div>
                            <button
                                onClick={onClose}
                                className="text-gray-500 hover:text-gray-700 text-2xl font-bold"
                            >
                                ×
                            </button>
                        </div>
                    </div>

                    {loading ? (
                        <div className="text-center text-gray-500 py-8">Загрузка данных...</div>
                    ) : comparisonData && comparisonData.length > 0 ? (
                        <>
                            {/* Радар-график */}
                            <div className="mb-6">
                                <h3 className="text-lg font-semibold mb-4">Радар-график Z-scores</h3>
                                <div style={{ height: '400px' }}>
                                    <ResponsiveContainer width="100%" height="100%">
                                        <RadarChart data={radarData}>
                                            <PolarGrid stroke="#e5e7eb" />
                                            <PolarAngleAxis
                                                dataKey="category"
                                                tick={{ fill: '#6b7280', fontSize: 12 }}
                                            />
                                            <PolarRadiusAxis
                                                angle={90}
                                                domain={[0, 'auto']}
                                                tick={{ fill: '#6b7280', fontSize: 10 }}
                                            />
                                            {comparisonData.map((playerData, idx) => (
                                                <Radar
                                                    key={playerData.name}
                                                    name={playerData.name}
                                                    dataKey={`player${idx}`}
                                                    stroke={COLORS[idx % COLORS.length]}
                                                    fill={COLORS[idx % COLORS.length]}
                                                    fillOpacity={0.3}
                                                    strokeWidth={2}
                                                />
                                            ))}
                                            <Legend 
                                                wrapperStyle={{ paddingTop: '20px' }}
                                                iconType="line"
                                            />
                                        </RadarChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>

                            {/* Переключатель вида статистики */}
                            <div className="mb-4 flex justify-center">
                                <div className="inline-flex rounded-lg border border-gray-300 bg-white p-1">
                                    <button
                                        onClick={() => setStatsView('z-scores')}
                                        className={`px-4 py-2 rounded-md font-medium transition-colors ${
                                            statsView === 'z-scores'
                                                ? 'bg-blue-600 text-white'
                                                : 'text-gray-700 hover:bg-gray-100'
                                        }`}
                                    >
                                        Z-Scores
                                    </button>
                                    <button
                                        onClick={() => setStatsView('raw')}
                                        className={`px-4 py-2 rounded-md font-medium transition-colors ${
                                            statsView === 'raw'
                                                ? 'bg-blue-600 text-white'
                                                : 'text-gray-700 hover:bg-gray-100'
                                        }`}
                                    >
                                        Обычная статистика
                                    </button>
                                </div>
                            </div>

                            {/* Таблица сравнения Z-scores */}
                            {statsView === 'z-scores' && (
                            <div className="mb-6">
                                <h3 className="text-lg font-semibold mb-4">Z-scores по категориям</h3>
                                <div className="overflow-x-auto">
                                    <table className="min-w-full text-sm border">
                                        <thead>
                                            <tr className="bg-gray-100 border-b">
                                                <th className="px-4 py-3 text-left font-semibold">Категория</th>
                                                {comparisonData.map((playerData, idx) => (
                                                    <th 
                                                        key={playerData.name}
                                                        className="px-4 py-3 text-center font-semibold"
                                                        style={{ color: COLORS[idx % COLORS.length] }}
                                                    >
                                                        {playerData.name}
                                                    </th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {CATEGORIES.map(cat => {
                                                // Определяем лучшее значение для этой категории
                                                const values = comparisonData.map(playerData => {
                                                    const zScore = playerData.z_scores?.[cat] || 0;
                                                    return typeof zScore === 'number' ? zScore : 0;
                                                });
                                                
                                                // Для TO меньше = лучше, для остальных больше = лучше
                                                const isTO = cat === 'TO';
                                                const bestValue = isTO 
                                                    ? Math.min(...values)
                                                    : Math.max(...values);
                                                
                                                return (
                                                    <tr key={cat} className="border-b hover:bg-gray-50">
                                                        <td className="px-4 py-3 font-medium">{cat}</td>
                                                        {comparisonData.map((playerData, idx) => {
                                                            const zScore = playerData.z_scores?.[cat] || 0;
                                                            const numValue = typeof zScore === 'number' ? zScore : 0;
                                                            const isBest = numValue === bestValue;
                                                            
                                                            let colorClass = zScore > 0 ? 'text-green-600' : zScore < 0 ? 'text-red-600' : 'text-gray-400';
                                                            let bgClass = isBest ? 'bg-green-100' : '';
                                                            
                                                            return (
                                                                <td 
                                                                    key={playerData.name}
                                                                    className={`px-4 py-3 text-center ${colorClass} ${bgClass}`}
                                                                >
                                                                    {typeof zScore === 'number' ? zScore.toFixed(2) : zScore}
                                                                </td>
                                                            );
                                                        })}
                                                    </tr>
                                                );
                                            })}
                                            <tr className="border-t-2 border-gray-300 font-bold">
                                                <td className="px-4 py-3">Total Z</td>
                                                {(() => {
                                                    const totalZValues = comparisonData.map(playerData => {
                                                        return Object.values(playerData.z_scores || {}).reduce((sum, val) => {
                                                            return sum + (typeof val === 'number' && !isNaN(val) ? val : 0);
                                                        }, 0);
                                                    });
                                                    const bestTotalZ = Math.max(...totalZValues);
                                                    
                                                    return comparisonData.map((playerData, idx) => {
                                                        const totalZ = totalZValues[idx];
                                                        const colorClass = totalZ > 0 ? 'text-green-600' : totalZ < 0 ? 'text-red-600' : 'text-gray-400';
                                                        const isBest = totalZ === bestTotalZ;
                                                        const bgClass = isBest ? 'bg-green-100' : '';
                                                        return (
                                                            <td 
                                                                key={playerData.name}
                                                                className={`px-4 py-3 text-center ${colorClass} ${bgClass}`}
                                                            >
                                                                {totalZ.toFixed(2)}
                                                            </td>
                                                        );
                                                    });
                                                })()}
                                            </tr>
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                            )}

                            {/* Таблица сравнения обычной статистики */}
                            {statsView === 'raw' && comparisonData[0]?.stats && (
                                <div className="mb-6">
                                    <h3 className="text-lg font-semibold mb-4">Обычная статистика</h3>
                                    <div className="overflow-x-auto">
                                        <table className="min-w-full text-sm border">
                                            <thead>
                                                <tr className="bg-gray-100 border-b">
                                                    <th className="px-4 py-3 text-left font-semibold">Категория</th>
                                                    {comparisonData.map((playerData, idx) => (
                                                        <th 
                                                            key={playerData.name}
                                                            className="px-4 py-3 text-center font-semibold"
                                                            style={{ color: COLORS[idx % COLORS.length] }}
                                                        >
                                                            {playerData.name}
                                                        </th>
                                                    ))}
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {CATEGORIES.map(cat => {
                                                    // Определяем лучшее значение для этой категории
                                                    const values = comparisonData.map(playerData => {
                                                        const value = playerData.stats?.[cat];
                                                        if (value === undefined || value === null) return null;
                                                        // Для процентов конвертируем в число, если нужно
                                                        if (cat === 'FG%' || cat === 'FT%' || cat === '3PT%') {
                                                            const numValue = typeof value === 'number' ? value : parseFloat(value);
                                                            return numValue > 1.0 ? numValue : numValue * 100;
                                                        }
                                                        return typeof value === 'number' ? value : parseFloat(value);
                                                    }).filter(v => v !== null && !isNaN(v));
                                                    
                                                    if (values.length === 0) {
                                                        return (
                                                            <tr key={cat} className="border-b hover:bg-gray-50">
                                                                <td className="px-4 py-3 font-medium">{cat}</td>
                                                                {comparisonData.map((playerData) => (
                                                                    <td key={playerData.name} className="px-4 py-3 text-center">
                                                                        N/A
                                                                    </td>
                                                                ))}
                                                            </tr>
                                                        );
                                                    }
                                                    
                                                    // Для TO меньше = лучше, для остальных больше = лучше
                                                    const isTO = cat === 'TO';
                                                    const bestValue = isTO 
                                                        ? Math.min(...values)
                                                        : Math.max(...values);
                                                    
                                                    return (
                                                        <tr key={cat} className="border-b hover:bg-gray-50">
                                                            <td className="px-4 py-3 font-medium">{cat}</td>
                                                            {comparisonData.map((playerData) => {
                                                                const value = playerData.stats?.[cat];
                                                                if (value === undefined || value === null) {
                                                                    return (
                                                                        <td key={playerData.name} className="px-4 py-3 text-center">
                                                                            N/A
                                                                        </td>
                                                                    );
                                                                }
                                                                
                                                                // Нормализуем значение для сравнения
                                                                let numValue = typeof value === 'number' ? value : parseFloat(value);
                                                                if (cat === 'FG%' || cat === 'FT%' || cat === '3PT%') {
                                                                    numValue = numValue > 1.0 ? numValue : numValue * 100;
                                                                }
                                                                
                                                                const isBest = Math.abs(numValue - bestValue) < 0.01; // Учитываем погрешность округления
                                                                const bgClass = isBest ? 'bg-green-100' : '';
                                                                
                                                                return (
                                                                    <td 
                                                                        key={playerData.name}
                                                                        className={`px-4 py-3 text-center ${bgClass}`}
                                                                    >
                                                                        {formatStatValue(cat, value)}
                                                                    </td>
                                                                );
                                                            })}
                                                        </tr>
                                                    );
                                                })}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            )}
                        </>
                    ) : (
                        <div className="text-center text-gray-500 py-8">Нет данных для сравнения</div>
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

export default PlayerComparisonModal;

