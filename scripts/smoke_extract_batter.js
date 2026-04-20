#!/usr/bin/env node
/**
 * Smoke-test helper for /api/extract-batter.
 *
 * Reads a batter FV-sheet image, base64-encodes it, posts to a running
 * server's /api/extract-batter endpoint, and prints a per-player summary
 * + the raw unmatched_markets diagnostic list.
 *
 * Requirements:
 *   - server.js running with ANTHROPIC_API_KEY set
 *   - image file path passed as argv[2]
 *
 * Usage:
 *   node scripts/smoke_extract_batter.js path/to/sheet.png [http://localhost:3300]
 */

const fs = require('fs');
const path = require('path');

const imgPath = process.argv[2];
const baseUrl = process.argv[3] || 'http://localhost:3000';
if (!imgPath) {
  console.error('usage: node scripts/smoke_extract_batter.js <image> [base-url]');
  process.exit(2);
}
const buf = fs.readFileSync(imgPath);
const ext = path.extname(imgPath).slice(1).toLowerCase();
const mimeMap = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif' };
const mime = mimeMap[ext] || 'image/png';
const b64 = buf.toString('base64');

(async () => {
  const t0 = Date.now();
  const r = await fetch(baseUrl + '/api/extract-batter', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ image: b64, mime }),
  });
  const j = await r.json();
  const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
  if (j.error) {
    console.error('ERROR:', j.error);
    if (j.raw) console.error('RAW:', j.raw.slice(0, 800));
    process.exit(1);
  }

  const players = j.players || [];
  const unmatched = j.unmatched_markets || [];

  console.log(`=== /api/extract-batter (${elapsed}s) ===\n`);
  console.log(`players parsed:   ${players.length}`);
  console.log(`rows dropped:     ${unmatched.length}`);

  // Props-per-player distribution
  const dist = {};
  let totalProps = 0;
  for (const p of players) {
    const n = (p.props || []).length;
    totalProps += n;
    dist[n] = (dist[n] || 0) + 1;
  }
  console.log(`total prop rows:  ${totalProps} (Over+Under merged into single records)`);
  console.log('\nprops-per-player distribution:');
  for (const k of Object.keys(dist).sort((a, b) => Number(a) - Number(b))) {
    console.log(`  ${k} props: ${dist[k]} player(s)`);
  }

  // Stat coverage
  const statCounts = {};
  for (const p of players) {
    for (const pr of (p.props || [])) {
      const k = pr.stat;
      statCounts[k] = (statCounts[k] || 0) + 1;
    }
  }
  console.log('\nstat coverage:');
  for (const [s, n] of Object.entries(statCounts).sort((a, b) => b[1] - a[1])) {
    console.log(`  ${s.padEnd(14)} ${n}`);
  }

  // Suspicion flags
  let susCount = 0;
  for (const p of players) {
    for (const pr of (p.props || [])) {
      if (pr.over_fv_suspicious || pr.under_fv_suspicious) susCount++;
    }
  }
  if (susCount > 0) console.log(`\n⚠ avg_fv-suspicious props: ${susCount} (visually verify the FV column)`);

  // Per-player dump (first 20)
  console.log('\n=== per-player props (first 20 players) ===');
  for (const p of players.slice(0, 20)) {
    console.log(`\n${p.player}  team=${p.team || '?'}  game=${p.game || '?'}  (${p.props.length} props)`);
    for (const pr of p.props) {
      const o = pr.over_fv != null  ? `O=${String(pr.over_fv).padStart(5)}` : 'O=  —  ';
      const u = pr.under_fv != null ? `U=${String(pr.under_fv).padStart(5)}` : 'U=  —  ';
      const sus = (pr.over_fv_suspicious || pr.under_fv_suspicious) ? ' ⚠' : '';
      console.log(`   ${pr.stat.padEnd(13)} @${pr.threshold}   ${o}   ${u}   odds=${pr.over_avg_odds || pr.under_avg_odds || ''}${sus}`);
    }
  }

  if (unmatched.length) {
    console.log(`\n=== unmatched_markets (${unmatched.length} rows dropped) ===`);
    for (const u of unmatched.slice(0, 30)) {
      console.log(`  L=${u.L}  ${(u.batter || '?').padEnd(20)}  ${(u.market || '?').padEnd(35)}  reason: ${u.reason}`);
    }
    if (unmatched.length > 30) console.log(`  ... and ${unmatched.length - 30} more`);
  }
})();
