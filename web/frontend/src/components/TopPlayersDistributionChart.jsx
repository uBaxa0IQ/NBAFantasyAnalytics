import React, { useMemo } from 'react';
import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts';
import { LEAGUE_CATEGORIES as CATEGORIES } from '../utils/categories';

const COLORS = [
    '#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6',
    '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1',
    '#14b8a6', '#a855f7', '#f43f5e', '#0ea5e9', '#22c55e'
];

const TopPlayersDistributionChart = ({ players, topN, puntCategories = [] }) => {
    const chartData = useMemo(() => {
        if (!players || players.length === 0) return [];

        // Рассчитываем total Z-score для каждого игрока с учетом пант-категорий
        const playersWithTotalZ = players.map(player => {
            let totalZ = 0;
            CATEGORIES.forEach(cat => {
                if (!puntCategories.includes(cat)) {
                    const zValue = player.z_scores?.[cat] || 0;
                    if (typeof zValue === 'number' && isFinite(zValue)) {
                        totalZ += zValue;
                    }
                }
            });
            return {
                ...player,
                totalZ
            };
        });

        // Сортируем по total Z-score (по убыванию)
        playersWithTotalZ.sort((a, b) => b.totalZ - a.totalZ);

        // Берем топ-N
        const topPlayers = playersWithTotalZ.slice(0, topN);

        // Группируем по fantasy_team
        const teamDistribution = {};
        topPlayers.forEach(player => {
            const teamName = player.fantasy_team || 'Без команды';
            if (!teamDistribution[teamName]) {
                teamDistribution[teamName] = {
                    name: teamName,
                    count: 0,
                    players: []
                };
            }
            teamDistribution[teamName].count++;
            teamDistribution[teamName].players.push({
                name: player.name,
                totalZ: player.totalZ
            });
        });

        // Преобразуем в массив для диаграммы
        const data = Object.values(teamDistribution)
            .map((team, index) => ({
                name: team.name,
                value: team.count,
                percentage: ((team.count / topN) * 100).toFixed(1),
                players: team.players,
                color: COLORS[index % COLORS.length]
            }))
            .sort((a, b) => b.value - a.value); // Сортируем по количеству игроков

        return data;
    }, [players, topN, puntCategories]);

    const CustomTooltip = ({ active, payload }) => {
        if (active && payload && payload.length) {
            const data = payload[0];
            return (
                <div className="bg-white border rounded-lg shadow-lg p-4">
                    <p className="font-semibold mb-2">{data.name}</p>
                    <p className="text-sm text-gray-600">
                        Игроков в топ-{topN}: <span className="font-bold">{data.value}</span> ({data.payload.percentage}%)
                    </p>
                    {data.payload.players && data.payload.players.length > 0 && (
                        <div className="mt-2 pt-2 border-t">
                            <p className="text-xs font-medium text-gray-500 mb-1">Игроки:</p>
                            <div className="max-h-32 overflow-y-auto">
                                {data.payload.players.map((player, idx) => (
                                    <div key={idx} className="text-xs text-gray-700">
                                        {player.name} ({player.totalZ.toFixed(2)})
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            );
        }
        return null;
    };


    if (chartData.length === 0) {
        return (
            <div className="bg-white border rounded-lg p-6 shadow-sm">
                <p className="text-gray-500 text-center">Нет данных для отображения</p>
            </div>
        );
    }

    return (
        <div className="bg-white border rounded-lg p-6 shadow-sm">
            <div className="h-80 w-full">
                <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                        <Pie
                            data={chartData}
                            cx="50%"
                            cy="50%"
                            labelLine={false}
                            outerRadius={100}
                            fill="#8884d8"
                            dataKey="value"
                        >
                            {chartData.map((entry, index) => (
                                <Cell key={`cell-${index}`} fill={entry.color} />
                            ))}
                        </Pie>
                        <Tooltip content={<CustomTooltip />} />
                    </PieChart>
                </ResponsiveContainer>
            </div>
            <div className="mt-4">
                <h4 className="text-sm font-semibold text-gray-700 mb-2">Легенда:</h4>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2 max-h-40 overflow-y-auto">
                    {chartData.map((entry, index) => (
                        <div key={index} className="flex items-center gap-2 text-sm">
                            <div
                                className="w-4 h-4 rounded"
                                style={{ backgroundColor: entry.color }}
                            />
                            <span className="text-gray-700">{entry.name}:</span>
                            <span className="font-semibold">{entry.value}</span>
                            <span className="text-gray-500">({entry.percentage}%)</span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
};

export default TopPlayersDistributionChart;
