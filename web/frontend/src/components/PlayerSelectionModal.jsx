import React, { useState, useEffect } from 'react';
import api from '../api';

const PlayerSelectionModal = ({ isOpen, onClose, teamId, period, onSave }) => {
    const [players, setPlayers] = useState([]);
    const [selectedPlayers, setSelectedPlayers] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
        if (!isOpen || !teamId) return;
        let cancelled = false;
        setLoading(true);
        setError(null);
        setPlayers([]);
        setSelectedPlayers([]);
        api.get(`/teams/${teamId}/players-for-selection`, { params: { period } })
            .then(res => {
                if (cancelled) return;
                const roster = res.data.players || [];
                const names = new Set(roster.map(player => player.name));
                let saved = [];
                try {
                    const parsed = JSON.parse(localStorage.getItem(`customTeamPlayers_${teamId}`) || '[]');
                    if (Array.isArray(parsed)) saved = parsed;
                } catch (err) {
                    console.error('Error parsing saved players:', err);
                }
                setPlayers(roster);
                setSelectedPlayers([...new Set(saved)].filter(name => names.has(name)).slice(0, 13));
            })
            .catch(err => {
                if (cancelled) return;
                console.error('Error loading players:', err);
                setError('Ошибка загрузки игроков');
            })
            .finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
    }, [isOpen, teamId, period]);

    const handleTogglePlayer = (playerName) => {
        setSelectedPlayers(prev => {
            if (prev.includes(playerName)) {
                return prev.filter(n => n !== playerName);
            } else {
                // Максимум 13 игроков
                if (prev.length >= 13) {
                    alert('Максимум 13 игроков');
                    return prev;
                }
                return [...prev, playerName];
            }
        });
    };

    const handleSelectTopN = () => {
        // Автоматически выбираем топ-13 игроков
        const top13 = players.slice(0, 13).map(p => p.name);
        setSelectedPlayers(top13);
    };

    const handleClear = () => {
        setSelectedPlayers([]);
    };

    const handleSave = () => {
        if (loading || error) return;
        // Сохраняем в localStorage
        if (teamId) {
            localStorage.setItem(`customTeamPlayers_${teamId}`, JSON.stringify(selectedPlayers));
            // Отправляем кастомное событие для обновления компонентов в той же вкладке
            window.dispatchEvent(new CustomEvent('customTeamPlayersUpdated', {
                detail: { teamId }
            }));
        }
        if (onSave) {
            onSave(selectedPlayers);
        }
        onClose();
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={onClose}>
            <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full mx-4 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
                <div className="p-6">
                    <div className="flex justify-between items-center mb-4">
                        <h2 className="text-2xl font-bold text-gray-800">
                            Выбор игроков для симуляции
                        </h2>
                        <button
                            onClick={onClose}
                            className="text-gray-500 hover:text-gray-700 text-2xl font-bold"
                        >
                            ×
                        </button>
                    </div>

                    <div className="mb-4 flex gap-2">
                        <button
                            onClick={handleSelectTopN}
                            disabled={loading || !!error}
                            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                        >
                            Выбрать топ-13 автоматически
                        </button>
                        <button
                            onClick={handleClear}
                            disabled={loading || !!error}
                            className="px-4 py-2 bg-gray-300 text-gray-700 rounded hover:bg-gray-400"
                        >
                            Очистить
                        </button>
                        <div className="ml-auto text-sm text-gray-600 flex items-center">
                            Выбрано: <span className="font-bold ml-1">{selectedPlayers.length}/13</span>
                        </div>
                    </div>

                    {loading && <div className="text-center p-4">Загрузка игроков...</div>}
                    {error && <div className="text-center p-4 text-red-500">{error}</div>}

                    {!loading && !error && (
                        <div className="overflow-x-auto">
                            <table className="min-w-full bg-white border">
                                <thead>
                                    <tr className="bg-gray-100">
                                        <th className="p-3 border text-left font-semibold">Выбрать</th>
                                        <th className="p-3 border text-left font-semibold">Игрок</th>
                                        <th className="p-3 border text-left font-semibold">Позиция</th>
                                        <th className="p-3 border text-center font-semibold">Total Z</th>
                                        <th className="p-3 border text-center font-semibold">IR</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {players.map((player, idx) => {
                                        const isSelected = selectedPlayers.includes(player.name);
                                        return (
                                            <tr
                                                key={idx}
                                                className={`hover:bg-gray-50 cursor-pointer ${isSelected ? 'bg-blue-50' : ''}`}
                                                onClick={() => handleTogglePlayer(player.name)}
                                            >
                                                <td className="p-3 border text-center">
                                                    <input
                                                        type="checkbox"
                                                        checked={isSelected}
                                                        onChange={() => handleTogglePlayer(player.name)}
                                                        onClick={(e) => e.stopPropagation()}
                                                    />
                                                </td>
                                                <td className="p-3 border font-medium">{player.name}</td>
                                                <td className="p-3 border">{player.position}</td>
                                                <td className="p-3 border text-center font-semibold">
                                                    {player.total_z.toFixed(2)}
                                                </td>
                                                <td className="p-3 border text-center">
                                                    {player.is_ir ? (
                                                        <span className="text-red-600 font-semibold">IR</span>
                                                    ) : (
                                                        <span className="text-gray-400">-</span>
                                                    )}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    )}

                    <div className="mt-6 flex justify-end gap-2">
                        <button
                            onClick={onClose}
                            className="px-4 py-2 bg-gray-300 text-gray-700 rounded hover:bg-gray-400"
                        >
                            Отмена
                        </button>
                        <button
                            onClick={handleSave}
                            disabled={loading || !!error}
                            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                        >
                            Сохранить
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default PlayerSelectionModal;
