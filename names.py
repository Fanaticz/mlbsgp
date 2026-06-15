#!/usr/bin/env python3
"""Name normalization + matching shared across the Long Ball pipeline.

The three data sources spell players differently:

  * Baseball Savant CSVs ...... "Last, First" with accents/suffixes  -> "Suárez, Eugenio"
  * Savant HR leaderboard ..... same "Last, First"                   -> "Acuña Jr., Ronald"
  * DraftKings odds ........... "First Last", usually no accents      -> "Eugenio Suarez"

Everything in the model is keyed on the DISPLAY form ("First Last"). To JOIN a
DK odds name to a Savant distance profile we compare an accent-/suffix-stripped
KEY so "Eugenio Suarez" == "Suárez, Eugenio". `norm_key` builds that key; the
helpers below convert between the two display conventions.
"""

import re
import unicodedata

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def to_display(name: str) -> str:
    """'Kurtz, Nick' -> 'Nick Kurtz'. Pass-through if already 'First Last'."""
    if "," in name:
        last, first = [p.strip() for p in name.split(",", 1)]
        return f"{first} {last}".strip()
    return name.strip()


def strip_accents(s: str) -> str:
    """'Suárez' -> 'Suarez'. Decompose then drop combining marks."""
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def norm_key(name: str) -> str:
    """Accent-/suffix-/punctuation-insensitive join key.

    Order-insensitive too: 'Suárez, Eugenio' and 'Eugenio Suarez' both ->
    'eugenio suarez'. Drops Jr./Sr./II/III so 'Acuña Jr., Ronald' and
    'Ronald Acuna' match. Sorted tokens guard against either input order."""
    n = to_display(name)
    n = strip_accents(n).lower()
    n = re.sub(r"\(.*?\)", " ", n)           # drop DK team qualifiers e.g. "(LAD)"
    n = re.sub(r"[.\-']", " ", n)            # punctuation -> space
    toks = [t for t in n.split() if t and t not in _SUFFIXES]
    toks.sort()                               # order-independent
    return " ".join(toks)


def build_key_index(names) -> dict:
    """Map norm_key -> original display name for a collection of names."""
    idx = {}
    for n in names:
        idx[norm_key(n)] = n
    return idx


def match(name: str, key_index: dict, fuzzy: bool = True):
    """Resolve `name` against a {norm_key: display} index.

    Exact key match first; optional last-name + first-initial fuzzy fallback
    (handles 'CJ Abrams' vs 'C. J. Abrams', 'Mike Trout' vs 'Michael Trout'
    only when unambiguous). Returns the matched display name or None."""
    k = norm_key(name)
    if k in key_index:
        return key_index[k]
    if not fuzzy:
        return None
    toks = k.split()
    if not toks:
        return None
    # last token is the (sorted) ... not reliable; rebuild from display order
    disp = strip_accents(to_display(name)).lower()
    disp = re.sub(r"\(.*?\)", " ", disp)
    disp = re.sub(r"[.\-']", " ", disp)
    parts = [t for t in disp.split() if t not in _SUFFIXES]
    if len(parts) < 2:
        return None
    first_init, last = parts[0][0], parts[-1]
    cands = []
    for key, display in key_index.items():
        ktoks = key.split()
        # key is sorted; check last name present + a token starting w/ first init
        if last in ktoks and any(t[0] == first_init for t in ktoks if t != last):
            cands.append(display)
    return cands[0] if len(cands) == 1 else None
