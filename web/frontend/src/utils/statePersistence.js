/**
 * Утилиты для сохранения и загрузки состояния вкладок в localStorage
 */

// Ключи для localStorage
const STORAGE_KEYS = {
    ANALYTICS: 'analytics_state',
    SIMULATION: 'simulation_state',
    DASHBOARD: 'dashboard_state',
    TRADE: 'trade_state',
    MULTITEAM_TRADE: 'multiteam_trade_state',
    PLAYERS: 'players_state',
    ALL_PLAYERS: 'allplayers_state',
    FREE_AGENTS: 'freeagents_state'
};

/**
 * Сохраняет состояние вкладки в localStorage
 * @param {string} key - Ключ для сохранения
 * @param {object} state - Объект состояния для сохранения
 */
export const saveState = (key, state) => {
    try {
        localStorage.setItem(key, JSON.stringify(state));
    } catch (error) {
        console.error(`Error saving state for ${key}:`, error);
    }
};

/**
 * Загружает состояние вкладки из localStorage
 * @param {string} key - Ключ для загрузки
 * @param {object} defaultState - Значения по умолчанию, если состояние не найдено
 * @returns {object} - Загруженное состояние или значения по умолчанию
 */
export const loadState = (key, defaultState = {}) => {
    try {
        const saved = localStorage.getItem(key);
        if (saved) {
            return JSON.parse(saved);
        }
    } catch (error) {
        console.error(`Error loading state for ${key}:`, error);
    }
    return defaultState;
};

/**
 * Очищает сохраненное состояние вкладки
 * @param {string} key - Ключ для очистки
 */
export const clearState = (key) => {
    try {
        localStorage.removeItem(key);
    } catch (error) {
        console.error(`Error clearing state for ${key}:`, error);
    }
};

// Экспорт ключей для удобства
export const StorageKeys = STORAGE_KEYS;










