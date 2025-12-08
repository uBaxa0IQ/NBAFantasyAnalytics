import React, { useState, useEffect } from 'react';
import api from '../api';

const CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'FG%', 'FT%', '3PT%', 'A/TO'];

const SettingsModal = ({ isOpen, onClose, onSave, initialSettings }) => {
    const [period, setPeriod] = useState(initialSettings.period || '2026_total');
    const [puntCategories, setPuntCategories] = useState(initialSettings.puntCategories || []);
    const [excludeIrForSimulations, setExcludeIrForSimulations] = useState(initialSettings.excludeIrForSimulations || false);
    const [mainTeam, setMainTeam] = useState(initialSettings.mainTeam || '');
    const [teams, setTeams] = useState([]);
    const [refreshStatus, setRefreshStatus] = useState(null);
    const [promptLoading, setPromptLoading] = useState(false);
    const [promptError, setPromptError] = useState(null);
    const [promptText, setPromptText] = useState(null);

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
            setExcludeIrForSimulations(initialSettings.excludeIrForSimulations || false);
            setMainTeam(initialSettings.mainTeam || '');
        }
    }, [initialSettings]);

    const handlePuntChange = (cat) => {
        setPuntCategories(prev =>
            prev.includes(cat) ? prev.filter(c => c !== cat) : [...prev, cat]
        );
    };

    const handleSave = () => {
        const settings = {
            period,
            puntCategories,
            excludeIrForSimulations,
            mainTeam
        };
        onSave(settings);
        onClose();
    };

    const handleGetPrompt = () => {
        setPromptLoading(true);
        setPromptError(null);
        setPromptText(null);

        api.get('/generate-prompt', {
            params: {
                period: period,
                exclude_ir: excludeIrForSimulations
            }
        })
            .then(res => {
                if (res.data.error) {
                    setPromptError(res.data.error);
                } else {
                    setPromptText(res.data.prompt);
                }
                setPromptLoading(false);
            })
            .catch(err => {
                console.error('Error fetching prompt:', err);
                
                let errorMessage = 'Ошибка при получении промпта';
                
                if (err.response) {
                    // Сервер ответил с кодом ошибки
                    const status = err.response.status;
                    const serverError = err.response.data?.error || err.response.data?.detail;
                    
                    if (serverError) {
                        errorMessage = serverError;
                    } else if (status === 500) {
                        errorMessage = 'Ошибка сервера при генерации промпта';
                    } else if (status === 504) {
                        errorMessage = 'Превышено время ожидания ответа сервера. Генерация промпта занимает слишком много времени. Попробуйте позже';
                    } else {
                        errorMessage = `Ошибка сервера (код ${status})`;
                    }
                } else if (err.request) {
                    // Запрос отправлен, но ответа нет (таймаут или сеть)
                    if (err.code === 'ECONNABORTED' || err.message?.includes('timeout')) {
                        errorMessage = 'Превышено время ожидания ответа. Генерация промпта занимает слишком много времени. Попробуйте позже';
                    } else {
                        errorMessage = 'Нет связи с сервером. Проверьте подключение к интернету';
                    }
                } else {
                    // Ошибка при настройке запроса
                    errorMessage = `Ошибка запроса: ${err.message || 'Неизвестная ошибка'}`;
                }
                
                setPromptError(errorMessage);
                setPromptLoading(false);
            });
    };

    const handleCopyPrompt = () => {
        if (promptText) {
            navigator.clipboard.writeText(promptText)
                .then(() => {
                    alert('Промпт скопирован в буфер обмена');
                })
                .catch(err => {
                    console.error('Error copying to clipboard:', err);
                    alert('Ошибка при копировании промпта');
                });
        }
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

                        {/* Исключить IR игроков из симуляций */}
                        <div>
                            <label className="flex items-center gap-2 cursor-pointer bg-gray-100 px-3 py-2 rounded hover:bg-gray-200">
                                <input
                                    type="checkbox"
                                    checked={excludeIrForSimulations}
                                    onChange={e => setExcludeIrForSimulations(e.target.checked)}
                                />
                                <span className="font-medium">Исключить IR игроков из симуляций</span>
                            </label>
                            <p className="text-xs text-gray-500 mt-1">
                                Примечание: В аналитике команды IR игроки всегда включены
                            </p>
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

                        {/* Промпт для LLM */}
                        <div className="border-t pt-4">
                            <h3 className="text-sm font-semibold text-gray-700 mb-3">
                                Промпт для LLM
                            </h3>
                            <div className="bg-white border rounded px-3 py-2 text-sm">
                                <p className="text-gray-600 mb-3">
                                    Сгенерируйте промпт с полным контекстом лиги для использования в LLM (ChatGPT, Claude и т.д.)
                                </p>
                                
                                {promptError && (
                                    <div className="mb-3 p-2 bg-red-50 border border-red-200 rounded text-red-700 text-xs">
                                        {promptError}
                                    </div>
                                )}
                                
                                {promptText && (
                                    <div className="mb-3">
                                        <div className="flex justify-end mb-2">
                                            <button
                                                onClick={handleCopyPrompt}
                                                className="px-3 py-1 text-xs bg-gray-200 text-gray-700 rounded hover:bg-gray-300"
                                            >
                                                Копировать
                                            </button>
                                        </div>
                                        <textarea
                                            readOnly
                                            value={promptText}
                                            className="w-full h-64 p-2 border rounded text-xs font-mono overflow-auto"
                                            style={{ resize: 'vertical' }}
                                        />
                                    </div>
                                )}
                                
                                <button
                                    onClick={handleGetPrompt}
                                    disabled={promptLoading}
                                    className="w-full px-4 py-2 bg-purple-600 text-white rounded hover:bg-purple-700 disabled:bg-gray-400 disabled:cursor-not-allowed font-medium"
                                >
                                    {promptLoading ? 'Генерация промпта...' : 'Получить промпт'}
                                </button>
                            </div>
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
        </div>
    );
};

export default SettingsModal;

