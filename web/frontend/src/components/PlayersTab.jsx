import React, { useState, useEffect } from 'react';
import FreeAgents from './FreeAgents';
import AllPlayers from './AllPlayers';
import { saveState, loadState, StorageKeys } from '../utils/statePersistence';

const PlayersTab = ({ onPlayerClick, period, puntCategories, excludeIrForSimulations }) => {
    const [viewMode, setViewMode] = useState(() => {
        const saved = loadState(StorageKeys.PLAYERS, {});
        return saved.viewMode || 'free-agents';
    }); // 'free-agents' или 'all-players'

    // Сохранение состояния при изменении
    useEffect(() => {
        saveState(StorageKeys.PLAYERS, { viewMode });
    }, [viewMode]);

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
                    puntCategories={puntCategories}
                />
            ) : (
                <AllPlayers
                    onPlayerClick={onPlayerClick}
                    period={period}
                    puntCategories={puntCategories}
                    excludeIrForSimulations={excludeIrForSimulations}
                />
            )}
        </div>
    );
};

export default PlayersTab;

