import React, { useState } from 'react';
import FreeAgents from './FreeAgents';
import AllPlayers from './AllPlayers';

const PlayersTab = ({ onPlayerClick, period, setPeriod, puntCategories, setPuntCategories }) => {
    const [viewMode, setViewMode] = useState('free-agents'); // 'free-agents' или 'all-players'

    return (
        <div>
            {/* Переключатель в стиле TradeAnalyzer */}
            <div className="mb-4 flex justify-center">
                <div className="inline-flex rounded-lg border border-gray-300 bg-white p-1">
                    <button
                        onClick={() => setViewMode('free-agents')}
                        className={`px-4 py-2 rounded-md font-medium transition-colors ${
                            viewMode === 'free-agents'
                                ? 'bg-blue-600 text-white'
                                : 'text-gray-700 hover:bg-gray-100'
                        }`}
                    >
                        Свободные агенты
                    </button>
                    <button
                        onClick={() => setViewMode('all-players')}
                        className={`px-4 py-2 rounded-md font-medium transition-colors ${
                            viewMode === 'all-players'
                                ? 'bg-blue-600 text-white'
                                : 'text-gray-700 hover:bg-gray-100'
                        }`}
                    >
                        Все игроки
                    </button>
                </div>
            </div>

            {/* Рендеринг соответствующего компонента */}
            {viewMode === 'free-agents' ? (
                <FreeAgents
                    onPlayerClick={onPlayerClick}
                    period={period}
                    setPeriod={setPeriod}
                    puntCategories={puntCategories}
                    setPuntCategories={setPuntCategories}
                />
            ) : (
                <AllPlayers
                    onPlayerClick={onPlayerClick}
                    period={period}
                    setPeriod={setPeriod}
                    puntCategories={puntCategories}
                    setPuntCategories={setPuntCategories}
                />
            )}
        </div>
    );
};

export default PlayersTab;

