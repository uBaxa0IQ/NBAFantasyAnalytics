import React, { useState, useEffect } from 'react';
import api from '../api';
import MatchupHistoryModal from './MatchupHistoryModal';

const MatchupHistory = ({ teamId }) => {
    const [history, setHistory] = useState(null);
    const [loading, setLoading] = useState(false);
    const [selectedMatchup, setSelectedMatchup] = useState(null);
    const [showFullHistory, setShowFullHistory] = useState(false);

    useEffect(() => {
        if (!teamId) {
            setHistory(null);
            return;
        }

        setLoading(true);
        api.get(`/dashboard/${teamId}/matchup-history`)
            .then(res => {
                setHistory(res.data);
                setLoading(false);
            })
            .catch(err => {
                console.error('Error fetching matchup history:', err);
                setLoading(false);
            });
    }, [teamId]);

    if (loading) {
        return (
            <div className="bg-white border rounded-lg p-6 shadow-sm">
                <div className="text-center text-gray-500">Загрузка истории матчапов...</div>
            </div>
        );
    }

    if (!history || !history.matchups || history.matchups.length === 0) {
        return (
            <div className="bg-white border rounded-lg p-6 shadow-sm">
                <h3 className="text-lg font-semibold text-gray-700 mb-4">История матчапов</h3>
                <div className="text-gray-500 text-sm">Нет данных о матчапах</div>
            </div>
        );
    }

    // Подсчет статистики
    const wins = history.matchups.filter(m => m.result === 'W').length;
    const losses = history.matchups.filter(m => m.result === 'L').length;
    const ties = history.matchups.filter(m => m.result === 'T').length;
    const totalGames = wins + losses + ties;
    const winRate = totalGames > 0 ? ((wins + 0.5 * ties) / totalGames * 100).toFixed(1) : 0;

    const handleMatchupClick = (matchup) => {
        setSelectedMatchup(matchup);
    };

    return (
        <>
            {/* Statistics Card with Collapsible Table */}
            <div className="bg-white border rounded-lg p-6 shadow-sm">
                <div className="flex justify-between items-center mb-4">
                    <h3 className="text-lg font-semibold text-gray-700">История матчапов</h3>
                    <button
                        onClick={() => setShowFullHistory(!showFullHistory)}
                        className="text-gray-500 hover:text-gray-700 text-sm font-medium flex items-center gap-2"
                    >
                        {showFullHistory ? 'Скрыть' : 'Показать'} таблицу
                        <span className={`transform transition-transform ${showFullHistory ? 'rotate-180' : ''}`}>
                            ▼
                        </span>
                    </button>
                </div>
                <div className="grid grid-cols-3 gap-4">
                    <div className="text-center">
                        <div className="text-2xl font-bold text-green-600">{wins}</div>
                        <div className="text-sm text-gray-600">Побед</div>
                    </div>
                    <div className="text-center">
                        <div className="text-2xl font-bold text-red-600">{losses}</div>
                        <div className="text-sm text-gray-600">Поражений</div>
                    </div>
                    <div className="text-center">
                        <div className="text-2xl font-bold text-gray-600">{ties}</div>
                        <div className="text-sm text-gray-600">Ничьих</div>
                    </div>
                </div>

                {/* Collapsible Table */}
                {showFullHistory && (
                    <div className="mt-4 overflow-x-auto">
                        <table className="min-w-full bg-white border">
                            <thead>
                                <tr className="bg-gray-100">
                                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">Неделя</th>
                                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">Соперник</th>
                                    <th className="px-4 py-3 text-center text-sm font-semibold text-gray-700">Результат</th>
                                    <th className="px-4 py-3 text-center text-sm font-semibold text-gray-700">Счет</th>
                                </tr>
                            </thead>
                            <tbody>
                                {history.matchups.map((matchup, idx) => {
                                    const resultColor = 
                                        matchup.result === 'W' ? 'bg-green-100 text-green-800' :
                                        matchup.result === 'L' ? 'bg-red-100 text-red-800' :
                                        'bg-gray-100 text-gray-800';
                                    
                                    return (
                                        <tr 
                                            key={idx} 
                                            className="border-b hover:bg-gray-50 cursor-pointer transition-colors"
                                            onClick={() => {
                                                setSelectedMatchup(matchup);
                                            }}
                                        >
                                            <td className="px-4 py-3 text-sm font-medium text-gray-700">
                                                Неделя {matchup.week}
                                            </td>
                                            <td className="px-4 py-3 text-sm text-gray-700">
                                                {matchup.opponent_name}
                                            </td>
                                            <td className="px-4 py-3 text-center">
                                                <span className={`px-2 py-1 rounded text-xs font-semibold ${resultColor}`}>
                                                    {matchup.result === 'W' ? 'Победа' : matchup.result === 'L' ? 'Поражение' : 'Ничья'}
                                                </span>
                                            </td>
                                            <td className="px-4 py-3 text-center text-sm font-semibold text-blue-600">
                                                {matchup.score}
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {/* Matchup Details Modal */}
            {selectedMatchup && (
                <MatchupHistoryModal
                    teamId={teamId}
                    matchup={selectedMatchup}
                    onClose={() => setSelectedMatchup(null)}
                />
            )}
        </>
    );
};

export default MatchupHistory;
