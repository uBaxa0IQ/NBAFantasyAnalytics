import React, { useRef, useLayoutEffect, useState } from 'react';
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Legend } from 'recharts';
import api from '../api';

const CHART_HEIGHT = 400;

const TeamBalanceRadar = ({ teamId, period, simulationMode = 'all', compareTeamId = null, compareTeamName = null }) => {
    const [data, setData] = useState(null);
    const [compareData, setCompareData] = useState(null);
    const [teamName, setTeamName] = useState('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [customPlayersKey, setCustomPlayersKey] = useState(0);
    const [chartWidth, setChartWidth] = useState(400);
    const containerRef = useRef(null);
    const isMountedRef = useRef(true);
    const resizeRafRef = useRef(null);

    // Размер контейнера без ResponsiveContainer (избегаем ResizeObserver Recharts → конфликт с React 19)
    useLayoutEffect(() => {
        if (!containerRef.current) return;
        const el = containerRef.current;
        const ro = new ResizeObserver((entries) => {
            if (!entries[0] || !isMountedRef.current) return;
            const w = entries[0].contentRect.width;
            if (w <= 0) return;
            if (resizeRafRef.current != null) cancelAnimationFrame(resizeRafRef.current);
            resizeRafRef.current = requestAnimationFrame(() => {
                resizeRafRef.current = null;
                if (isMountedRef.current) setChartWidth(w);
            });
        });
        ro.observe(el);
        return () => {
            if (resizeRafRef.current != null) cancelAnimationFrame(resizeRafRef.current);
            ro.disconnect();
        };
    }, []);

    // Отслеживаем изменения в localStorage
    React.useEffect(() => {
        if (!teamId || simulationMode !== 'top_n') return;

        const storageKey = `customTeamPlayers_${teamId}`;
        
        const checkStorage = () => {
            if (isMountedRef.current) setCustomPlayersKey(prev => prev + 1);
        };

        checkStorage();

        window.addEventListener('storage', (e) => {
            if (e.key === storageKey) checkStorage();
        });
        window.addEventListener('customTeamPlayersUpdated', (e) => {
            if (e.detail?.teamId === teamId) checkStorage();
        });

        return () => {
            window.removeEventListener('storage', checkStorage);
            window.removeEventListener('customTeamPlayersUpdated', checkStorage);
        };
    }, [teamId, simulationMode]);

    React.useEffect(() => {
        if (!teamId) {
            setLoading(false);
            return;
        }

        isMountedRef.current = true;
        const ac = new AbortController();
        const signal = ac.signal;

        const safeSetState = (updater) => {
            if (!isMountedRef.current || signal.aborted) return;
            updater();
        };

        const fetchBalanceData = async () => {
            try {
                safeSetState(() => setLoading(true));

                const params = {
                    period,
                    punt_categories: '',
                    simulation_mode: simulationMode
                };
                if (simulationMode === 'top_n') {
                    params.top_n_players = 13;
                    const saved = localStorage.getItem(`customTeamPlayers_${teamId}`);
                    if (saved) {
                        try {
                            const customPlayers = JSON.parse(saved);
                            if (customPlayers.length > 0) params.custom_team_players = customPlayers.join(',');
                        } catch (e) {
                            console.error('Error parsing custom players:', e);
                        }
                    }
                }

                const response = await api.get(`/team-balance/${teamId}`, { params, signal });
                const result = response.data;

                if (signal.aborted) return;
                if (result.error) {
                    safeSetState(() => {
                        setError(result.error);
                        setData(null);
                        setLoading(false);
                    });
                    return;
                }

                safeSetState(() => {
                    setData(result.data);
                    setTeamName(result.team_name || 'Моя команда');
                    setError(null);
                });

                if (compareTeamId) {
                    const compareParams = {
                        period,
                        punt_categories: '',
                        simulation_mode: simulationMode
                    };
                    if (simulationMode === 'top_n') {
                        compareParams.top_n_players = 13;
                        const saved = localStorage.getItem(`customTeamPlayers_${compareTeamId}`);
                        if (saved) {
                            try {
                                const customPlayers = JSON.parse(saved);
                                if (customPlayers.length > 0) compareParams.custom_team_players = customPlayers.join(',');
                            } catch (e) {
                                console.error('Error parsing custom players for compare team:', e);
                            }
                        }
                    }

                    const compareResponse = await api.get(`/team-balance/${compareTeamId}`, {
                        params: compareParams,
                        signal
                    });
                    const compareResult = compareResponse.data;
                    if (!signal.aborted) {
                        safeSetState(() => {
                            setCompareData(compareResult.error ? null : compareResult.data);
                        });
                    }
                } else {
                    safeSetState(() => setCompareData(null));
                }
            } catch (err) {
                if (err.name === 'CanceledError' || signal.aborted) return;
                safeSetState(() => setError('Ошибка загрузки данных'));
                console.error('Error fetching balance data:', err);
            } finally {
                if (!signal.aborted) safeSetState(() => setLoading(false));
            }
        };

        fetchBalanceData();

        return () => {
            isMountedRef.current = false;
            ac.abort();
        };
    }, [teamId, period, simulationMode, compareTeamId, customPlayersKey]);

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
        <div ref={containerRef} className="w-full" style={{ minHeight: CHART_HEIGHT }}>
            <RadarChart width={chartWidth} height={CHART_HEIGHT} data={mergedData}>
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
        </div>
    );
};

export default TeamBalanceRadar;
