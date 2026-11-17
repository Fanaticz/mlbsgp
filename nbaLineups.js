// NBA starting lineups and injury statuses, read off Rotowire's daily lineups
// page (rotowire.com/basketball/nba-lineups.php; ?date=tomorrow for the next
// day). For each game and team: whether the five are confirmed or expected,
// the five starters, and the "may not play" list with each man's tag (Prob,
// Ques, Doubt, Out, OFS) and Rotowire's own chance that he plays.
//
// Used by /api/nba/lineups for the first-dunk page (public/nba_dunk.html).
'use strict';

// Rotowire's team codes -> ESPN's (the ones the first-dunk data is keyed by).
const ABBR = { NYK: 'NY', SAS: 'SA', UTA: 'UTAH', GSW: 'GS', NOP: 'NO', WAS: 'WSH', PHO: 'PHX', BRK: 'BKN', CHO: 'CHA' };
// A tag's chance of playing when Rotowire gives none of its own.
const TAG_P = { out: 0, ofs: 0, doubt: 0.15, ques: 0.5, gtd: 0.5, prob: 0.85 };

function text(s) {
  return String(s || '').replace(/<[^>]*>/g, ' ').replace(/&amp;/g, '&').replace(/&#0?39;|&apos;/g, "'")
    .replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
}

function parsePlayers(html) {
  const out = [];
  const re = /<li class="lineup__player([^"]*)"[^>]*>([\s\S]*?)<\/li>/g;
  let m;
  while ((m = re.exec(html))) {
    const cls = m[1], body = m[2];
    const a = body.match(/<a[^>]*title="([^"]*)"[^>]*>/);
    if (!a) continue;
    const pos = (body.match(/class="lineup__pos"[^>]*>([^<]*)</) || [])[1] || '';
    const tag = text((body.match(/class="lineup__inj"[^>]*>([^<]*)</) || [])[1] || '').toLowerCase();
    const pct = (cls.match(/is-pct-play-(\d+)/) || [])[1];
    let play = 1;
    if (tag === 'out' || tag === 'ofs') play = 0;
    else if (pct != null && Number(pct) < 100) play = Number(pct) / 100;
    else if (tag && TAG_P[tag] != null) play = TAG_P[tag];
    out.push({ name: text(a[1]), pos: text(pos), tag, play });
  }
  return out;
}

function parseList(html) {
  const status = /lineup__status[^"]*is-confirmed/.test(html) ? 'confirmed'
    : /lineup__status[^"]*is-expected/.test(html) ? 'expected' : 'unknown';
  // the five, then a "MAY NOT PLAY" title, then the injury list
  const cut = html.search(/<li class="lineup__title/);
  const starters = parsePlayers(cut < 0 ? html : html.slice(0, cut)).slice(0, 5);
  const others = cut < 0 ? [] : parsePlayers(html.slice(cut));
  if (status === 'confirmed') starters.forEach((p) => { p.play = 1; });
  return { status, starters, others };
}

const MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];

// "Starting lineups for November 16, 2026" -> "20261116" ('' when the page doesn't say)
function pageDate(html) {
  const m = String(html || '').match(/Starting lineups for\s+([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})/);
  const mo = m ? MONTHS.indexOf(m[1].toLowerCase()) : -1;
  return mo < 0 ? '' : m[3] + String(mo + 1).padStart(2, '0') + String(m[2]).padStart(2, '0');
}

// The page's games: [{ date, away, home, time, teams: { <ESPN abbr>: { status, starters, others } } }]
function parse(html) {
  const games = [];
  const date = pageDate(html);
  const blocks = String(html || '').split(/<div class="lineup is-nba[^"]*"/).slice(1);
  for (const b of blocks) {
    const abbrs = [];
    const re = /class="lineup__abbr">([^<]*)</g;
    let m;
    while ((m = re.exec(b))) abbrs.push(text(m[1]).toUpperCase());
    if (abbrs.length < 2) continue;
    const visit = (b.match(/<ul class="lineup__list is-visit">([\s\S]*?)<\/ul>/) || [])[1];
    const home = (b.match(/<ul class="lineup__list is-home">([\s\S]*?)<\/ul>/) || [])[1];
    if (!visit || !home) continue;
    const away = ABBR[abbrs[0]] || abbrs[0], hm = ABBR[abbrs[1]] || abbrs[1];
    games.push({
      date, away, home: hm, time: text((b.match(/class="lineup__time">([^<]*)</) || [])[1] || ''),
      teams: { [away]: parseList(visit), [hm]: parseList(home) },
    });
  }
  return games;
}

const URL_TODAY = 'https://www.rotowire.com/basketball/nba-lineups.php';
const UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36';

async function fetchDay(tomorrow) {
  const r = await fetch(URL_TODAY + (tomorrow ? '?date=tomorrow' : ''), { headers: { 'User-Agent': UA, Accept: 'text/html' } });
  if (!r.ok) throw new Error(`Rotowire answered ${r.status}`);
  return parse(await r.text());
}

// Both days in one list; each game carries the date its page is for.
async function fetchLineups() {
  const [a, b] = await Promise.allSettled([fetchDay(false), fetchDay(true)]);
  if (a.status === 'rejected' && b.status === 'rejected') throw a.reason;
  return {
    source: 'rotowire',
    games: [].concat(a.status === 'fulfilled' ? a.value : [], b.status === 'fulfilled' ? b.value : []),
  };
}

module.exports = { parse, pageDate, fetchLineups, ABBR, TAG_P };
