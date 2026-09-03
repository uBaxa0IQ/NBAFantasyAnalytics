import React, { useState, useEffect } from 'react';
import api from '../api';
import PlayerSelectionModal from './PlayerSelectionModal';
import { getSeasonConfig, normalizeSavedPeriod } from '../utils/periods';
import { LEAGUE_CATEGORIES as CATEGORIES } from '../utils/categories';
const DEFAULT_WEIGHTED_COEFFICIENTS = {
    total: 0.45,
    last_30: 0.35,
    last_15: 0.15,
    last_7: 0.05
};

const SettingsModal = ({ isOpen, onClose, onSave, initialSettings, seasonConfig }) => {
    const periods = seasonConfig?.periods || getSeasonConfig().periods;
    const [period, setPeriod] = useState(normalizeSavedPeriod(initialSettings.period, periods));
    const [puntCategories, setPuntCategories] = useState(initialSettings.puntCategories || []);
    const [simulationMode, setSimulationMode] = useState(initialSettings.simulationMode || 'top_n');
    const [calculationEngine, setCalculationEngine] = useState(initialSettings.calculationEngine || 'calendar');
    const [mainTeam, setMainTeam] = useState(initialSettings.mainTeam || '');
    const [colorByTrend, setColorByTrend] = useState(initialSettings.colorByTrend !== undefined ? initialSettings.colorByTrend : false);
    const [teams, setTeams] = useState([]);
    const [refreshStatus, setRefreshStatus] = useState(null);
    const [showPlayerSelection, setShowPlayerSelection] = useState(false);
    const [selectedPlayersCount, setSelectedPlayersCount] = useState(0);
    const [weightedCoefficients, setWeightedCoefficients] = useState(DEFAULT_WEIGHTED_COEFFICIENTS);
    const [settingsError, setSettingsError] = useState('');
    const [saving, setSaving] = useState(false);
    const [readiness, setReadiness] = useState(null);
    const [leagueId, setLeagueId] = useState(String(seasonConfig?.league_id || ''));

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
                    setMainTeam(current => current || res.data[0]?.team_id?.toString() || '');
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

            api.get('/settings/weighted-coefficients')
                .then(res => setWeightedCoefficients(res.data))
                .catch(err => {
                    console.error('Error fetching weighted coefficients:', err);
                    setSettingsError('Не удалось загрузить коэффициенты универсального режима');
                });

            api.get('/settings/readiness')
                .then(res => setReadiness(res.data))
                .catch(() => setReadiness(null));
        }
    }, [isOpen]);

    useEffect(() => {
        // Обновляем локальные состояния при изменении initialSettings
        if (initialSettings) {
            setPeriod(normalizeSavedPeriod(initialSettings.period, periods));
            setPuntCategories(initialSettings.puntCategories || []);
            setMainTeam(initialSettings.mainTeam || '');
            setSimulationMode(initialSettings.simulationMode || 'top_n');
            setCalculationEngine(initialSettings.calculationEngine || 'calendar');
            if (initialSettings.colorByTrend !== undefined) {
                setColorByTrend(initialSettings.colorByTrend);
            }
        }
    }, [initialSettings, periods]);

    useEffect(() => {
        setLeagueId(String(seasonConfig?.league_id || ''));
    }, [seasonConfig?.league_id]);

    useEffect(() => {
        // Загружаем количество выбранных игроков из localStorage
        if (mainTeam) {
            const saved = localStorage.getItem(`customTeamPlayers_${mainTeam}`);
            if (saved) {
                try {
                    const savedList = JSON.parse(saved);
                    setSelectedPlayersCount(savedList.length);
                } catch {
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

    const handleCoefficientChange = (key, percentValue) => {
        const numericValue = Number(percentValue);
        setWeightedCoefficients(prev => ({
            ...prev,
            [key]: Number.isFinite(numericValue) ? numericValue / 100 : 0
        }));
        setSettingsError('');
    };

    const coefficientSum = Object.values(weightedCoefficients).reduce((sum, value) => sum + value, 0);
    const coefficientsAreValid = Object.values(weightedCoefficients).every(value => value >= 0 && value <= 1)
        && Math.abs(coefficientSum - 1) <= 0.001;

    const handleSave = async () => {
        setSettingsError('');
        setSaving(true);

        if (period === periods.weighted && !coefficientsAreValid) {
            setSettingsError('Сумма коэффициентов универсального режима должна быть равна 100%');
            setSaving(false);
            return;
        }

        if (period === periods.weighted) {
            try {
                await api.put('/settings/weighted-coefficients', weightedCoefficients);
            } catch (error) {
                setSettingsError(error.response?.data?.detail || 'Не удалось сохранить коэффициенты');
                setSaving(false);
                return;
            }
        }

        const normalizedLeagueId = leagueId.trim();
        if (!/^\d+$/.test(normalizedLeagueId) || Number(normalizedLeagueId) <= 0) {
            setSettingsError('League ID должен быть положительным числом');
            setSaving(false);
            return;
        }

        let leagueChanged = false;
        let effectiveMainTeam = mainTeam;
        if (normalizedLeagueId !== String(seasonConfig?.league_id || '')) {
            try {
                const response = await api.put('/settings/league', { league_id: Number(normalizedLeagueId) });
                leagueChanged = true;
                effectiveMainTeam = response.data?.season?.default_team_id
                    ? String(response.data.season.default_team_id)
                    : String(response.data?.teams?.[0]?.team_id || '');
                localStorage.setItem('mainTeam', effectiveMainTeam);
            } catch (error) {
                setSettingsError(error.response?.data?.detail || 'Не удалось подключиться к указанной лиге');
                setSaving(false);
                return;
            }
        }

        const settings = {
            period,
            puntCategories,
            simulationMode,
            mainTeam: effectiveMainTeam,
            colorByTrend,
            calculationEngine
        };
        onSave(settings);
        setSaving(false);
        onClose();
        if (leagueChanged) window.location.reload();
    };

    const handlePlayerSelectionSave = (selectedPlayers) => {
        setSelectedPlayersCount(selectedPlayers.length);
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
                        {readiness && (
                            <div className={`rounded border px-3 py-2 text-sm ${readiness.ready ? 'border-green-200 bg-green-50 text-green-800' : 'border-amber-200 bg-amber-50 text-amber-900'}`}>
                                <div className="font-medium">
                                    Сезон {readiness.season.year} · лига {readiness.season.league_id} · {readiness.team_count} команд
                                </div>
                                {!readiness.ready && (
                                    <div className="mt-1 text-xs">{readiness.warnings.join(' · ')}</div>
                                )}
                            </div>
                        )}
                        <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
                            <label className="block text-sm font-semibold text-gray-800 mb-2">
                                ESPN League ID
                            </label>
                            <input
                                type="text"
                                inputMode="numeric"
                                value={leagueId}
                                onChange={event => { setLeagueId(event.target.value.replace(/\D/g, '')); setSettingsError(''); }}
                                placeholder="Например: 623163114"
                                className="w-full rounded border bg-white p-2"
                            />
                            <p className="mt-2 text-xs text-gray-600">
                                После сохранения приложение проверит доступ через текущий ESPN-аккаунт, очистит кеш старой лиги и перезагрузит команды и категории. Сезон остаётся {seasonConfig?.year || readiness?.season?.year || 'текущим'}.
                            </p>
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-2">
                                Период статистики:
                            </label>
                            <select
                                className="w-full border p-2 rounded"
                                value={period}
                                onChange={e => setPeriod(e.target.value)}
                            >
                                <option value={periods.total}>Весь сезон</option>
                                <option value={periods.last_30}>Последние 30 дней</option>
                                <option value={periods.last_15}>Последние 15 дней</option>
                                <option value={periods.last_7}>Последние 7 дней</option>
                                <option value={periods.weighted}>Взвешенный (Универсальный)</option>
                            </select>
                        </div>

                        {period === periods.weighted && (
                            <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
                                <div className="mb-3">
                                    <h3 className="font-semibold text-gray-800">Коэффициенты универсального режима</h3>
                                    <p className="text-xs text-gray-600 mt-1">
                                        Настройте, насколько сильно учитывать сезонную форму и последние отрезки. Значения применяются ко всей аналитике универсального периода.
                                    </p>
                                </div>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                    {[
                                        ['total', 'Весь сезон'],
                                        ['last_30', 'Последние 30 дней'],
                                        ['last_15', 'Последние 15 дней'],
                                        ['last_7', 'Последние 7 дней']
                                    ].map(([key, label]) => (
                                        <label key={key} className="text-sm text-gray-700">
                                            <span className="block mb-1">{label}</span>
                                            <div className="relative">
                                                <input
                                                    type="number"
                                                    min="0"
                                                    max="100"
                                                    step="1"
                                                    value={Number((weightedCoefficients[key] * 100).toFixed(1))}
                                                    onChange={event => handleCoefficientChange(key, event.target.value)}
                                                    className="w-full border bg-white p-2 pr-8 rounded"
                                                />
                                                <span className="absolute right-3 top-2 text-gray-500">%</span>
                                            </div>
                                        </label>
                                    ))}
                                </div>
                                <div className={`mt-3 text-sm font-medium ${coefficientsAreValid ? 'text-green-700' : 'text-red-700'}`}>
                                    Сумма: {(coefficientSum * 100).toFixed(1)}% {coefficientsAreValid ? '✓' : '— требуется 100%'}
                                </div>
                            </div>
                        )}

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
                            <p className="mt-2 text-xs text-gray-500">
                                Для драфта: пустой список включает автоматический выбор стратегии. Любая отмеченная категория фиксирует ручной пант и отключает автоматическое переключение.
                            </p>
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-2">
                                Расчётный движок:
                            </label>
                            <select
                                className="w-full border p-2 rounded"
                                value={calculationEngine}
                                onChange={event => setCalculationEngine(event.target.value)}
                            >
                                <option value="calendar">Новый — календарь и lineup-слоты</option>
                                <option value="legacy">Классический — средние и Z-score</option>
                            </select>
                            <p className="text-xs text-gray-500 mt-1">
                                Новый учитывает игровые дни и позиции; классический сохраняет прежнюю методику.
                            </p>
                        </div>

                        {/* Основная команда */}
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-2">
                                Состав для расчётов и симуляций:
                            </label>
                            <select
                                className="w-full border p-2 rounded"
                                value={simulationMode}
                                onChange={event => setSimulationMode(event.target.value)}
                            >
                                <option value="all">Весь текущий ростер</option>
                                <option value="exclude_ir">Без игроков в IR</option>
                                <option value="top_n">Выбранные игроки / лучшие 13</option>
                            </select>
                            <p className="text-xs text-gray-500 mt-1">
                                Это пользовательская настройка; приложение больше не навязывает один режим.
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

                        {/* Окраска Total Z-Score по тренду */}
                        <div className="border-t pt-4">
                            <div className="flex items-center justify-between">
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">
                                        Окраска Total Z-Score по тренду
                                    </label>
                                    <p className="text-xs text-gray-500">
                                        Окрашивает Total Z-Score от ярко-зеленого (улучшение) до ярко-красного (ухудшение) на основе сравнения 15 дней с сезоном
                                    </p>
                                </div>
                                <label className="relative inline-flex items-center cursor-pointer">
                                    <input 
                                        type="checkbox" 
                                        className="sr-only peer"
                                        checked={colorByTrend}
                                        onChange={(e) => setColorByTrend(e.target.checked)}
                                    />
                                    <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                                </label>
                            </div>
                        </div>

                        {/* Настройка игроков для режима top_n */}
                        {mainTeam && simulationMode === 'top_n' && (
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

                        {settingsError && (
                            <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                                {settingsError}
                            </div>
                        )}
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
                            disabled={saving || (period === periods.weighted && !coefficientsAreValid)}
                            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {saving ? 'Сохранение...' : 'Сохранить'}
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

        </div>
    );
};

export default SettingsModal;

