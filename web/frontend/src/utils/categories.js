export const DEFAULT_CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'FG%', 'FT%', '3PT%', 'A/TO'];

// Mutated in place so every component importing this reference immediately
// sees the active league category set after settings load.
export const LEAGUE_CATEGORIES = [...DEFAULT_CATEGORIES];

export const configureLeagueCategories = (categories) => {
    const next = Array.isArray(categories) && categories.length ? categories : DEFAULT_CATEGORIES;
    LEAGUE_CATEGORIES.splice(0, LEAGUE_CATEGORIES.length, ...next);
    return LEAGUE_CATEGORIES;
};
