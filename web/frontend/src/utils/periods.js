import { configureLeagueCategories, DEFAULT_CATEGORIES } from './categories';

const fallbackYear = new Date().getFullYear();

export const fallbackPeriods = {
    total: `${fallbackYear}_total`,
    last_30: `${fallbackYear}_last_30`,
    last_15: `${fallbackYear}_last_15`,
    last_7: `${fallbackYear}_last_7`,
    projected: `${fallbackYear}_projected`,
    weighted: `${fallbackYear}_weighted`
};

export const getSeasonConfig = () => {
    try {
        const stored = JSON.parse(localStorage.getItem('seasonConfig') || 'null');
        if (stored?.periods) {
            configureLeagueCategories(stored.categories);
            return stored;
        }
    } catch {
        // Поврежденная локальная настройка не должна мешать запуску приложения.
    }
    configureLeagueCategories(DEFAULT_CATEGORIES);
    return { year: fallbackYear, default_period: fallbackPeriods.total, periods: fallbackPeriods, categories: DEFAULT_CATEGORIES };
};

export const saveSeasonConfig = (season) => {
    if (season?.periods) {
        configureLeagueCategories(season.categories);
        localStorage.setItem('seasonConfig', JSON.stringify(season));
    }
};

export const normalizeSavedPeriod = (period, periods = getSeasonConfig().periods) => {
    if (Object.values(periods).includes(period)) return period;
    const suffix = String(period || '').replace(/^\d+_/, '');
    return periods[suffix] || periods.total;
};
