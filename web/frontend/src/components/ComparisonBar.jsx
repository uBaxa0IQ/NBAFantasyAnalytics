import React from 'react';
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, ResponsiveContainer } from 'recharts';

const COLORS = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6'];

const ComparisonBar = ({ players, onCompare, onClear, onRemove }) => {
    // Подготовка данных для мини-радара (только основные категории)
    const mainCategories = ['PTS', 'REB', 'AST', 'STL', 'BLK', 'FG%', 'FT%'];
    
    const radarData = mainCategories.map(cat => {
        const dataPoint = { category: cat };
        players.forEach((player, idx) => {
            const zScore = player.z_scores?.[cat] || 0;
            dataPoint[`player${idx}`] = zScore;
        });
        return dataPoint;
    });

    // Вычисляем Total Z для каждого игрока
    const getTotalZ = (player) => {
        if (!player.z_scores) return 0;
        return Object.values(player.z_scores).reduce((sum, val) => {
            return sum + (typeof val === 'number' && !isNaN(val) ? val : 0);
        }, 0);
    };

    return (
        <div className="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-300 shadow-lg z-40">
            <div className="container mx-auto px-4 py-3">
                <div className="flex items-center justify-between gap-4">
                    {/* Список игроков */}
                    <div className="flex items-center gap-3 flex-1 overflow-x-auto">
                        <span className="text-sm font-semibold text-gray-700 whitespace-nowrap">
                            Сравнение ({players.length}):
                        </span>
                        {players.map((player, idx) => (
                            <div
                                key={player.name}
                                className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2 border border-gray-200 min-w-[200px]"
                            >
                                <div className="flex-1 min-w-0">
                                    <div className="font-medium text-sm truncate">{player.name}</div>
                                    <div className="text-xs text-gray-500">
                                        {player.position} • Total Z: {getTotalZ(player).toFixed(1)}
                                    </div>
                                </div>
                                <button
                                    onClick={() => onRemove(player.name)}
                                    className="text-red-500 hover:text-red-700 text-lg font-bold"
                                    title="Убрать из сравнения"
                                >
                                    ×
                                </button>
                            </div>
                        ))}
                    </div>

                    {/* Мини-радар */}
                    <div className="hidden md:block" style={{ width: '200px', height: '120px' }}>
                        <ResponsiveContainer width="100%" height="100%">
                            <RadarChart data={radarData}>
                                <PolarGrid stroke="#e5e7eb" />
                                <PolarAngleAxis
                                    dataKey="category"
                                    tick={{ fill: '#6b7280', fontSize: 10 }}
                                />
                                {players.map((player, idx) => (
                                    <Radar
                                        key={player.name}
                                        name={player.name}
                                        dataKey={`player${idx}`}
                                        stroke={COLORS[idx % COLORS.length]}
                                        fill={COLORS[idx % COLORS.length]}
                                        fillOpacity={0.3}
                                        strokeWidth={1.5}
                                    />
                                ))}
                            </RadarChart>
                        </ResponsiveContainer>
                    </div>

                    {/* Кнопки */}
                    <div className="flex items-center gap-2 whitespace-nowrap">
                        <button
                            onClick={onCompare}
                            className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 font-medium text-sm"
                        >
                            Сравнить
                        </button>
                        <button
                            onClick={onClear}
                            className="bg-gray-200 text-gray-700 px-4 py-2 rounded hover:bg-gray-300 font-medium text-sm"
                        >
                            Очистить
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default ComparisonBar;

