import React from 'react';

const SimulationDetailsModal = ({ team, onClose }) => {
    if (!team) return null;

    const getResultBadge = (result) => {
        if (result === 'win') {
            return <span className="px-2 py-1 text-xs font-semibold rounded bg-green-100 text-green-800">П</span>;
        } else if (result === 'loss') {
            return <span className="px-2 py-1 text-xs font-semibold rounded bg-red-100 text-red-800">Пор</span>;
        } else {
            return <span className="px-2 py-1 text-xs font-semibold rounded bg-gray-100 text-gray-800">Н</span>;
        }
    };

    const getCategoryBadge = (result) => {
        if (result === 'win') {
            return 'text-green-600';
        } else if (result === 'loss') {
            return 'text-red-600';
        } else {
            return 'text-gray-500';
        }
    };

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-lg max-w-4xl w-full max-h-[90vh] overflow-hidden">
                {/* Header */}
                <div className="bg-blue-900 text-white p-4 flex justify-between items-center">
                    <h2 className="text-xl font-bold">{team.name} - Детали симуляции</h2>
                    <button
                        onClick={onClose}
                        className="text-white hover:text-gray-200 text-2xl font-bold"
                    >
                        ×
                    </button>
                </div>

                {/* Summary */}
                <div className="p-4 bg-gray-50 border-b">
                    <div className="flex gap-6 justify-center">
                        <div className="text-center">
                            <div className="text-2xl font-bold text-green-600">{team.wins}</div>
                            <div className="text-sm text-gray-600">Победы</div>
                        </div>
                        <div className="text-center">
                            <div className="text-2xl font-bold text-red-600">{team.losses}</div>
                            <div className="text-sm text-gray-600">Поражения</div>
                        </div>
                        <div className="text-center">
                            <div className="text-2xl font-bold text-gray-600">{team.ties}</div>
                            <div className="text-sm text-gray-600">Ничьи</div>
                        </div>
                        <div className="text-center">
                            <div className="text-2xl font-bold text-blue-600">{team.win_rate}%</div>
                            <div className="text-sm text-gray-600">Винрейт</div>
                        </div>
                    </div>
                </div>

                {/* Matchups List */}
                <div className="overflow-y-auto max-h-[calc(90vh-200px)] p-4">
                    <div className="space-y-4">
                        {team.matchups && team.matchups.map((matchup, index) => (
                            <div key={index} className="border rounded-lg p-4 hover:bg-gray-50">
                                <div className="flex items-center justify-between mb-3">
                                    <div className="flex items-center gap-3">
                                        {getResultBadge(matchup.result)}
                                        <span className="font-semibold">vs {matchup.opponent_name}</span>
                                    </div>
                                    <div className="text-lg font-bold text-blue-600">
                                        {matchup.score}
                                    </div>
                                </div>

                                {/* Category Breakdown */}
                                <div className="grid grid-cols-4 md:grid-cols-6 lg:grid-cols-11 gap-2">
                                    {matchup.categories && Object.entries(matchup.categories).map(([category, result]) => (
                                        <div key={category} className="text-center">
                                            <div className={`text-xs font-semibold ${getCategoryBadge(result)}`}>
                                                {category}
                                            </div>
                                            <div className="text-xs text-gray-500">
                                                {result === 'win' ? '✓' : result === 'loss' ? '✗' : '−'}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        ))}
                    </div>

                    {(!team.matchups || team.matchups.length === 0) && (
                        <div className="text-center text-gray-500 py-8">
                            Нет данных о матчапах
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default SimulationDetailsModal;
