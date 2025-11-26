import React from 'react';

const PlayerModal = ({ player, onClose }) => {
    if (!player) return null;

    const zScores = player.z_scores || {};

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={onClose}>
            <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full max-h-[90vh] overflow-y-auto m-4" onClick={e => e.stopPropagation()}>
                <div className="p-6">
                    {/* Header */}
                    <div className="flex justify-between items-start mb-6">
                        <div>
                            <h2 className="text-2xl font-bold">{player.name}</h2>
                            <div className="flex gap-4 mt-2 text-sm text-gray-600">
                                <span>Позиция: <strong>{player.position}</strong></span>
                                <span>NBA Team: <strong>{player.nba_team}</strong></span>
                                {player.fantasy_team && (
                                    <span>Fantasy Team: <strong>{player.fantasy_team}</strong></span>
                                )}
                            </div>
                        </div>
                        <button
                            onClick={onClose}
                            className="text-gray-500 hover:text-gray-700 text-2xl font-bold"
                        >
                            ×
                        </button>
                    </div>

                    {/* Z-Scores */}
                    <div>
                        <h3 className="text-lg font-semibold mb-3">Z-Scores</h3>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            {Object.entries(zScores).map(([cat, val]) => {
                                let colorClass = val > 0 ? 'text-green-600' : 'text-red-600';
                                if (val === 0) colorClass = 'text-gray-400';

                                return (
                                    <div key={cat} className="bg-gray-50 p-3 rounded">
                                        <div className="text-sm text-gray-600">{cat}</div>
                                        <div className={`text-xl font-bold ${colorClass}`}>
                                            {typeof val === 'number' ? val.toFixed(2) : val}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>

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

export default PlayerModal;
