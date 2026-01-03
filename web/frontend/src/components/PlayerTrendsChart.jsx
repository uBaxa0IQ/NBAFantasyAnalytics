import React from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, LabelList } from 'recharts';

const PlayerTrendsChart = ({ trendsData }) => {
    if (!trendsData || !trendsData.trends || trendsData.trends.length === 0) return null;

    // Преобразуем массив trends в формат для графика
    // Маппинг русских названий периодов на английские для единообразия
    const periodMapping = {
        'Последние 7 дней': 'Last 7',
        'Последние 15 дней': 'Last 15',
        'Последние 30 дней': 'Last 30',
        'Весь сезон': 'Season'
    };

    const data = trendsData.trends.map(trend => ({
        period: periodMapping[trend.period] || trend.period,
        value: trend.total_z
    }));

    // Порядок сортировки периодов (как в дэшборде команды)
    const sortOrder = ['Season', 'Last 30', 'Last 15', 'Last 7'];
    data.sort((a, b) => sortOrder.indexOf(a.period) - sortOrder.indexOf(b.period));

    // Находим минимум и максимум для домена оси Y
    const minValue = Math.min(...data.map(d => d.value));
    const maxValue = Math.max(...data.map(d => d.value));
    
    // Добавляем отступы
    const domainMin = Math.floor(minValue - Math.abs(minValue) * 0.1);
    const domainMax = Math.ceil(maxValue + Math.abs(maxValue) * 0.1);

    return (
        <div className="bg-white border rounded-lg p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-gray-700 mb-4">Динамика формы (Z-Score)</h3>
            <div className="h-64 w-full">
                <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                        data={data}
                        margin={{ top: 20, right: 30, left: 20, bottom: 5 }}
                    >
                        <CartesianGrid strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="period" />
                        <YAxis domain={[domainMin, domainMax]} />
                        <Tooltip 
                            contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 2px 8px rgba(0,0,0,0.1)' }}
                            cursor={{ fill: 'transparent' }}
                        />
                        <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                            {data.map((entry, index) => (
                                <Cell key={`cell-${index}`} fill={entry.value >= 0 ? "#3b82f6" : "#ef4444"} />
                            ))}
                            <LabelList dataKey="value" position="top" />
                        </Bar>
                    </BarChart>
                </ResponsiveContainer>
            </div>
            <p className="text-xs text-gray-500 mt-2 text-center">
                Total Z-Score игрока за разные периоды времени
            </p>
        </div>
    );
};

export default PlayerTrendsChart;

