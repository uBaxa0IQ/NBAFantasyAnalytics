import { expect, test } from '@playwright/test';

const periods = Object.fromEntries(
    ['total', 'projected', 'last_30', 'last_15', 'last_7', 'weighted'].map(key => [key, `2027_${key}`]),
);
const season = { year: 2027, league_id: 123, periods, categories: ['PTS', 'REB'] };
const seasonModeKey = `season-mode:${season.league_id}:${periods.projected}`;
const saved = (page, key) => page.evaluate(key => localStorage.getItem(key), key);
const periodSelect = page => page.locator('select').filter({ has: page.locator('option[value$="_projected"]') });

async function setup(page, { period = periods.total, enteredSeason = true, settingsReady = Promise.resolve() } = {}) {
    let draftRequests = 0;
    await page.clock.install();
    await page.addInitScript(({ season, seasonModeKey, period, enteredSeason }) => {
        if (localStorage.getItem('period') !== null) return;
        localStorage.setItem('seasonConfig', JSON.stringify(season));
        localStorage.setItem('period', period);
        localStorage.setItem('puntsEnabled', 'true');
        localStorage.setItem('puntCategories', '["PTS"]');
        if (enteredSeason) localStorage.setItem(seasonModeKey, 'true');
    }, { season, seasonModeKey, period, enteredSeason });
    await page.route('**/api/**', async route => {
        const path = new URL(route.request().url()).pathname;
        let json = {};
        if (path === '/api/settings') {
            await settingsReady;
            json = { season };
        } else if (path === '/api/teams') {
            json = [];
        } else if (path === '/api/draft/state') {
            draftRequests += 1;
            json = { status: 'completed', season_started: false };
        } else if (path === '/api/settings/weighted-coefficients') {
            json = { total: 0.45, last_30: 0.35, last_15: 0.15, last_7: 0.05 };
        } else if (path === '/api/settings/readiness') {
            json = { ready: true, season, team_count: 0 };
        }
        await route.fulfill({ json });
    });
    await page.goto('/');
    await expect(page.getByTitle('Настройки', { exact: true })).toBeVisible();
    await expect.poll(() => draftRequests).toBeGreaterThan(0);
    return { draftRequests: () => draftRequests };
}

for (const key of ['total', 'last_7', 'weighted', 'projected']) {
    test(`preserves saved ${key} after draft polling and reload`, async ({ page }) => {
        const state = await setup(page, { period: periods[key] });
        await page.getByTitle('Настройки', { exact: true }).click();
        await expect(periodSelect(page)).toHaveValue(periods[key]);
        await page.getByRole('button', { name: 'Отмена', exact: true }).click();
        const before = state.draftRequests();
        await page.clock.fastForward(16000);
        await expect.poll(state.draftRequests).toBeGreaterThan(before);
        await expect.poll(() => saved(page, 'period')).toBe(periods[key]);
        await page.reload();
        await page.getByTitle('Настройки', { exact: true }).click();
        await expect(periodSelect(page)).toHaveValue(periods[key]);
    });
}

test('entering the main application preserves the selected period', async ({ page }) => {
    await setup(page, { enteredSeason: false });
    await page.getByRole('button', { name: 'Перейти в основное приложение', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Dashboard', exact: true })).toBeVisible();
    await expect.poll(() => saved(page, 'period')).toBe(periods.total);
    await expect.poll(() => saved(page, seasonModeKey)).toBe('true');
});

test('late season settings do not overwrite a newly saved period', async ({ page }) => {
    let releaseSettings;
    const settingsReady = new Promise(resolve => { releaseSettings = resolve; });
    await setup(page, { period: periods.projected, settingsReady });
    await page.getByTitle('Настройки', { exact: true }).click();
    await periodSelect(page).selectOption(periods.total);
    await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
    await expect.poll(() => saved(page, 'period')).toBe(periods.total);
    const response = page.waitForResponse('**/api/settings');
    releaseSettings();
    await response;
    await page.getByTitle('Настройки', { exact: true }).click();
    await expect(periodSelect(page)).toHaveValue(periods.total);
});

test('shortcuts work outside editors without changing settings while typing', async ({ page }) => {
    await setup(page);
    await page.locator('body').press('Shift+S');
    await expect.poll(() => saved(page, 'period')).toBe(periods.projected);
    await page.locator('body').press('Shift+S');
    await expect.poll(() => saved(page, 'period')).toBe(periods.total);
    await page.locator('body').press('Shift+P');
    await expect.poll(() => saved(page, 'puntsEnabled')).toBe('false');
    await page.locator('body').press('Shift+P');
    await expect.poll(() => saved(page, 'puntsEnabled')).toBe('true');

    await page.evaluate(() => {
        const container = document.createElement('div');
        container.id = 'editors';
        container.innerHTML = '<input><textarea></textarea><select><option>One</option></select><div contenteditable="true"><span>Editable</span></div><div role="textbox" tabindex="0"></div>';
        document.body.append(container);
    });
    for (const selector of ['input', 'textarea', 'select', '[contenteditable]', '[role="textbox"]']) {
        const editor = page.locator(`#editors ${selector}`);
        await editor.press('Shift+S');
        await expect.poll(() => saved(page, 'period')).toBe(periods.total);
        await editor.press('Shift+P');
        await expect.poll(() => saved(page, 'puntsEnabled')).toBe('true');
    }
    await page.locator('#editors [contenteditable] span').dispatchEvent('keydown', { code: 'KeyS', shiftKey: true });
    await expect.poll(() => saved(page, 'period')).toBe(periods.total);
    await expect.poll(() => saved(page, 'puntsEnabled')).toBe('true');
});

test('open settings keep pending edits through shortcuts and background polling', async ({ page }) => {
    const state = await setup(page);
    await page.getByTitle('Настройки', { exact: true }).click();
    await periodSelect(page).selectOption(periods.last_7);
    // Even when focus leaves a field, shortcuts must not change the saved snapshot.
    await page.locator('body').press('Shift+S');
    await page.locator('body').press('Shift+P');
    const before = state.draftRequests();
    await page.clock.fastForward(16000);
    await expect.poll(state.draftRequests).toBeGreaterThan(before);
    await expect(periodSelect(page)).toHaveValue(periods.last_7);
    await expect.poll(() => saved(page, 'period')).toBe(periods.total);
    await expect.poll(() => saved(page, 'puntsEnabled')).toBe('true');
    await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
    await expect.poll(() => saved(page, 'period')).toBe(periods.last_7);
    await page.getByTitle('Настройки', { exact: true }).click();
    await expect(periodSelect(page)).toHaveValue(periods.last_7);
});
