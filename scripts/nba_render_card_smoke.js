#!/usr/bin/env node
/* Phase 3 synthetic card render smoke test.
 *
 * Boots a jsdom page from public/index.html, activates the NBA tab via
 * ?sport=nba&nbaDev=1, manually injects a canned correlations dataset +
 * the dev-synthesized FV/DK prices, runs the pipeline, and writes the
 * resulting NBA tab HTML (scoped to #page-nba-evfinder) to
 * /tmp/nba_card_sample.html so the user can open it in a browser for
 * the Phase 3 screenshot review.
 *
 * Run:
 *   node scripts/nba_render_card_smoke.js
 */

const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');

const INDEX = path.join(__dirname, '..', 'public', 'index.html');
const SCRIPT = path.join(__dirname, '..', 'public', 'utils', 'nbaEvTab.js');
const OUT = '/tmp/nba_card_sample.html';

/* Canonical single-entry correlations fixture. Matches the Phase 1
   output schema so the enumeration code path is exercised identically
   to a real upload. */
function fixtureCorrelations() {
  return {
    schema_version: 1,
    status: 'ok',
    season: '2025-26',
    uploaded_at: '2026-04-21T09:14:33Z',
    entries: [{
      player: 'Donovan Test',
      leg1: { prop: 'Points', side: 'over', line: 27.5 },
      leg2: { prop: 'Rebounds', side: 'over', line: 4.5 },
      r_adj: 0.21,
      r_raw: 0.22,
      p_value: 0.29,
      n_games: 28,
      hit_rate_1: 0.554,
      hit_rate_2: 0.426,
      p_joint: 0.34,
      p_independent: 0.236,
      _adjusted_prob_excel: 0.30,
      type: 'Same Player',
    }, {
      player: 'Donovan Test',
      leg1: { prop: 'Assists', side: 'over', line: 5.5 },
      leg2: { prop: 'Points', side: 'over', line: 24.5 },
      r_adj: 0.33,
      r_raw: 0.34,
      p_value: 0.04,
      n_games: 48,
      hit_rate_1: 0.62,
      hit_rate_2: 0.55,
      p_joint: 0.42,
      p_independent: 0.341,
      _adjusted_prob_excel: 0.38,
      type: 'Same Player',
    }],
    by_player: { 'Donovan Test': [0, 1] },
  };
}

(async () => {
  const html = fs.readFileSync(INDEX, 'utf8');
  const scriptSrc = fs.readFileSync(SCRIPT, 'utf8');

  const vc = new VirtualConsole();
  vc.on('jsdomError', () => {});
  const dom = new JSDOM(html, {
    url: 'http://localhost/?sport=nba&nbaDev=1',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    virtualConsole: vc,
  });
  const { window } = dom;
  /* Stub fetch so the module's reload() call doesn't blow up; we inject
     state manually right after. */
  window.fetch = () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ status: 'empty', entries: [], by_player: {} }) });

  /* Evaluate nbaEvTab.js in the window context (normally loaded via
     <script src>, but jsdom's external-resource fetch for file:// is
     sketchy; direct eval is deterministic). */
  window.eval(scriptSrc);

  await new Promise(r => window.setTimeout(r, 100));

  /* Activate NBA, then inject the fixture + trigger the dev sim. */
  window.setSport('nba');
  await new Promise(r => window.setTimeout(r, 50));
  window.nbaTab._state.correlations = fixtureCorrelations();
  window.nbaTab._state.meta = {
    status: 'ok', uploaded_at: '2026-04-21T09:14:33Z', season: '2025-26',
    source_filename: 'fixture.xlsx', row_count: 2, distinct_players: 1,
    rejected_rows: 0,
  };
  /* Permissive filters so the synthetic edge (which lands anywhere from
     ~-2% to +13% depending on the jittered DK vig) shows up in the
     render. Production defaults stay +3 / 30 / 0.10 — this is a render
     sanity check, not a filter test. */
  window.nbaTab._state.filters.minEvPct = -10;
  window.nbaTab._state.filters.minGames = 10;
  window.nbaTab._state.filters.maxPValue = 1.0;
  window.nbaTab.devSimulate();

  await new Promise(r => window.setTimeout(r, 80));

  const page = window.document.getElementById('page-nba-evfinder');
  const fullHtml = '<!doctype html><html><head><meta charset="utf-8"><title>NBA Phase 3 synthetic card</title>' +
    window.document.querySelector('style').outerHTML +
    '</head><body style="background:#0d0f14;padding:24px">' +
    page.outerHTML +
    '</body></html>';

  fs.writeFileSync(OUT, fullHtml);
  const cards = page.querySelectorAll('.nba-card');
  console.log('rendered', cards.length, 'cards →', OUT);
  if (cards.length) {
    const firstText = cards[0].textContent.replace(/\s+/g, ' ').trim();
    console.log('first card text (condensed):', firstText.slice(0, 260));
  }
  dom.window.close();
})();
