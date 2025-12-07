import React, { useState, useEffect } from 'react';
import api from '../api';
import PlayerSelectionModal from './PlayerSelectionModal';
import PromptModal from './PromptModal';

const CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'FG%', 'FT%', '3PT%', 'A/TO'];

const SettingsModal = ({ isOpen, onClose, onSave, initialSettings }) => {
    const [period, setPeriod] = useState(initialSettings.period || '2026_total');
    const [puntCategories, setPuntCategories] = useState(initialSettings.puntCategories || []);
    const [simulationMode, setSimulationMode] = useState(initialSettings.simulationMode || 'all');
    const [mainTeam, setMainTeam] = useState(initialSettings.mainTeam || '');
    const [teams, setTeams] = useState([]);
    const [refreshStatus, setRefreshStatus] = useState(null);
    const [showPlayerSelection, setShowPlayerSelection] = useState(false);
    const [selectedPlayersCount, setSelectedPlayersCount] = useState(0);
    const [showPromptModal, setShowPromptModal] = useState(false);

    // Форматирование времени последнего обновления
    const formatLastRefresh = (isoString) => {
        if (!isoString) return 'Еще не обновлялось';
        
        try {
            // Парсим ISO строку (может быть с или без timezone)
            const date = new Date(isoString);
            
            // Проверяем валидность даты
            if (isNaN(date.getTime())) {
                return 'Неверный формат времени';
            }
            
            const now = new Date();
            const diffMs = now - date;
            
            // Если разница отрицательная (будущее время), значит проблема с часовым поясом
            if (diffMs < 0) {
                // Пробуем интерпретировать как UTC и пересчитать
                const utcDate = new Date(isoString + (isoString.includes('Z') ? '' : 'Z'));
                const diffMsFixed = now - utcDate;
                if (diffMsFixed >= 0) {
                    const diffMins = Math.floor(diffMsFixed / 60000);
                    const diffSecs = Math.floor((diffMsFixed % 60000) / 1000);
                    
                    if (diffMins < 1) {
                        return `Только что (${diffSecs} сек назад)`;
                    } else if (diffMins < 60) {
                        return `${diffMins} мин назад`;
                    } else {
                        const hours = Math.floor(diffMins / 60);
                        return `${hours} ч ${diffMins % 60} мин назад`;
                    }
                }
            }
            
            const diffMins = Math.floor(diffMs / 60000);
            const diffSecs = Math.floor((diffMs % 60000) / 1000);

            if (diffMins < 1) {
                return `Только что (${diffSecs} сек назад)`;
            } else if (diffMins < 60) {
                return `${diffMins} мин назад`;
            } else {
                const hours = Math.floor(diffMins / 60);
                return `${hours} ч ${diffMins % 60} мин назад`;
            }
        } catch (error) {
            console.error('Error formatting refresh time:', error);
            return 'Ошибка форматирования времени';
        }
    };

    useEffect(() => {
        if (isOpen) {
            // Загружаем список команд при открытии модального окна
            api.get('/teams')
                .then(res => {
                    setTeams(res.data);
                    // Если mainTeam не установлен, устанавливаем первую команду
                    if (!mainTeam && res.data.length > 0) {
                        setMainTeam(res.data[0].team_id.toString());
                    }
                })
                .catch(err => console.error('Error fetching teams:', err));

            // Загружаем статус обновления
            api.get('/refresh-status')
                .then(res => {
                    setRefreshStatus(res.data);
                })
                .catch(err => {
                    console.error('Error fetching refresh status:', err);
                });
        }
    }, [isOpen]);

    useEffect(() => {
        // Обновляем локальные состояния при изменении initialSettings
        if (initialSettings) {
            setPeriod(initialSettings.period || '2026_total');
            setPuntCategories(initialSettings.puntCategories || []);
            setSimulationMode(initialSettings.simulationMode || 'all');
            setMainTeam(initialSettings.mainTeam || '');
        }
    }, [initialSettings]);

    useEffect(() => {
        // Загружаем количество выбранных игроков из localStorage
        if (mainTeam) {
            const saved = localStorage.getItem(`customTeamPlayers_${mainTeam}`);
            if (saved) {
                try {
                    const savedList = JSON.parse(saved);
                    setSelectedPlayersCount(savedList.length);
                } catch (e) {
                    setSelectedPlayersCount(0);
                }
            } else {
                setSelectedPlayersCount(0);
            }
        }
    }, [mainTeam]);

    const handlePuntChange = (cat) => {
        setPuntCategories(prev =>
            prev.includes(cat) ? prev.filter(c => c !== cat) : [...prev, cat]
        );
    };

    const handleSave = () => {
        const settings = {
            period,
            puntCategories,
            simulationMode,
            mainTeam
        };
        onSave(settings);
        onClose();
    };

    const handlePlayerSelectionSave = (selectedPlayers) => {
        setSelectedPlayersCount(selectedPlayers.length);
    };

    const handleGeneratePrompt = () => {
        setShowPromptModal(true);
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={onClose}>
            <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
                <div className="p-6">
                    <div className="flex justify-between items-center mb-6">
                        <h2 className="text-2xl font-bold text-gray-800">Настройки</h2>
                        <button
                            onClick={onClose}
                            className="text-gray-500 hover:text-gray-700 text-2xl font-bold"
                        >
                            ×
                        </button>
                    </div>

                    <div className="space-y-6">
                        {/* Период */}
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-2">
                                Период статистики:
                            </label>
                            <select
                                className="w-full border p-2 rounded"
                                value={period}
                                onChange={e => setPeriod(e.target.value)}
                            >
                                <option value="2026_total">Весь сезон</option>
                                <option value="2026_last_30">Последние 30 дней</option>
                                <option value="2026_last_15">Последние 15 дней</option>
                                <option value="2026_last_7">Последние 7 дней</option>
                                <option value="2026_projected">Прогноз</option>
                            </select>
                        </div>

                        {/* Punt Categories */}
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-2">
                                Punt Categories:
                            </label>
                            <div className="flex gap-2 flex-wrap">
                                {CATEGORIES.map(cat => (
                                    <label
                                        key={cat}
                                        className="flex items-center gap-1 cursor-pointer bg-gray-100 px-3 py-2 rounded hover:bg-gray-200"
                                    >
                                        <input
                                            type="checkbox"
                                            checked={puntCategories.includes(cat)}
                                            onChange={() => handlePuntChange(cat)}
                                        />
                                        <span className="text-sm">{cat}</span>
                                    </label>
                                ))}
                            </div>
                        </div>

                        {/* Режим симуляций */}
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-2">
                                Режим симуляций:
                            </label>
                            <div className="space-y-2">
                                <label className="flex items-center gap-2 cursor-pointer bg-gray-100 px-3 py-2 rounded hover:bg-gray-200">
                                    <input
                                        type="radio"
                                        name="simulationMode"
                                        value="all"
                                        checked={simulationMode === 'all'}
                                        onChange={e => setSimulationMode(e.target.value)}
                                    />
                                    <span className="font-medium">Все игроки</span>
                                </label>
                                <label className="flex items-center gap-2 cursor-pointer bg-gray-100 px-3 py-2 rounded hover:bg-gray-200">
                                    <input
                                        type="radio"
                                        name="simulationMode"
                                        value="exclude_ir"
                                        checked={simulationMode === 'exclude_ir'}
                                        onChange={e => setSimulationMode(e.target.value)}
                                    />
                                    <span className="font-medium">Убрать IR игроков</span>
                                </label>
                                <label className="flex items-center gap-2 cursor-pointer bg-gray-100 px-3 py-2 rounded hover:bg-gray-200">
                                    <input
                                        type="radio"
                                        name="simulationMode"
                                        value="top_n"
                                        checked={simulationMode === 'top_n'}
                                        onChange={e => setSimulationMode(e.target.value)}
                                    />
                                    <span className="font-medium">Топ-13 игроков команды</span>
                                </label>
                            </div>
                        </div>

                        {/* Основная команда */}
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-2">
                                Основная команда (для Dashboard):
                            </label>
                            <select
                                className="w-full border p-2 rounded"
                                value={mainTeam}
                                onChange={e => setMainTeam(e.target.value)}
                            >
                                <option value="">Выберите команду</option>
                                {teams.map(team => (
                                    <option key={team.team_id} value={team.team_id}>
                                        {team.team_name}
                                    </option>
                                ))}
                            </select>
                        </div>

                        {/* Настройка игроков для режима top_n */}
                        {simulationMode === 'top_n' && mainTeam && (
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Настройка игроков для симуляции:
                                </label>
                                <div className="flex items-center gap-2">
                                    <button
                                        onClick={() => setShowPlayerSelection(true)}
                                        className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                                    >
                                        Настроить игроков
                                    </button>
                                    {selectedPlayersCount > 0 && (
                                        <span className="text-sm text-gray-600">
                                            Выбрано игроков: <span className="font-bold">{selectedPlayersCount}/13</span>
                                        </span>
                                    )}
                                </div>
                                <p className="text-xs text-gray-500 mt-1">
                                    Выберите игроков для своей команды. Если не выбрано, будут использоваться топ-13 по Z-score.
                                </p>
                            </div>
                        )}

                        {/* Генерация промпта для LLM */}
                        <div className="border-t pt-4">
                            <h3 className="text-sm font-semibold text-gray-700 mb-3">
                                Промпт для LLM
                            </h3>
                            <div className="bg-gray-50 border rounded px-3 py-3 text-sm">
                                <p className="text-gray-600 mb-3">
                                    Сгенерируйте промпт с полным контекстом лиги для использования в LLM (ChatGPT, Claude и т.д.)
                                </p>
                                <button
                                    onClick={handleGeneratePrompt}
                                    className="px-4 py-2 bg-purple-600 text-white rounded hover:bg-purple-700"
                                >
                                    Получить промпт
                                </button>
                            </div>
                        </div>

                        {/* Информация о последнем обновлении */}
                        <div className="border-t pt-4">
                            <h3 className="text-sm font-semibold text-gray-700 mb-3">
                                Информация об обновлении данных
                            </h3>
                            {refreshStatus ? (
                                <div className="bg-gray-50 border rounded px-3 py-2 text-sm">
                                    <div className="flex items-center gap-2 mb-2">
                                        <span className="text-gray-600">Последнее обновление:</span>
                                        <span className="font-medium text-gray-800">
                                            {refreshStatus.last_refresh_time 
                                                ? formatLastRefresh(refreshStatus.last_refresh_time)
                                                : 'Ожидание первого обновления...'}
                                        </span>
                                    </div>
                                    {refreshStatus.auto_refresh_enabled && (
                                        <div className="text-xs text-gray-500">
                                            Автообновление каждые {refreshStatus.refresh_interval_minutes} мин
                                        </div>
                                    )}
                                </div>
                            ) : (
                                <div className="text-sm text-gray-500">Загрузка информации...</div>
                            )}
                        </div>
                    </div>

                    {/* Кнопки */}
                    <div className="flex justify-end gap-4 mt-6">
                        <button
                            onClick={onClose}
                            className="px-4 py-2 border border-gray-300 rounded hover:bg-gray-100"
                        >
                            Отмена
                        </button>
                        <button
                            onClick={handleSave}
                            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                        >
                            Сохранить
                        </button>
                    </div>
                </div>
            </div>

            {/* Модальное окно выбора игроков */}
            {showPlayerSelection && mainTeam && (
                <PlayerSelectionModal
                    isOpen={showPlayerSelection}
                    onClose={() => setShowPlayerSelection(false)}
                    teamId={mainTeam}
                    period={period}
                    onSave={handlePlayerSelectionSave}
                />
            )}

            {/* Модальное окно промпта */}
            {showPromptModal && (
                <PromptModal
                    isOpen={showPromptModal}
                    onClose={() => setShowPromptModal(false)}
                    period={period}
                    simulationMode={simulationMode}
                    topNPlayers={13}
                    mainTeamId={mainTeam}
                    puntCategories={puntCategories}
                />
            )}
        </div>
    );
};

export default SettingsModal;

