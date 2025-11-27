import React from 'react';
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Legend } from 'recharts';
import api from '../api';

const PlayerBalanceRadar = ({ playerName, period = "2026_total" }) => {
    const [data, setData] = React.useState(null);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState(null);

    React.useEffect(() => {
        if (!playerName) {
            setLoading(false);
            return;
        }

        const fetchBalanceData = async () => {
            try {
                setLoading(true);
                
                const response = await api.get(`/player/${encodeURIComponent(playerName)}/balance`, {
                    params: { period }
                });
                const result = response.data;

                if (result.error) {
                    setError(result.error);
                    setData(null);
                    setLoading(false);
                    return;
                }

                setData(result.data);
                setError(null);
            } catch (err) {
                setError('Ошибка загрузки данных');
                console.error('Error fetching player balance data:', err);
            } finally {
                setLoading(false);
            }
        };

        fetchBalanceData();
    }, [playerName, period]);

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

    if (!data || data.length === 0) {
        return (
            <div className="text-center p-4 text-gray-500">
                Нет данных для отображения
            </div>
        );
    }

    return (
        <div className="w-full h-full">
            <ResponsiveContainer width="100%" height={400}>
                <RadarChart data={data}>
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
                    <Radar
                        name={playerName}
                        dataKey="value"
                        stroke="#3b82f6"
                        fill="#3b82f6"
                        fillOpacity={0.4}
                        strokeWidth={2}
                    />
                    <Legend 
                        wrapperStyle={{ paddingTop: '20px' }}
                        iconType="line"
                    />
                </RadarChart>
            </ResponsiveContainer>
        </div>
    );
};

export default PlayerBalanceRadar;

