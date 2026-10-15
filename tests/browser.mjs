import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from 'playwright-core';

const base = 'http://127.0.0.1:3000';
const artifacts = new URL('../artifacts/', import.meta.url);
await mkdir(artifacts, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome',
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1680, height: 1200 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
const results = [];

async function graphData() {
  return page.evaluate(() => [...document.querySelectorAll('*')]
    .filter(element => element._cyreg?.cy)
    .map(element => ({
      nodes: element._cyreg.cy.nodes().map(node => node.id()).sort(),
      edges: element._cyreg.cy.edges().map(edge => edge.data()),
    })));
}

async function waitForGraph(redis) {
  await page.waitForFunction(expectedRedis => {
    const graphs = [...document.querySelectorAll('*')].filter(e => e._cyreg?.cy);
    return graphs.length === 2 && graphs.every(e => {
      const cy = e._cyreg.cy;
      return cy.nodes().length === (expectedRedis ? 3 : 2)
        && cy.edges().length === (expectedRedis ? 2 : 1)
        && (cy.getElementById('redis').length === 1) === expectedRedis
        && cy.edges().every(edge => Number.isFinite(edge.data('metrics').response_time));
    });
  }, redis, { timeout: 60000 });
}

async function select(index, text) {
  await page.getByRole('combobox').nth(index).click();
  await page.getByRole('option', { name: text, exact: true }).click();
}

function latency(graph) {
  const edge = graph.edges.find(e => e.source === 'app-a' && e.target === 'app-b');
  assert.ok(edge, 'app-a -> app-b must exist');
  assert.ok(Number.isFinite(edge.metrics.response_time) && edge.metrics.response_time > 0);
  assert.ok(edge.metrics.rate > 0);
  return edge.metrics.response_time;
}

async function capture(name) {
  const graphs = await graphData();
  results.push({ name, graphs });
  await page.screenshot({ path: new URL(`${name}.png`, artifacts).pathname, fullPage: true });
  return graphs;
}

try {
  await page.goto(`${base}/d/novatec-journeys?refresh=1h`, { waitUntil: 'networkidle' });
  await waitForGraph(true);
  const inbound = await capture('01-whatsapp');
  assert.deepEqual(inbound[0].nodes, ['app-a', 'app-b', 'redis']);
  assert.ok(latency(inbound[1]) > latency(inbound[0]) + 20,
    'global metrics must include the slower notification journey');

  await select(0, 'Notificacao ativa');
  await waitForGraph(false);
  const notification = await capture('02-notification');
  assert.deepEqual(notification[0].nodes, ['app-a', 'app-b']);
  assert.ok(latency(notification[0]) > latency(inbound[0]) + 70);
  assert.ok(latency(notification[0]) > latency(notification[1]) + 20);

  const tenantQuery = page.waitForRequest(req =>
    req.url().includes('/api/ds/query')
      && (req.postData() || '').includes('tenant-b'));
  await select(1, 'tenant-b');
  await tenantQuery;
  await waitForGraph(false);
  await capture('03-tenant-b');
  assert.ok(page.url().includes('var-tenant=tenant-b'));

  await select(0, 'All');
  await waitForGraph(true);
  const all = await capture('04-all');
  assert.deepEqual(all[0].nodes, ['app-a', 'app-b', 'redis']);
  assert.ok(Math.abs(latency(all[0]) - latency(all[1])) < 5,
    'when all journeys are selected both panels must agree');

  await select(0, 'Entrada normal de WhatsApp');
  await waitForGraph(true);
  await select(0, 'Notificacao ativa');
  await waitForGraph(false);
  await capture('05-no-stale-redis');

  await page.goto(`${base}/d/novatec-journeys?var-journey=does_not_exist&refresh=1h`,
    { waitUntil: 'networkidle' });
  await page.waitForFunction(() =>
    document.body.innerText.includes('No data to show - the query returned no data.'));
  assert.equal((await graphData()).length, 0, 'unknown journey must not fall back to all services');
  await capture('06-unknown-journey');
  assert.deepEqual(errors, [], 'no uncaught JavaScript errors');
  await writeFile(new URL('browser-results.json', artifacts), JSON.stringify(results, null, 2));
  console.log('PASS: browser rendered real latency, filtered nodes/edges, tenant query, All, repeated transitions and empty journey.');
  console.log(`Evidence: ${artifacts.pathname}`);
} catch (error) {
  await page.screenshot({ path: new URL('failure.png', artifacts).pathname, fullPage: true });
  console.error((await page.locator('body').innerText()).slice(-6000));
  throw error;
} finally {
  await browser.close();
}
