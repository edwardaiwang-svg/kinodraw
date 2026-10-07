// Drive the real Studio page in headless Chromium (Playwright, the edu/ package's dev dependency).
//   node tests/studio_browser.mjs SCENARIO URL [SHOTS_DIR]
// Playwright is found in $KINODRAW_PLAYWRIGHT (a folder whose node_modules has it) or edu/. Exit 0 = passed.
import assert from 'node:assert/strict';
import { mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const require = createRequire(join(process.env.KINODRAW_PLAYWRIGHT || join(ROOT, 'edu'), 'package.json'));
const { chromium } = require('playwright');
const [scenario, url, shots] = process.argv.slice(2);
if (shots) mkdirSync(shots, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1320, height: 880 } });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
const shot = async (name) => { if (shots) { await page.waitForTimeout(300); await page.screenshot({ path: join(shots, name + '.png') }); } };
const open = () => page.locator('#modal').evaluate((m) => !m.classList.contains('hidden'));
const active = () => page.evaluate(() => {
  const e = document.activeElement;
  return { id: e.id, tag: e.tagName, text: e.textContent.trim(), inside: !!e.closest('#modal .modal-box') };
});
// Every control a keyboard can reach in the open dialog, in page order.
const reachable = () => page.evaluate(() => [...document.querySelectorAll('#modal .modal-box :is(button, [href], input, select, textarea, [tabindex])')]
  .filter((e) => !e.disabled && e.tabIndex >= 0 && e.getClientRects().length).map((e, i) => (e.dataset.reach = i)));

async function a11y() {
  await page.goto(url);
  await page.waitForSelector('#btn-settings');
  await page.focus('#btn-settings');
  await page.keyboard.press('Enter');
  assert.ok(await open(), 'Settings did not open from the keyboard');
  const dialog = await page.evaluate(() => {
    const box = document.querySelector('#modal .modal-box'), label = box.getAttribute('aria-labelledby');
    return { role: box.getAttribute('role'), modal: box.getAttribute('aria-modal'),
      label: label && document.getElementById(label)?.textContent, close: document.querySelector('#modal .close').getAttribute('aria-label') };
  });
  assert.deepEqual(dialog, { role: 'dialog', modal: 'true', label: 'Settings', close: 'Close' });
  assert.ok((await active()).inside, 'focus stayed outside the open dialog');
  await shot('a11y-1-dialog-focus-inside');
  const order = await reachable();
  assert.ok(order.length > 2);
  await page.focus(`[data-reach="${order.length - 1}"]`);
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.dataset.reach), '0', 'Tab from the last control left the dialog');
  await page.keyboard.press('Shift+Tab');
  assert.equal(await page.evaluate(() => document.activeElement.dataset.reach), String(order.length - 1), 'Shift+Tab from the first control left the dialog');
  await page.keyboard.press('Escape');
  assert.equal(await open(), false, 'Escape did not close the dialog');
  assert.equal((await active()).id, 'btn-settings', 'focus did not return to the button that opened the dialog');

  await page.keyboard.press('?');
  assert.ok(await open(), '? did not open the shortcut list');
  const sheet = await page.locator('#modal-body').innerText();
  for (const key of ['Ctrl/⌘+S', 'Ctrl/⌘+Z', 'Ctrl/⌘+Shift+Z', 'Esc', '?']) assert.ok(sheet.includes(key), 'shortcut list misses ' + key);
  assert.ok((await active()).inside);
  await shot('a11y-2-shortcuts');
  await page.keyboard.press('Escape');
  assert.equal(await open(), false);

  await page.click('#btn-new');
  await page.focus('#script');
  await page.keyboard.type('Why? Because.');
  assert.equal(await open(), false, '? typed into the script opened the shortcut list');
  assert.equal(await page.inputValue('#script'), 'Why? Because.');
}

const tiles = () => page.locator('#picks [data-id]').evaluateAll((all) => all.map((e) => e.dataset.id));
const chips = () => page.locator('#packs [data-pack]').evaluateAll((all) => all.map((e) => e.textContent));
let inflight = 0;                                    // requests still answering (a search waits 250 ms for typing)
for (const done of ['requestfinished', 'requestfailed']) page.on(done, () => inflight--);
page.on('request', () => inflight++);
const settle = async () => { await page.waitForTimeout(300); while (inflight > 0) await page.waitForTimeout(50); };
const choose = async (name) => { await page.locator('#packs [data-pack]', { hasText: name }).click(); await settle(); };
async function openPicker() {
  await page.locator('.beat .add').first().click();
  await page.waitForSelector('#picks [data-id]');
  await settle();
}

async function picker() {
  await page.goto(url);
  await page.waitForSelector('.beat .add');
  await openPicker();
  assert.equal((await active()).id, 'q', 'the picker does not start in its search box');
  const names = await chips();
  for (const name of ['All', '★ Favourites (0)', 'Recent (0)', 'Doodles', 'Fluent Emoji', 'Tabler Icons', 'Health Icons'])
    assert.ok(names.some((c) => c.startsWith(name)), 'no chip ' + name + ' in ' + names);
  await page.fill('#q', '');
  await choose('Tabler Icons');
  let shown = await tiles();
  assert.equal(shown.length, 32);
  assert.ok(shown.every((id) => id.startsWith('tb_')), 'Tabler Icons shows other pictures');
  assert.match(await page.textContent('#pick-count'), /^32 of 3,\d{3} pictures$/);
  await page.click('#pick-more'); await settle();
  assert.equal((await tiles()).length, 64);
  await choose('All');
  await page.fill('#q', 'elefant'); await settle();
  shown = await tiles();
  assert.ok(shown.slice(0, 5).includes('fl_elephant'), 'elefant does not find the elephant: ' + shown.slice(0, 5));
  await page.locator('[data-star="fl_elephant"]').click(); await settle();
  assert.equal(await page.getAttribute('[data-star="fl_elephant"]', 'aria-pressed'), 'true');
  const picked = shown.find((id) => id !== 'fl_elephant');
  await page.locator(`#picks [data-id="${picked}"]`).click(); await settle();
  assert.equal(await open(), false, 'picking did not close the picker');
  assert.ok(await page.locator(`.item img[src*="/doodle/${picked}.svg"]`).count(), 'the picked picture is not on the board');

  await openPicker();
  await page.fill('#q', 'elefant'); await settle();
  await shot('picker-1-typo-chips');
  await choose('★ Favourites');
  assert.deepEqual(await tiles(), ['fl_elephant']);
  assert.equal(await page.inputValue('#q'), '', 'Favourites kept the search');
  await shot('picker-2-favourites');
  await choose('Recent');
  assert.deepEqual(await tiles(), [picked]);
  await page.keyboard.press('Escape');

  await page.reload();                           // kept by the Studio, not by this page
  await page.waitForSelector('.beat .add');
  await openPicker();
  await choose('★ Favourites');
  assert.deepEqual(await tiles(), ['fl_elephant']);
  await page.locator('[data-star="fl_elephant"]').click(); await settle();
  assert.ok((await chips()).includes('★ Favourites (0)'));
}

try {
  await { a11y, picker }[scenario]();
  assert.deepEqual(errors, [], 'the page logged errors');
  console.log(JSON.stringify({ scenario, passed: true }));
} catch (error) {
  console.error(error);
  process.exitCode = 1;
} finally {
  await browser.close();
}
