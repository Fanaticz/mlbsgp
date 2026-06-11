// Parse the text layer of a Pinnacle soccer match-page PDF ("print to PDF"
// of pinnacle.com/en/soccer/.../<match>) into structured market groups.
//
// pdf-parse hands us one text line per visual row, but the layout varies:
// sometimes "Yes & Over 2.5" and "+238" land on separate lines, sometimes the
// odds glue onto the selection ("Mexico & Over 2.5+167"), and two-way markets
// pack both sides onto one line ("Yes+162No-191"). The tokenizer below treats
// every American-odds token ([+-]ddd..) as a terminator: whatever text
// accumulated since the previous odds token (possibly across lines) is that
// selection's name.

// American odds are always 3-5 digits with a mandatory sign and no space
// after the sign — so "0 - 1" (range selection) and "(Mexico -5)" never
// false-positive.
const ODDS_RE = /([+-]\d{3,5})(?!\d)/g;

// Market groups we extract, keyed by canonical id. Each Pinnacle header line
// must match `re` exactly (full-match variants only; "1st Half" headers fail
// these anchored regexes on purpose). Groups marked sgp:true are mutually
// exclusive + exhaustive partitions, so a straight multiplicative devig of
// the group yields fair probabilities for every selection.
const MARKET_DEFS = [
  { key: 'btts_total',    label: 'Both Teams To Score / Total Goals', sgp: true,  re: /^Both Teams To Score\/Total Goals$/i },
  { key: 'btts_winner',   label: 'Both Teams To Score / Winner',      sgp: true,  re: /^Both Teams To Score\/Winner$/i },
  { key: 'winner_total',  label: 'Winner / Total Goals',              sgp: true,  re: /^Winner\/Total Goals$/i },
  { key: 'ht_ft',         label: 'Half-Time / Full-Time',             sgp: true,  re: /^Half-Time\/Full-Time$/i },
  { key: 'oddeven_total', label: 'Odd/Even / Total Goals', sgp: true,  re: /^Odd\/Even ?\/ ?Total Goals$/i },
  { key: 'btts',          label: 'Both Teams To Score',               sgp: false, re: /^Both Teams To Score\?$/i },
  { key: 'double_chance', label: 'Double Chance',                     sgp: false, re: /^Double Chance$/i },
  { key: 'draw_no_bet',   label: 'Draw No Bet',                       sgp: false, re: /^Draw No Bet$/i },
];

// Any line that looks like a Pinnacle market header — including ones we don't
// track (correct score, exact totals, handicaps...) — must close the previous
// group so foreign selections don't bleed in.
const ANY_HEADER_RE = /^(Both Teams To Score|Correct Score|Double Chance|Draw No Bet|Half-Time\/Full-Time|First Team To Score|Either Team To Score|Exact Total Goals|Winner\/Total Goals|Winning Margin|Total Goals|Odd\/Even|3-Way Handicap|.+ To Score\? ?(1st Half)?$|.+ Goals( 1st Half)?$|.+ Odd\/Even$|.+ To Win to Nil\?|Either Team To (Take a Penalty Kick|Get a Red Card))/i;

// Page furniture: nav, bet slip, cookie banner, footer, page headers/URLs.
const NOISE_RE = /^(Hide All|To place a Multiple bet|bets on your Bet Slip|Single bet\.|There are no bets|Click the odds|SINGLES$|MULTIPLES$|TEASERS|Welcome to Pinnacle|ACCEPT$|JOIN$|LOG IN|Forgot email|Email or ClientID|SPORTS BETTING|CASINO$|LIVE CASINO|VIRTUAL SPORTS|BETTING RESOURCES|LIVE CENTRE|Search$|Help$|American Odds|EN$|FAVOURITES|Log in or Join|favourites\.|TOP SPORTS|A-Z SPORTS|BET SLIP|Sports Betting$|\w+ betting$|About Pinnacle|Corporate$|Press$|Affiliates$|Why Pinnacle|Policies$|Responsible Gaming|Terms & Conditions|Privacy Policy|Cookie Policy|Help & Support|Contact us|Betting Rules|Bets Offered|Sitemap$|Payment Options|Social$|Gambling can be addictive|Impyrial Holdings|Pinnacle\.com operates|and is supervised|games of chance|Online sports betting|Pinnacle, Pinnacle Sports|the website|written consent|v\.\d|https?:\/\/|\d+\/\d+\/\d+, |\(GMT)/i;

function parsePinnacleSoccerText(text) {
  const lines = String(text || '')
    // Icon-font glyphs (Unicode private use area) prefix some rows; strip
    // them before line classification.
    .replace(/[\uE000-\uF8FF]/g, '')
    .replace(/\u00A0/g, ' ')
    .split(/\r?\n/)
    .map(l => l.trim())
    .filter(Boolean);

  // Kickoff line ("Thursday, June 11, 2026 at 14:00") is followed by the two
  // team lines at the top of the printed page.
  let home = null, away = null, kickoff = null, league = null;
  const kickIdx = lines.findIndex(l => /^\w+day, .+ at \d{1,2}:\d{2}$/.test(l));
  if (kickIdx >= 0) {
    kickoff = lines[kickIdx].replace(/^\w+day, /, '');
    if (lines.length > kickIdx + 2) { home = lines[kickIdx + 1]; away = lines[kickIdx + 2]; }
  }
  for (const line of lines) {
    if (!league && /World Cup/i.test(line)) league = 'FIFA - World Cup';
  }
  if (!home || !away) {
    // Fallback: page-footer title "Mexico vs South Africa Betting Odds | ..."
    for (const line of lines) {
      const m = line.match(/([A-Za-z .'À-ſ-]+?) vs\.? ([A-Za-z .'À-ſ-]+?) Betting Odds/);
      if (m) { home = home || m[1].trim(); away = away || m[2].trim(); break; }
    }
  }

  const markets = {};   // key -> [{ name, odds }]
  let current = null;   // active tracked market key
  let pending = '';     // selection text awaiting its odds token

  for (const line of lines) {
    if (NOISE_RE.test(line)) { pending = ''; continue; }

    ODDS_RE.lastIndex = 0;
    if (!ODDS_RE.test(line)) {
      const def = MARKET_DEFS.find(d => d.re.test(line));
      if (def) {
        current = def.key;
        markets[current] = markets[current] || [];
        pending = '';
        continue;
      }
      if (ANY_HEADER_RE.test(line)) { current = null; pending = ''; continue; }
      if (current) pending = pending ? pending + ' ' + line : line;
      continue;
    }

    if (!current) { pending = ''; continue; }

    let lastEnd = 0, m;
    ODDS_RE.lastIndex = 0;
    while ((m = ODDS_RE.exec(line)) !== null) {
      let name = line.slice(lastEnd, m.index).trim();
      if (pending) { name = name ? pending + ' ' + name : pending; pending = ''; }
      name = name.trim();
      if (name) markets[current].push({ name, odds: parseInt(m[1], 10) });
      lastEnd = m.index + m[1].length;
    }
    const tail = line.slice(lastEnd).trim();
    if (tail) pending = tail;
  }

  return { home, away, league, kickoff, markets };
}

module.exports = { parsePinnacleSoccerText, MARKET_DEFS };
