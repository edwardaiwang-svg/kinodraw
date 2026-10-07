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

try {
  await { a11y }[scenario]();
  assert.deepEqual(errors, [], 'the page logged errors');
  console.log(JSON.stringify({ scenario, passed: true }));
} catch (error) {
  console.error(error);
  process.exitCode = 1;
} finally {
  await browser.close();
}
