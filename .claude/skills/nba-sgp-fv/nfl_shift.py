#!/usr/bin/env python3
"""NFL yardage legs away from the main line: a gamma curve through the main
line's fair value, read off at the slip's line.

  python3 nfl_shift.py yds 54.5 0.50 99.5   # P(100+ receiving yards) from a 54.5 main at 50%

Yards are skewed with a floor at zero, so a bell curve fitted through the main
line runs far short above it. Study of 11-11:
- Game logs (5,000 receiving, 1,400 rushing player-games, prior games only): at
  twice the main line the normal gave 60-71% of the real hit rate and at three
  times 29-38%; a gamma gave 95-126%.
- DK's and FanDuel's ladders (4,000 one-way prices, 14 games): the spread the
  books imply near the main line is the same from player to player once the
  main line's level is known (CV below, quartiles within about 0.05). A gamma
  with it sits under both books' prices by their margin over the whole ladder
  (5-7% near the main, 0-25% at 1.8x and beyond); the normal is off 2x to 50x.
The gamma runs a little high far out (book price over fair of 1.00-1.07 on DK
beyond 1.8x, where its margin should be 13%), so above the main line a leg
keeps 15% of the normal. Passing yards are close to symmetric (CV about 0.3)
and the same curve fits.
"""
import math
import sys

# (main line, CV = SD / mean) knots, from the books' own ladders
CV = {"yds": [(8, 1.07), (20, 0.87), (30, 0.78), (42, 0.68), (60, 0.57), (85, 0.52)],
      "ryds": [(10, 0.93), (27, 0.71), (42, 0.62), (60, 0.54), (85, 0.46)],
      "pyds": [(180, 0.34), (215, 0.31), (245, 0.28), (280, 0.27)]}
UP_NORMAL = 0.15   # the normal's share of a leg above the main line


def ncdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


def nppf(p):
    lo, hi = -10.0, 10.0
    for _ in range(60):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if ncdf(m) < p else (lo, m)
    return m


def gammp(a, x):
    """Regularized lower incomplete gamma P(a, x)."""
    if x <= 0:
        return 0.0
    gl = math.lgamma(a)
    if x < a + 1:
        ap, s, dl = a, 1 / a, 1 / a
        for _ in range(500):
            ap += 1
            dl *= x / ap
            s += dl
            if abs(dl) < abs(s) * 1e-12:
                break
        return s * math.exp(-x + a * math.log(x) - gl)
    b, c = x + 1 - a, 1e300
    d = 1 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        de = d * c
        h *= de
        if abs(de - 1) < 1e-12:
            break
    return 1 - math.exp(-x + a * math.log(x) - gl) * h


def cv_at(stat, main):
    knots = CV[stat]
    if main <= knots[0][0]:
        return knots[0][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if main <= x1:
            return y0 + (y1 - y0) * (main - x0) / (x1 - x0)
    return knots[-1][1]


def over(stat, main, p_main, line):
    """P(stat > line), given P(stat > main) = p_main."""
    if line == main:
        return p_main
    cv = cv_at(stat, main)
    k = 1 / (cv * cv)
    lo, hi = 0.01, 5000.0
    for _ in range(70):   # the gamma's scale that puts p_main above the main line
        th = (lo + hi) / 2
        lo, hi = (th, hi) if 1 - gammp(k, main / th) < p_main else (lo, th)
    g = 1 - gammp(k, line / th)
    if line < main:
        return g
    sd = cv * main
    n = 1 - ncdf((line - (main - sd * nppf(1 - p_main))) / sd)
    return (1 - UP_NORMAL) * g + UP_NORMAL * n


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit(__doc__)
    s, m, p, ln = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
    q = over(s, m, p, ln)
    print(f"{s} over {ln:g}: {q:.1%} ({'+' if q < .5 else ''}{round(100 * (1 - q) / q) if q < .5 else round(-100 * q / (1 - q))})"
          f"  from {m:g} at {p:.1%}, CV {cv_at(s, m):.2f}")
