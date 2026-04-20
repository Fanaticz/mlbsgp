/* nameNormalize.js — ASCII-folding helpers for player-name lookups.
   UMD: works as <script> in browser (window.nameNormalize) or
   require() in Node (server.js + smoke drivers).

   Why this exists: TEAMMATE_DATA was built from ASCII-only sources, but
   the MLB Stats API (our /api/lineups source) returns diacritic forms
   ("Andrés Giménez"). FV-sheet OCR returns ASCII ("Andres Gimenez").
   That three-way disagreement broke the player-name join in the
   2026-04-20 live test (0 candidates surfaced). foldAscii / foldKey
   give us one canonical form usable at every join point.

   Strategy: NFKD-decompose, strip combining marks (U+0300..U+036F),
   collapse whitespace, trim. foldKey adds lowercase for case-insensitive
   equality.

   Idempotent — calling foldAscii on already-folded text is a no-op.
   Safe to call defensively at lookup sites in addition to the boundary
   normalizations. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.nameNormalize = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {

  function foldAscii(name) {
    if (name == null) return '';
    var s = String(name);
    /* String.prototype.normalize is in every current browser + Node 14+.
       Defensive guard for ancient engines just falls back to the raw
       string — names without diacritics still match correctly. */
    if (typeof s.normalize === 'function') {
      s = s.normalize('NFKD').replace(/[\u0300-\u036f]/g, '');
    }
    /* Replace any non-alphanumeric, non-whitespace character with a space
       BEFORE collapsing whitespace. Motivating cases (all observed live
       against tonight's slate on 2026-04-20):
         - "Logan O'Hoppe" straight apostrophe U+0027
         - "Logan O\u2019Hoppe"  curly apostrophe U+2019 (MLB Stats API uses this sometimes)
         - "Isiah Kiner-Falefa" hyphen vs space variants
         - "J.T. Realmuto"      periods
         - "Ke'Bryan Hayes", "Travis d'Arnaud"
       All of these fold to a single canonical form (space between tokens),
       which means straight-vs-curly-apostrophe and hyphen-vs-space
       mismatches across OCR, MLB API, and TEAMMATE_DATA all collapse at
       every join site. Display names in lineup.displayName / player.batter
       are preserved separately for UI; this fold is strictly for keys. */
    s = s.replace(/[^A-Za-z0-9\s]/g, ' ');
    return s.replace(/\s+/g, ' ').trim();
  }

  function foldKey(name) {
    return foldAscii(name).toLowerCase();
  }

  return { foldAscii: foldAscii, foldKey: foldKey };
}));
