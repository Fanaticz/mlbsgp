#!/usr/bin/env node
/* NBA Phase 1 smoke test.
 *
 * Assumes the server is running locally on PORT (default 3000) with
 * NBA_DATA_DIR pointing at an empty directory. Generates a synthetic xlsx
 * via scripts/nba_generate_test_xlsx.py, posts it to the upload endpoint,
 * verifies meta + dataset fetches round-trip, then exercises rollback.
 *
 * Run:
 *   node scripts/nba_smoke_upload.js
 *   PORT=3000 node scripts/nba_smoke_upload.js
 */

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const zlib = require('zlib');

const PORT = process.env.PORT || 3000;
const BASE = 'http://127.0.0.1:' + PORT;
const TMP_DIR = process.env.NBA_SMOKE_TMP || '/tmp/nba_smoke';

function log(label, obj) {
  console.log('\n=== ' + label + ' ===');
  console.log(typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2));
}

function fail(msg) {
  console.error('\nFAIL: ' + msg);
  process.exit(1);
}

async function main() {
  fs.mkdirSync(TMP_DIR, { recursive: true });

  // 1. Generate two distinct synthetic xlsx files so we can test rollback.
  const xlsx1 = path.join(TMP_DIR, 'synth_v1.xlsx');
  const xlsx2 = path.join(TMP_DIR, 'synth_v2.xlsx');
  const gen1 = spawnSync('python3', [
    path.join(__dirname, 'nba_generate_test_xlsx.py'),
    '--out', xlsx1, '--seed', '11', '--rows', '72', '--include-teammate',
  ]);
  if (gen1.status !== 0) fail('generate v1 failed: ' + gen1.stderr.toString());
  const gen2 = spawnSync('python3', [
    path.join(__dirname, 'nba_generate_test_xlsx.py'),
    '--out', xlsx2, '--seed', '22', '--rows', '51',
  ]);
  if (gen2.status !== 0) fail('generate v2 failed: ' + gen2.stderr.toString());
  log('generated', { xlsx1, xlsx2 });

  // 2. Cold start: meta must be 'empty'.
  let meta = await (await fetch(BASE + '/api/nba/correlations/meta')).json();
  log('meta (cold start)', meta);
  if (meta.status !== 'empty') fail('expected cold-start meta.status=empty, got ' + meta.status);

  let corr = await (await fetch(BASE + '/api/nba/correlations')).json();
  if (corr.status !== 'empty' || (corr.entries || []).length !== 0) {
    fail('expected cold-start correlations empty, got ' + JSON.stringify(corr).slice(0, 200));
  }

  // 3. Upload v1. Multipart via native FormData.
  const buf1 = fs.readFileSync(xlsx1);
  const fd1 = new FormData();
  fd1.append('file', new Blob([buf1]), 'synth_v1.xlsx');
  const up1 = await (await fetch(BASE + '/api/nba/upload-correlations', {
    method: 'POST',
    body: fd1,
  })).json();
  log('upload v1', up1);
  if (!up1.ok) fail('upload v1 not ok: ' + (up1.error || ''));
  if (up1.rejected_rows < 1) fail('expected at least 1 rejected teammate row, got ' + up1.rejected_rows);
  if (up1.row_count < 50) fail('expected ~72 rows, got ' + up1.row_count);

  // 4. Fetch meta + dataset, confirm contents.
  meta = await (await fetch(BASE + '/api/nba/correlations/meta')).json();
  log('meta (after v1)', meta);
  if (meta.status !== 'ok' || meta.row_count !== up1.row_count) {
    fail('meta mismatch after upload');
  }

  const corrRes = await fetch(BASE + '/api/nba/correlations');
  // Response body is gzipped JSON because we set Content-Encoding:gzip. fetch's
  // WHATWG streams layer will auto-decode gzip so .json() works.
  const corrJson = await corrRes.json();
  log('correlations (after v1)', {
    season: corrJson.season,
    schema_version: corrJson.schema_version,
    entries_len: (corrJson.entries || []).length,
    by_player_keys: Object.keys(corrJson.by_player || {}),
  });
  if ((corrJson.entries || []).length !== up1.row_count) {
    fail('entries length mismatch');
  }
  // by_player index must cover every entry.
  const indexed = new Set();
  for (const idxs of Object.values(corrJson.by_player)) idxs.forEach(i => indexed.add(i));
  if (indexed.size !== corrJson.entries.length) {
    fail('by_player index does not cover every entry: ' + indexed.size + ' vs ' + corrJson.entries.length);
  }

  // Round-trip check: pull the first entry for the first player and verify
  // fields look sane.
  const firstPlayer = Object.keys(corrJson.by_player)[0];
  const firstIdx = corrJson.by_player[firstPlayer][0];
  const firstEntry = corrJson.entries[firstIdx];
  log('round-trip sample', firstEntry);
  if (firstEntry.player !== firstPlayer) fail('by_player points to wrong entry');
  if (firstEntry.leg1.side !== 'over' && firstEntry.leg1.side !== 'under') {
    fail('side not normalized lowercase: ' + firstEntry.leg1.side);
  }
  if (!firstEntry.p_joint || firstEntry.p_joint > 1 || firstEntry.p_joint < 0) {
    fail('p_joint out of range');
  }

  // 5. Upload v2, confirm it replaced v1 and that history archived v1.
  const buf2 = fs.readFileSync(xlsx2);
  const fd2 = new FormData();
  fd2.append('file', new Blob([buf2]), 'synth_v2.xlsx');
  const up2 = await (await fetch(BASE + '/api/nba/upload-correlations', {
    method: 'POST',
    body: fd2,
  })).json();
  log('upload v2', up2);
  if (!up2.ok) fail('upload v2 not ok');

  meta = await (await fetch(BASE + '/api/nba/correlations/meta')).json();
  if (meta.row_count !== up2.row_count) fail('meta did not reflect v2 upload');

  // 6. Invalid file: existing data should not be touched.
  fs.writeFileSync(path.join(TMP_DIR, 'bad.xlsx'), 'not xlsx content');
  const bad = fs.readFileSync(path.join(TMP_DIR, 'bad.xlsx'));
  const fdBad = new FormData();
  fdBad.append('file', new Blob([bad]), 'bad.xlsx');
  const badRes = await fetch(BASE + '/api/nba/upload-correlations', { method: 'POST', body: fdBad });
  const badJson = await badRes.json();
  log('invalid upload response', { status: badRes.status, body: badJson });
  if (badRes.status < 400) fail('invalid upload should have returned 4xx');
  if (badJson.ok !== false) fail('invalid upload body should have ok=false');

  const metaAfterBad = await (await fetch(BASE + '/api/nba/correlations/meta')).json();
  if (metaAfterBad.row_count !== up2.row_count) {
    fail('invalid upload changed existing data (row_count drifted)');
  }
  log('meta preserved after invalid upload', metaAfterBad);

  // 7. Rollback: should restore v1.
  const rb = await (await fetch(BASE + '/api/nba/correlations/rollback', { method: 'POST' })).json();
  log('rollback', rb);
  if (!rb.ok) fail('rollback not ok');

  const metaAfterRb = await (await fetch(BASE + '/api/nba/correlations/meta')).json();
  if (metaAfterRb.row_count !== up1.row_count) {
    fail('rollback did not restore v1 row_count (got ' + metaAfterRb.row_count + ', want ' + up1.row_count + ')');
  }
  log('meta after rollback', metaAfterRb);

  console.log('\nALL CHECKS PASSED');
}

main().catch(e => { console.error(e); process.exit(1); });
