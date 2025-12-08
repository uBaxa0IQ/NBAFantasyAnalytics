import React from 'react';

const SeasonProjectionModal = ({ projection, onClose }) => {
    if (!projection || !projection.full_standings) return null;

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-[60]" onClick={onClose}>
            <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto m-4" onClick={e => e.stopPropagation()}>
                <div className="p-6">
                    {/* Header */}
                    <div className="flex justify-between items-start mb-6">
                        <div>
                            <h2 className="text-2xl font-bold text-gray-700">Прогноз итоговых мест</h2>
                            <div className="mt-2 text-sm text-gray-600">
                                Прогнозируемая таблица лиги на конец сезона
                            </div>
                        </div>
                        <button
                            onClick={onClose}
                            className="text-gray-500 hover:text-gray-700 text-2xl font-bold"
                        >
                            ×
                        </button>
                    </div>

                    {/* Table */}
                    <div className="overflow-x-auto">
                        <table className="min-w-full bg-white border">
                            <thead>
                                <tr className="bg-gray-100">
                                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">Место</th>
                                    <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">Команда</th>
                                    <th className="px-4 py-3 text-center text-sm font-semibold text-gray-700">Победы</th>
                                    <th className="px-4 py-3 text-center text-sm font-semibold text-gray-700">Поражения</th>
                                    <th className="px-4 py-3 text-center text-sm font-semibold text-gray-700">Ничьи</th>
                                    <th className="px-4 py-3 text-center text-sm font-semibold text-gray-700">Винрейт</th>
                                </tr>
                            </thead>
                            <tbody>
                                {projection.full_standings.map((team, idx) => {
                                    const isCurrentTeam = team.team_id === projection.team_id;
                                    return (
                                        <tr 
                                            key={team.team_id} 
                                            className={`border-b hover:bg-gray-50 transition-colors ${
                                                isCurrentTeam ? 'bg-blue-50' : ''
                                            }`}
                                        >
                                            <td className="px-4 py-3 text-sm font-semibold text-gray-700">
                                                {team.position}
                                            </td>
                                            <td className="px-4 py-3 text-sm font-medium text-gray-700">
                                                {team.team_name}
                                                {isCurrentTeam && (
                                                    <span className="ml-2 text-xs text-blue-600 font-semibold">(ваша команда)</span>
                                                )}
                                            </td>
                                            <td className="px-4 py-3 text-center text-sm text-gray-700">
                                                {team.wins}
                                            </td>
                                            <td className="px-4 py-3 text-center text-sm text-gray-700">
                                                {team.losses}
                                            </td>
                                            <td className="px-4 py-3 text-center text-sm text-gray-700">
                                                {team.ties}
                                            </td>
                                            <td className="px-4 py-3 text-center">
                                                <span className="text-sm font-semibold text-blue-600">
                                                    {team.win_rate}%
                                                </span>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>

                    {/* Close Button */}
                    <div className="mt-6 flex justify-end">
                        <button
                            onClick={onClose}
                            className="bg-blue-600 text-white px-6 py-2 rounded hover:bg-blue-700 transition-colors"
                        >
                            Закрыть
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default SeasonProjectionModal;

