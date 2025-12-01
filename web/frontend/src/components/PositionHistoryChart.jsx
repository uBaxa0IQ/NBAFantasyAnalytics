import React, { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import api from '../api';

const PositionHistoryChart = ({ teamId, period, excludeIr }) => {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        if (!teamId) {
            setLoading(false);
            return;
        }

        setLoading(true);
        api.get(`/dashboard/${teamId}/position-history`, {
            params: { period, exclude_ir: excludeIr }
        })
            .then(res => {
                // Проверяем, есть ли ошибка в ответе сервера
                if (res.data && res.data.error) {
                    setError(res.data.error);
                    setData(null);
                } else {
                    setData(res.data);
                    setError(null);
                }
            })
            .catch(err => {
                console.error('Error fetching position history:', err);
                
                // Извлекаем конкретное сообщение об ошибке
                let errorMessage = 'Ошибка загрузки данных';
                
                if (err.response) {
                    // Сервер ответил с ошибкой
                    const status = err.response.status;
                    const serverError = err.response.data?.error || err.response.data?.detail;
                    
                    if (serverError) {
                        errorMessage = serverError;
                    } else if (status === 404) {
                        errorMessage = 'Команда не найдена';
                    } else if (status === 500) {
                        errorMessage = 'Ошибка сервера при расчете позиций';
                    } else if (status === 503) {
                        errorMessage = 'Сервис временно недоступен';
                    } else {
                        errorMessage = `Ошибка сервера (код ${status})`;
                    }
                } else if (err.request) {
                    // Запрос отправлен, но ответа нет (таймаут или сеть)
                    if (err.code === 'ECONNABORTED' || err.message?.includes('timeout')) {
                        errorMessage = 'Превышено время ожидания ответа. Попробуйте позже';
                    } else {
                        errorMessage = 'Нет связи с сервером. Проверьте подключение к интернету';
                    }
                } else {
                    // Ошибка при настройке запроса
                    errorMessage = `Ошибка запроса: ${err.message || 'Неизвестная ошибка'}`;
                }
                
                setError(errorMessage);
                setData(null);
            })
            .finally(() => {
                setLoading(false);
            });
    }, [teamId, period, excludeIr]);

    if (loading) {
        return (
            <div className="flex items-center justify-center p-8">
                <div className="text-gray-500">Загрузка...</div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="text-center p-4 text-red-500">
                {error}
            </div>
        );
    }

    if (!data || !data.position_history || data.position_history.length === 0) {
        return (
            <div className="text-center p-4 text-gray-500">
                Нет данных для отображения
            </div>
        );
    }

    // Подготавливаем данные для графика
    // Инвертируем ось Y, чтобы позиция 1 была сверху
    const chartData = data.position_history.map(item => ({
        week: `Неделя ${item.week}`,
        weekNum: item.week,
        position: item.position
    }));

    // Находим лучшую и худшую позиции для дополнительной информации
    const positions = data.position_history.map(item => item.position);
    const bestPosition = Math.min(...positions);
    const worstPosition = Math.max(...positions);
    const currentPosition = data.position_history[data.position_history.length - 1]?.position;
    const firstPosition = data.position_history[0]?.position;
    const change = currentPosition - firstPosition;
    
    // Генерируем метки для оси Y, обязательно включая позицию 1
    const maxPosition = Math.max(worstPosition, 1);
    const yAxisTicks = [];
    // Всегда добавляем 1
    yAxisTicks.push(1);
    // Добавляем остальные метки с шагом, чтобы не было слишком много
    const step = Math.max(1, Math.ceil((maxPosition - 1) / 6));
    for (let i = 1 + step; i <= maxPosition; i += step) {
        if (!yAxisTicks.includes(i)) {
            yAxisTicks.push(i);
        }
    }
    // Всегда добавляем максимальную позицию, если её еще нет
    if (!yAxisTicks.includes(maxPosition)) {
        yAxisTicks.push(maxPosition);
    }
    yAxisTicks.sort((a, b) => b - a); // Сортируем по убыванию (так как reversed)

    // Кастомный формат для Tooltip
    const CustomTooltip = ({ active, payload }) => {
        if (active && payload && payload.length) {
            return (
                <div className="bg-white p-3 border rounded shadow-lg">
                    <p className="font-semibold">{payload[0].payload.week}</p>
                    <p className="text-blue-600">
                        Позиция: <span className="font-bold">#{payload[0].value}</span>
                    </p>
                </div>
            );
        }
        return null;
    };

    return (
        <div className="w-full">
            {/* Статистика */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                <div className="bg-blue-50 p-3 rounded">
                    <div className="text-sm text-gray-600">Текущая позиция</div>
                    <div className="text-2xl font-bold text-blue-600">#{currentPosition}</div>
                </div>
                <div className="bg-green-50 p-3 rounded">
                    <div className="text-sm text-gray-600">Лучшая позиция</div>
                    <div className="text-2xl font-bold text-green-600">#{bestPosition}</div>
                </div>
                <div className="bg-red-50 p-3 rounded">
                    <div className="text-sm text-gray-600">Худшая позиция</div>
                    <div className="text-2xl font-bold text-red-600">#{worstPosition}</div>
                </div>
            </div>

            {/* График */}
            <ResponsiveContainer width="100%" height={300}>
                <LineChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis 
                        dataKey="week" 
                        stroke="#6b7280"
                        tick={{ fill: '#6b7280', fontSize: 12 }}
                    />
                    <YAxis 
                        reversed
                        domain={[1, maxPosition + 1]}
                        stroke="#6b7280"
                        tick={{ fill: '#6b7280', fontSize: 12 }}
                        label={{ value: 'Позиция', angle: -90, position: 'insideLeft', style: { fill: '#6b7280' } }}
                        allowDecimals={false}
                        ticks={yAxisTicks}
                    />
                    <Tooltip content={<CustomTooltip />} />
                    <Legend />
                    <Line 
                        type="monotone" 
                        dataKey="position" 
                        stroke="#3b82f6" 
                        strokeWidth={3}
                        dot={{ fill: '#3b82f6', r: 5 }}
                        activeDot={{ r: 7 }}
                        name="Позиция в лиге"
                    />
                </LineChart>
            </ResponsiveContainer>
        </div>
    );
};

export default PositionHistoryChart;

