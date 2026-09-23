import { LEAGUE_CATEGORIES as CATEGORIES } from './categories';

export const WORKING_CATEGORIES = ['FG%', 'REB', 'AST', 'A/TO', 'STL', 'BLK', 'DD'];
const CORE_REACH = 8;

export const CATEGORY_TARGETS = {
    'FG%': { top3: 0.504, first: 0.524, goal: 0.515 },
    REB: { top3: 5734, first: 6190, goal: 6000 },
    AST: { top3: 3904, first: 4293, goal: 4100 },
    'A/TO': { top3: 2.16, first: 2.41, goal: 2.30 },
    STL: { top3: 994, first: 1059, goal: 1030 },
    BLK: { top3: 718, first: 828, goal: 800 },
    DD: { top3: 173, first: 208, goal: 200 },
};

export const snakePickNumbers = (slot, teamCount, rounds) => Array.from({ length: rounds }, (_, round) => (
    round * teamCount + (round % 2 === 0 ? slot : teamCount + 1 - slot)
));

const erfc = x => {
    const z = Math.abs(x);
    const t = 1 / (1 + 0.5 * z);
    const ans = t * Math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))));
    return x >= 0 ? ans : 2 - ans;
};

const survival = (adp, pick) => {
    if (adp == null || pick == null) return 1;
    if (Number(pick) <= 1) return 1;
    const sigma = Math.max(3, Math.min(18, 2.5 + 0.12 * Number(adp)));
    const z = (Number(pick) - 0.5 - Number(adp)) / sigma;
    return Math.max(0, Math.min(1, 0.5 * erfc(z / Math.SQRT2)));
};

const marketPick = player => {
    const value = player?.espn_market_pick ?? player?.espn_adp;
    return value == null ? null : Number(value);
};

const isCore = (player, pick) => {
    const market = marketPick(player);
    return market == null || pick == null || market <= Number(pick) + CORE_REACH;
};

const bandFor = (value, target) => {
    if (value == null || !target) return 'empty';
    if (value + 1e-12 >= target.first) return 'first';
    if (value + 1e-12 >= target.goal) return 'goal';
    if (value + 1e-12 >= target.top3) return 'top3';
    return 'below';
};

export const projectedTeamTotals = (roster, categories = CATEGORIES) => {
    const component = {};
    const hasRaw = {};
    const zFallback = {};
    roster.forEach(player => {
        const stats = player.stats || {};
        const gp = Number(stats.GP);
        const games = Number.isFinite(gp) ? Math.max(0, gp) : 82;
        Object.entries(stats).forEach(([key, value]) => {
            if (key === 'GP' || typeof value !== 'number') return;
            component[key] = (component[key] || 0) + value * games;
            hasRaw[key] = true;
        });
        Object.entries(player.z_scores || {}).forEach(([category, value]) => {
            if (typeof value === 'number') zFallback[category] = (zFallback[category] || 0) + value;
        });
    });
    return Object.fromEntries(categories.map(category => {
        if (category === 'FG%' && component.FGA) return [category, component.FGM / component.FGA];
        if (category === 'FT%' && component.FTA) return [category, component.FTM / component.FTA];
        if (category === '3PT%' && component['3PA']) return [category, component['3PM'] / component['3PA']];
        if (category === 'A/TO' && component.TO) return [category, component.AST / component.TO];
        if (hasRaw[category]) return [category, component[category]];
        return [category, zFallback[category] ?? null];
    }));
};

export const evaluateConstructor = ({ players, rosterIds, picks, categories = CATEGORIES, puntCategories = [] }) => {
    const punts = new Set(puntCategories || []);
    const byId = Object.fromEntries((players || []).map(player => [Number(player.player_id), player]));
    const roster = (rosterIds || []).map(id => byId[Number(id)]).filter(Boolean);
    const totals = roster.length ? projectedTeamTotals(roster, categories) : Object.fromEntries(categories.map(category => [category, null]));
    const incomplete = roster.length < (picks?.length || 0);
    const working = WORKING_CATEGORIES.filter(category => categories.includes(category) && !punts.has(category));
    const categoryRows = categories.map(category => {
        const target = CATEGORY_TARGETS[category];
        const punt = punts.has(category);
        let band = punt ? 'punt' : bandFor(totals[category], target);
        if (incomplete && !punt && band === 'below') band = 'building';
        return {
            category,
            value: totals[category] == null ? null : Number(totals[category]),
            top3: target?.top3 ?? null,
            first: target?.first ?? null,
            goal: target?.goal ?? null,
            band,
            working: working.includes(category),
        };
    });
    const slots = (picks || []).map((pick, index) => {
        const player = byId[Number(rosterIds?.[index])];
        const chance = player ? survival(marketPick(player), pick) : null;
        return {
            index,
            pick,
            player_id: player ? Number(player.player_id) : null,
            available: chance == null ? null : Math.round(chance * 1000) / 10,
            core: Boolean(player && isCore(player, pick)),
        };
    });
    const named = slots.filter(slot => slot.player_id);
    const coreSlots = named.filter(slot => slot.core);
    const product = rows => rows.reduce((total, slot) => total * ((slot.available ?? 100) / 100), 1);
    return {
        filled: roster.length,
        rounds: picks?.length || 0,
        totals,
        categories: categoryRows,
        working_in_goal: working.filter(category => ['goal', 'first'].includes(bandFor(totals[category], CATEGORY_TARGETS[category]))).length,
        working_count: working.length,
        assembly: {
            full_rate: named.length ? Math.round(product(named) * 1000) / 10 : null,
            core_rate: coreSlots.length ? Math.round(product(coreSlots) * 1000) / 10 : (named.length ? 100 : null),
            slots,
            planned: named.length,
            core_count: coreSlots.length,
        },
        picks,
    };
};

export const buildConstructorBoard = (recommendations, draftState, teamId) => {
    const teamCount = Math.max(1, Number(draftState?.team_count || recommendations?.simulation?.team_count || 1));
    const rounds = Math.max(1, Number(recommendations?.draft_rounds || draftState?.draft_rounds || draftState?.roster_size || 13));
    const order = draftState?.settings?.pick_order || [];
    const orderIndex = order.findIndex(id => String(id) === String(teamId));
    const slot = Number(recommendations?.simulation?.slot) || (orderIndex >= 0 ? orderIndex + 1 : 1);
    const planned = Array.isArray(recommendations?.planned_picks) ? recommendations.planned_picks.filter(Boolean) : [];
    const picks = planned.length === rounds ? planned : snakePickNumbers(slot, teamCount, rounds);
    return {
        players: recommendations?.players || [],
        slot,
        team_count: teamCount,
        rounds,
        picks,
        order_known: Boolean(draftState?.settings?.order_known || order.length),
        categories: CATEGORIES,
    };
};
