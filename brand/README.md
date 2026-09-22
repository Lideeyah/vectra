# Vectra — mark, wordmark, lockup

Generated from the app, not drawn alongside it. `web/app/page.tsx` `Mark()` and
`Header()` are the source; these files are a build of them. The viewBox units
**are** the app's units, so any file here can be diffed against the component.

Regenerate rather than hand-edit. A logo that has been touched in two places is
a logo with two versions.

## The mark

A hairline circle in bone. Inside it, a solid cyan disc offset from centre.
That offset is drift, and it is the whole product in one shape — the distance
between where a basket is and where it should be. Never centre the disc.

```
circle  cx 11   cy 11    r 10   stroke bone  stroke-width 1
disc    cx 11.8 cy 10.4  r 5.4  fill cyan
```

The offset is `hypot(0.8, 0.6)` = **1.0 = 10% of the radius**, at 36.87°.

> **Known divergence.** `DESIGN.md` §7 says "approximately eight percent". The
> app ships ten. These assets follow the app, because the app is what anyone has
> actually looked at. Decide which is canonical and make the other match — don't
> leave both.

## The wordmark

"Vectra", title case. Bricolage Grotesque **opsz 17 / wght 600**, tracking
**−0.01em**, converted to outlines.

Two things that are easy to get wrong:

- **It is not uppercase and not loosely tracked.** The app sets it at −0.01em,
  tighter than default. Section labels in the UI are caps at +0.08em; the
  wordmark is not one of those.
- **`opsz` is pinned at 17.** Bricolage Grotesque is an optical-size variable
  font, and CSS optical sizing is on by default, so the app's glyphs at 17px are
  the opsz=17 instance. The opsz=96 shapes are ~9% narrower and are a different
  wordmark. Pinning it keeps one fixed shape at every size.

Outlined rather than left as `<text>`: a wordmark that depends on a webfont
renders as Helvetica the first time someone opens it in Figma, in an email, or
offline, and a logo that changes shape by context is not a logo. The cost is
that these files no longer track the typeface — regenerate if it ever moves.

## Lockup

Mark, 12-unit gap, wordmark at 17. Cap height centred on the mark's axis.
Measured against the running app: width within **0.34%**, baseline within
**0.07%**.

## Files

| | |
|---|---|
| `vectra-icon.svg` | mark on ground — the primary |
| `vectra-icon-on-light.svg` | ring in ground, for bone backgrounds |
| `vectra-icon-mono.svg` | `currentColor`; the offset carries the meaning without the fill |
| `vectra-favicon.svg` | ground plate, stroke thickened — 1/22 of a 16px tab icon is under half a pixel and vanishes. Offset untouched. |
| `vectra-lockup*.svg` | horizontal, three colourways |
| `vectra-lockup-stacked.svg` | mark over wordmark |
| `vectra-wordmark*.svg` | wordmark alone |
| `png/` | raster, transparent, for anything that cannot take SVG |
| `vectra-brand-sheet.png` | contact sheet, every variant at every size |

## Colour

Five values, each with one job. No sixth colour, per `DESIGN.md` §2.

```
--ground  #0e1620
--bone    #e8e4da
--cyan    #00d4c4   agency, live state, anything actionable
--orange  #e4572e   out of tolerance: normal, expected, working
--red     #ff3b30   failure
```

The mark uses bone and cyan only. Orange and red never appear in it — they mean
specific things about a running basket, and a logo is not making that claim.

## Forbidden

Rounded corners anywhere near it. Gradient fills. Drop shadows. A centred disc.
Rotating, pulsing or spinning it. Any colour outside the five above.

Where the mark animates in product, the disc eases to centre on a completed
rebalance over ~600ms and drifts back off centre as the position drifts — the
same convergence easing as everything else. **Never animate a favicon.**

## Regenerating

Needs `fonttools` and the Bricolage Grotesque variable font:

```bash
curl -fsSL "https://github.com/google/fonts/raw/main/ofl/bricolagegrotesque/BricolageGrotesque%5Bopsz,wdth,wght%5D.ttf" -o /tmp/bg-var.ttf
python3 -c "
from fontTools.ttLib import TTFont; from fontTools.varLib import instancer
f=TTFont('/tmp/bg-var.ttf')
instancer.instantiateVariableFont(f,{'opsz':17,'wght':600,'wdth':100},inplace=True)
f.save('/tmp/bricolage-17-600.ttf')"
python3 build.py
```
