import React, { useEffect, useState } from 'react';
import api from '../api';
import { getSeasonConfig } from '../utils/periods';

const LineupOptimizerModal = ({ teamId, onClose, puntCategories = [], period = getSeasonConfig().periods.total, calculationEngine = 'calendar' }) => {
    const [loading, setLoading] = useState(true);
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);

    useEffect(() => {
        if (!teamId) return;
        setLoading(true);
        setError(null);
        api.get(`/lineup/${teamId}/optimize`, {
            params: {
                period,
                remaining_only: true,
                punt_categories: puntCategories.join(','),
                calculation_engine: calculationEngine,
            },
        })
            .then(response => setData(response.data))
            .catch(requestError => {
                console.error('Error optimizing lineup:', requestError);
                setError(requestError.response?.data?.detail || 'Ошибка при оптимизации состава');
            })
            .finally(() => setLoading(false));
    }, [teamId, period, puntCategories, calculationEngine]);

    const shell = children => (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 overflow-y-auto" onClick={onClose}>
            <div className="bg-white rounded-lg p-6 max-w-6xl w-full mx-4 my-8" onClick={event => event.stopPropagation()}>
                {children}
            </div>
        </div>
    );

    if (loading) return shell(<div className="text-center">Считаю состав по календарю…</div>);
    if (error) return shell(<div className="text-red-600">{error}</div>);
    if (!data) return null;

    if (data.method === 'legacy_matchup_z_ranking') {
        return shell(
            <>
                <div className="flex justify-between items-start mb-4">
                    <div>
                        <h2 className="text-xl font-bold">Классическая оценка состава</h2>
                        <p className="text-sm text-gray-600">Z-score и бонус текущего матчапа, без календарной оптимизации.</p>
                    </div>
                    <button onClick={onClose} className="text-gray-500 text-2xl">×</button>
                </div>
                <div className="space-y-2 max-h-[65vh] overflow-y-auto">
                    {data.players.map((player, index) => (
                        <div key={player.name} className="border rounded p-3 flex justify-between gap-3">
                            <div><span className="text-gray-400 mr-2">#{index + 1}</span><span className="font-medium">{player.name}</span><div className="text-xs text-gray-500 ml-7">{player.position}</div></div>
                            <div className="text-right"><div className="font-bold text-blue-700">{player.value.toFixed(2)}</div><div className="text-xs text-gray-500">Z {player.base_z.toFixed(2)} · matchup {player.matchup_bonus.toFixed(2)}</div></div>
                        </div>
                    ))}
                </div>
            </>
        );
    }

    const selectedGames = Object.entries(data.selected_games || {})
        .filter(([, games]) => games > 0)
        .sort((a, b) => b[1] - a[1]);

    return shell(
        <>
            <div className="flex justify-between items-start gap-4 mb-4">
                <div>
                    <h2 className="text-xl font-bold">Оптимальный состав по дням</h2>
                    <div className="text-sm text-gray-600 mt-1">
                        {data.matchup_info ? `Матчап ${data.matchup_info.week}: vs ${data.matchup_info.opponent_name}` : `Период ${data.matchup_period}`}
                        {' · '}учтены календарь, позиции и травмы
                    </div>
                </div>
                <button onClick={onClose} className="text-gray-500 hover:text-gray-700 text-2xl">×</button>
            </div>

            {data.days.length === 0 ? (
                <div className="p-4 bg-amber-50 rounded text-amber-900">
                    В выбранном матчапе не осталось игровых дней.
                </div>
            ) : (
                <div className="space-y-4 max-h-[65vh] overflow-y-auto pr-1">
                    {data.days.map(day => (
                        <div key={day.scoring_period} className="border rounded-lg p-4">
                            <div className="font-semibold mb-3">Игровой день {day.scoring_period}</div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2">
                                {day.starters.map((starter, index) => (
                                    <div key={`${starter.slot}-${index}`} className="bg-blue-50 rounded p-2 min-w-0">
                                        <div className="text-xs font-bold text-blue-700">{starter.slot}</div>
                                        <div className="font-medium truncate" title={starter.name}>{starter.name}</div>
                                        <div className="text-xs text-gray-500">{starter.position} · Z {starter.value.toFixed(2)}</div>
                                    </div>
                                ))}
                            </div>
                            {day.bench.length > 0 && (
                                <div className="text-xs text-gray-500 mt-3">
                                    Играют, но не помещаются в слоты: {day.bench.join(', ')}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}

            <div className="mt-4 p-3 bg-gray-50 rounded">
                <div className="text-sm font-semibold mb-1">Использование игроков</div>
                <div className="text-sm text-gray-600">
                    {selectedGames.map(([name, games]) => `${name}: ${games}`).join(' · ') || 'Нет доступных игр'}
                </div>
            </div>
        </>
    );
};

export default LineupOptimizerModal;
