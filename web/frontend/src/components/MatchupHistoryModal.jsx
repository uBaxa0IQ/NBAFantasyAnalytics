import React, { useState, useEffect } from 'react';
import api from '../api';

const MatchupHistoryModal = ({ teamId, matchup, onClose }) => {
    const [matchupDetails, setMatchupDetails] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (!teamId || !matchup) return;

        setLoading(true);
        // Получаем детали матчапа для конкретной недели
        api.get(`/dashboard/${teamId}/matchup-details`, {
            params: { week: matchup.week }
        })
            .then(res => {
                setMatchupDetails(res.data);
                setLoading(false);
            })
            .catch(err => {
                console.error('Error fetching matchup details:', err);
                setLoading(false);
            });
    }, [teamId, matchup]);

    const formatValue = (category, value) => {
        if (category === 'FG%' || category === 'FT%' || category === '3PT%') {
            const formatted = value.toFixed(4);
            return formatted.startsWith('0.') ? formatted.substring(1) : formatted;
        } else if (category === 'A/TO') {
            return value.toFixed(3);
        } else {
            return Math.round(value).toString();
        }
    };

    if (!matchup) return null;

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={onClose}>
            <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto m-4" onClick={e => e.stopPropagation()}>
                <div className="p-6">
                    {/* Header */}
                    <div className="flex justify-between items-start mb-6">
                        <div>
                            <h2 className="text-2xl font-bold">Детали матчапа</h2>
                            <div className="mt-2 text-sm text-gray-600">
                                Неделя {matchup.week} • vs {matchup.opponent_name}
                            </div>
                            <div className="mt-1">
                                <span className={`px-3 py-1 rounded text-sm font-semibold ${
                                    matchup.result === 'W' ? 'bg-green-100 text-green-800' :
                                    matchup.result === 'L' ? 'bg-red-100 text-red-800' :
                                    'bg-gray-100 text-gray-800'
                                }`}>
                                    {matchup.result === 'W' ? 'Победа' : matchup.result === 'L' ? 'Поражение' : 'Ничья'} {matchup.score}
                                </span>
                            </div>
                        </div>
                        <button
                            onClick={onClose}
                            className="text-gray-500 hover:text-gray-700 text-2xl font-bold"
                        >
                            ×
                        </button>
                    </div>

                    {loading ? (
                        <div className="text-center text-gray-500 py-8">Загрузка деталей...</div>
                    ) : matchupDetails ? (
                        <div className="overflow-x-auto">
                            <table className="min-w-full">
                                <thead>
                                    <tr className="bg-gray-100 border-b">
                                        <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">Категория</th>
                                        <th className="px-4 py-3 text-center text-sm font-semibold text-gray-700">
                                            {matchupDetails.my_team.name}
                                        </th>
                                        <th className="px-4 py-3 text-center text-sm font-semibold text-gray-700">
                                            {matchupDetails.opponent.name}
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {matchupDetails.categories.map((item, idx) => {
                                        const myWins = item.winner === 'my_team';
                                        const opponentWins = item.winner === 'opponent';
                                        const isTie = item.winner === 'tie';

                                        return (
                                            <tr 
                                                key={item.category} 
                                                className={`border-b hover:bg-gray-50 ${
                                                    idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'
                                                }`}
                                            >
                                                <td className="px-4 py-3 text-sm font-medium text-gray-700">
                                                    {item.category}
                                                </td>
                                                <td className={`px-4 py-3 text-center text-sm font-semibold ${
                                                    myWins ? 'bg-green-100 text-green-800' : 
                                                    isTie ? 'bg-gray-100 text-gray-600' : 
                                                    'text-gray-700'
                                                }`}>
                                                    {formatValue(item.category, item.my_value)}
                                                </td>
                                                <td className={`px-4 py-3 text-center text-sm font-semibold ${
                                                    opponentWins ? 'bg-green-100 text-green-800' : 
                                                    isTie ? 'bg-gray-100 text-gray-600' : 
                                                    'text-gray-700'
                                                }`}>
                                                    {formatValue(item.category, item.opponent_value)}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    ) : (
                        <div className="text-center text-gray-500 py-8">
                            Детали матчапа недоступны
                        </div>
                    )}

                    {/* Close Button */}
                    <div className="mt-6 flex justify-end">
                        <button
                            onClick={onClose}
                            className="bg-blue-600 text-white px-6 py-2 rounded hover:bg-blue-700"
                        >
                            Закрыть
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default MatchupHistoryModal;

