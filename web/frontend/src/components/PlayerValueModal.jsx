import React, { useState, useEffect } from 'react';
import api from '../api';

const PlayerValueModal = ({ teamId, onClose, puntCategories = [], period = '2026_total', excludeIr = false }) => {
    const [loading, setLoading] = useState(true);
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);
    const [selectedPlayer, setSelectedPlayer] = useState(null);

    useEffect(() => {
        if (!teamId) return;

        setLoading(true);
        setError(null);

        const puntStr = puntCategories.join(',');
        
        api.get(`/lineup/${teamId}/optimize`, {
            params: {
                period: period,
                exclude_ir: excludeIr,
                punt_categories: puntStr
            }
        })
            .then(res => {
                setData(res.data);
                setLoading(false);
            })
            .catch(err => {
                console.error('Error fetching player values:', err);
                setError(err.response?.data?.error || 'Ошибка при загрузке данных');
                setLoading(false);
            });
    }, [teamId, puntCategories, period, excludeIr]);

    if (loading) {
        return (
            <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={onClose}>
                <div className="bg-white rounded-lg p-6 max-w-2xl w-full mx-4" onClick={e => e.stopPropagation()}>
                    <div className="text-center">Загрузка...</div>
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={onClose}>
                <div className="bg-white rounded-lg p-6 max-w-2xl w-full mx-4" onClick={e => e.stopPropagation()}>
                    <div className="flex justify-between items-center mb-4">
                        <h2 className="text-xl font-bold">Ошибка</h2>
                        <button onClick={onClose} className="text-gray-500 hover:text-gray-700 text-2xl">×</button>
                    </div>
                    <div className="text-red-600">{error}</div>
                    <div className="mt-4 flex justify-end">
                        <button
                            onClick={onClose}
                            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                        >
                            Закрыть
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    if (!data || !data.players) return null;

    const players = data.players || [];

    return (
        <>
            <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 overflow-y-auto" onClick={onClose}>
                <div className="bg-white rounded-lg p-6 max-w-4xl w-full mx-4 my-8" onClick={e => e.stopPropagation()}>
                    <div className="flex justify-between items-center mb-4">
                        <h2 className="text-xl font-bold">Ценность игроков команды</h2>
                        <button onClick={onClose} className="text-gray-500 hover:text-gray-700 text-2xl">×</button>
                    </div>

                    {data.matchup_info && (
                        <div className="mb-4 p-3 bg-blue-50 rounded">
                            <div className="text-sm text-gray-600">
                                <strong>Матчап:</strong> vs {data.matchup_info.opponent_name} (Неделя {data.matchup_info.week})
                            </div>
                            <div className="text-sm text-gray-600 mt-1">
                                <strong>Период:</strong> {period}
                            </div>
                        </div>
                    )}

                    <div className="mb-4 text-sm text-gray-600">
                        Всего игроков: {data.total_players || players.length}
                    </div>

                    {/* Список игроков */}
                    <div className="space-y-2 max-h-96 overflow-y-auto">
                        {players.map((player, idx) => (
                            <div 
                                key={idx} 
                                className="border rounded p-4 bg-gray-50 hover:bg-gray-100 transition-colors cursor-pointer"
                                onClick={() => setSelectedPlayer(player)}
                            >
                                <div className="flex justify-between items-start">
                                    <div className="flex-1">
                                        <div className="flex items-center gap-3 mb-2">
                                            <span className="text-lg font-bold text-gray-400 w-8">#{idx + 1}</span>
                                            <div>
                                                <div className="font-semibold text-lg">{player.name}</div>
                                                <div className="text-sm text-gray-600">
                                                    {player.position}
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div className="text-right">
                                        <div className="text-lg font-bold text-blue-600">
                                            Ценность: {player.value.toFixed(2)}
                                        </div>
                                        <div className="text-xs text-gray-500 mt-1">
                                            Z-score: {player.base_z.toFixed(2)} | 
                                            Бонус: {player.matchup_bonus > 0 ? '+' : ''}{player.matchup_bonus.toFixed(2)}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>

                    <div className="mt-6 flex justify-end">
                        <button
                            onClick={onClose}
                            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                        >
                            Закрыть
                        </button>
                    </div>
                </div>
            </div>

            {/* Модальное окно с детализацией */}
            {selectedPlayer && (
                <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-[60]" onClick={() => setSelectedPlayer(null)}>
                    <div className="bg-white rounded-lg p-6 max-w-2xl w-full mx-4" onClick={e => e.stopPropagation()}>
                        <div className="flex justify-between items-center mb-4">
                            <h3 className="text-xl font-bold">Детализация ценности: {selectedPlayer.name}</h3>
                            <button onClick={() => setSelectedPlayer(null)} className="text-gray-500 hover:text-gray-700 text-2xl">×</button>
                        </div>
                        
                        <div className="space-y-4">
                            <div className="border rounded p-4">
                                <div className="text-sm font-medium text-gray-600 mb-2">Общая ценность</div>
                                <div className="text-2xl font-bold text-blue-600">{selectedPlayer.value.toFixed(2)}</div>
                            </div>

                            <div className="border rounded p-4">
                                <div className="text-sm font-medium text-gray-600 mb-2">Базовый Z-score</div>
                                <div className="text-xl font-semibold">{selectedPlayer.base_z.toFixed(2)}</div>
                                <div className="text-xs text-gray-500 mt-1">Сумма Z-scores по всем категориям</div>
                            </div>

                            <div className="border rounded p-4">
                                <div className="text-sm font-medium text-gray-600 mb-2">Бонус за матчап</div>
                                <div className={`text-xl font-semibold ${selectedPlayer.matchup_bonus > 0 ? 'text-green-600' : selectedPlayer.matchup_bonus < 0 ? 'text-red-600' : 'text-gray-600'}`}>
                                    {selectedPlayer.matchup_bonus > 0 ? '+' : ''}{selectedPlayer.matchup_bonus.toFixed(2)}
                                </div>
                                <div className="text-xs text-gray-500 mt-1">
                                    {selectedPlayer.matchup_bonus > 0 
                                        ? 'Положительный бонус: игрок помогает в категориях, где мы отстаем'
                                        : selectedPlayer.matchup_bonus < 0
                                        ? 'Отрицательный бонус: игрок помогает в категориях, где мы сильно лидируем (>20%)'
                                        : 'Нейтральный: игрок не влияет на матчап или помогает в категориях, где мы выигрываем'}
                                </div>
                            </div>

                            {selectedPlayer.category_details && (
                                <div className="border rounded p-4">
                                    <div className="text-sm font-medium text-gray-600 mb-2">Детализация по категориям</div>
                                    <div className="space-y-2 max-h-64 overflow-y-auto">
                                        {Object.entries(selectedPlayer.category_details).map(([cat, info]) => (
                                            <div key={cat} className="flex justify-between items-center text-sm">
                                                <span className="font-medium">{cat}</span>
                                                <span className={info.bonus > 0 ? 'text-green-600' : info.bonus < 0 ? 'text-red-600' : 'text-gray-500'}>
                                                    {info.bonus > 0 ? '+' : ''}{info.bonus.toFixed(2)}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>

                        <div className="mt-6 flex justify-end">
                            <button
                                onClick={() => setSelectedPlayer(null)}
                                className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                            >
                                Закрыть
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
};

export default PlayerValueModal;

