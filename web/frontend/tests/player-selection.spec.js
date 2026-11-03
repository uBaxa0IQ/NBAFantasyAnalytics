import { expect, test } from '@playwright/test';

const players = Array.from({ length: 15 }, (_, i) => ({ name: `Player ${i + 1}`, position: 'PG', total_z: 15 - i, is_ir: i === 0 }));
const selected = players.slice(0, 12).map(player => player.name);

async function openSelection(page, saved, failRoster = false) {
    await page.addInitScript(saved => {
        localStorage.setItem('mainTeam', '');
        localStorage.setItem('simulationMode', 'top_n');
        localStorage.setItem('customTeamPlayers_12', JSON.stringify(saved));
    }, saved);
    await page.route('**/api/**', route => {
        const path = new URL(route.request().url()).pathname;
        if (path === '/api/teams/12/players-for-selection') {
            return route.fulfill(failRoster ? { status: 500, json: {} } : { json: { players } });
        }
        if (path === '/api/settings/readiness') return route.fulfill({ json: { ready: true, season: {year:2027, league_id:123}, team_count:1 } });
        return route.fulfill({ json: path === '/api/teams' ? [{ team_id: 12, team_name: 'uBaxa' }] : {} });
    });
    await page.goto('/');
    await page.getByTitle('Настройки', { exact: true }).click();
    await page.locator('select').filter({ has: page.locator('option[value="12"]') }).selectOption('12');
    await page.getByRole('button', { name: 'Настроить игроков', exact: true }).click();
    return page.getByRole('heading', { name: 'Выбор игроков для симуляции', exact: true }).locator('../..');
}

for (const [name, stale] of [['departed player', 'Former Player'], ['duplicate player', 'Player 1']]) {
    test(`counts visible selections and frees a slot for a ${name}`, async ({ page }) => {
        const modal = await openSelection(page, [...selected, stale]);
        await expect(modal.getByRole('checkbox', { checked: true })).toHaveCount(12);
        await expect(modal.getByText('12/13', { exact: true })).toBeVisible();
        // IR remains selectable; only names absent from the roster are removed.
        await expect(modal.getByRole('cell', { name: 'Player 1', exact: true }).locator('..').getByRole('checkbox')).toBeChecked();
        await modal.getByRole('row').filter({ hasText: 'Player 13' }).getByRole('checkbox').check();
        await expect(modal.getByText('13/13', { exact: true })).toBeVisible();
        await modal.getByRole('button', { name: 'Сохранить', exact: true }).click();
        const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('customTeamPlayers_12')));
        expect(stored).toEqual([...selected, 'Player 13']);
    });
}

test('does not overwrite the selection after a roster loading failure', async ({ page }) => {
    const modal = await openSelection(page, selected, true);
    await expect(modal.getByText('Ошибка загрузки игроков', { exact: true })).toBeVisible();
    await expect(modal.getByRole('button', { name: 'Сохранить', exact: true })).toBeDisabled();
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('customTeamPlayers_12')))).toEqual(selected);
});
