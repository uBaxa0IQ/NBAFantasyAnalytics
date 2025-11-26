import React from 'react';
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Legend } from 'recharts';
import api from '../api';

const TeamBalanceRadar = ({ teamId, period, puntCategories, excludeIr = false, compareTeamId = null, compareTeamName = null }) => {
    const [data, setData] = React.useState(null);
    const [compareData, setCompareData] = React.useState(null);
    const [teamName, setTeamName] = React.useState('');
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState(null);

    React.useEffect(() => {
        if (!teamId) {
            setLoading(false);
            return;
        }

        const fetchBalanceData = async () => {
            try {
                setLoading(true);
                const puntStr = puntCategories.join(',');
                
                // Загружаем данные для основной команды
                const response = await api.get(`/team-balance/${teamId}`, {
                    params: {
                        period,
                        punt_categories: puntStr,
                        exclude_ir: excludeIr
                    }
                });
                const result = response.data;

                if (result.error) {
                    setError(result.error);
                    setData(null);
                    setLoading(false);
                    return;
                }

                setData(result.data);
                setTeamName(result.team_name || 'Моя команда');
                setError(null);

                // Если нужно сравнение, загружаем данные для второй команды
                if (compareTeamId) {
                    const compareResponse = await api.get(`/team-balance/${compareTeamId}`, {
                        params: {
                            period,
                            punt_categories: puntStr,
                            exclude_ir: excludeIr
                        }
                    });
                    const compareResult = compareResponse.data;

                    if (compareResult.error) {
                        setCompareData(null);
                    } else {
                        setCompareData(compareResult.data);
                    }
                } else {
                    setCompareData(null);
                }
            } catch (err) {
                setError('Ошибка загрузки данных');
                console.error('Error fetching balance data:', err);
            } finally {
                setLoading(false);
            }
        };

        fetchBalanceData();
    }, [teamId, period, puntCategories, excludeIr, compareTeamId]);

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

    // Объединяем данные для отображения двух радаров
    // Создаем объект для каждой категории с значениями обеих команд
    const mergedData = data.map(item => {
        const compareItem = compareData 
            ? compareData.find(c => c.category === item.category)
            : null;
        
        return {
            category: item.category,
            myValue: item.value,
            compareValue: compareItem ? compareItem.value : null
        };
    });

    const displayName = compareTeamName || 'Сравнение';

    return (
        <div className="w-full h-full">
            <ResponsiveContainer width="100%" height={400}>
                <RadarChart data={mergedData}>
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
                        name={teamName}
                        dataKey="myValue"
                        stroke="#3b82f6"
                        fill="#3b82f6"
                        fillOpacity={0.4}
                        strokeWidth={2}
                    />
                    {compareData && compareData.length > 0 && (
                        <Radar
                            name={displayName}
                            dataKey="compareValue"
                            stroke="#ef4444"
                            fill="#ef4444"
                            fillOpacity={0.4}
                            strokeWidth={2}
                        />
                    )}
                    <Legend 
                        wrapperStyle={{ paddingTop: '20px' }}
                        iconType="line"
                    />
                </RadarChart>
            </ResponsiveContainer>
        </div>
    );
};

export default TeamBalanceRadar;
