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
    return s.replace(/\s+/g, ' ').trim();
  }

  function foldKey(name) {
    return foldAscii(name).toLowerCase();
  }

  return { foldAscii: foldAscii, foldKey: foldKey };
}));
