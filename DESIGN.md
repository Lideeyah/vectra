# Vectra — Design System

Settled before any interface code. Nothing here is a suggestion.

---

## 1. THE ORGANISING IDEA

Vectra's entire job is the distance between where a portfolio is and where it should be. So the design primitive is a pair: every quantity on screen appears twice, target and actual, with the offset between them carrying the information.

Target is always a hairline outline. Actual is always a solid fill. Drift is read by looking, before any number is read.

The interface is an instrument, not a dashboard.

---

## 2. COLOUR

Five values, each with exactly one job. No sixth colour is introduced for any reason.

**Ground** `#0E1620`. A deep blue-cast near-black. Warm enough not to read as a terminal, clearly blue rather than grey.

**Bone** `#E8E4DA` for all text and structure. Never pure white. Five weights: 100, 60, 30, 12 and 6 percent.

**Cyan** `#00D4C4` means agency. Primary buttons as solid fill with ground as the label. The actual position line. Live state. Anything the user acts on.

**Orange** `#E4572E` means out of tolerance. Drift beyond band, rebalance in flight, cap approaching, activation window pause. These are normal, expected, healthy states of a working product, not errors.

**Red** `#FF3B30` means failure. A leg reverted, keeper stale, allowance insufficient, mint state unreadable, mandate expired unintentionally. States where the product is not doing what the user believes it is doing.

The distinction that keeps orange and red apart: orange means the system is working on it, red means the system has stopped and needs you.

Orange and red are hairline outline and text only, never a fill. One instance of each per screen, maximum. Cyan may fill.

No green up and red down. No status lights. No gradients.

---

## 3. BUTTON HIERARCHY

Primary: solid cyan fill, ground-coloured label.
Secondary: cyan hairline outline, cyan text, no fill.
Tertiary: bone text at 60 percent, no border.
Destructive: orange hairline outline, orange text, never filled.

---

## 4. TECHNIQUE

Engineering drawing. Dimension lines with tick marks, callout leaders, bracket notation for tolerance bands, numbers set against tick scales rather than inside boxes.

Hairlines at fractional opacity. Zero radius everywhere, because instruments do not have rounded corners. No cards, no shadows, no elevation, no outlined containers used decoratively.

A faint measurement grid at four to six percent opacity, visible rather than implied, and everything genuinely aligns to it.

---

## 5. TYPE

Numbers, addresses, timestamps and contract data in **JetBrains Mono**.
Everything else in **Bricolage Grotesque**.

No serif anywhere.

---

## 6. MOTION

Convergence. Values ease toward their target over roughly 600ms rather than snapping. That single behaviour is the product's argument expressed as motion.

Nothing bounces, pulses, springs or spins.

**Indeterminate waiting is not animated at all.** Convergence applies to values that have a target to ease toward. A wait has no known destination, so it is shown as a measurement rather than a motion: elapsed seconds since submission for a leg in flight, time remaining until the next scheduled run when waiting for a first cycle. Set in mono, counting, with nothing else moving.

Everything on screen is a measurement, so a wait is measured too.

---

## 7. THE MARK

The logo is the design primitive rendered directly.

A hairline circle in bone. Inside it, a solid cyan disc offset from centre by approximately eight percent of the radius. Not enough to read as an error, enough that the eye catches it.

That offset is drift, and it is the entire product in one shape.

At small sizes it reads as a target or an aperture. At large sizes the offset becomes the subject. It survives in a single colour, because the offset carries the meaning without the fill.

Where it animates, the disc eases to centre on a completed rebalance, using the same 600ms convergence easing as everything else, then drifts back off centre as the position drifts. The mark is alive in the same way the product is.

Favicon uses the static offset version. Never animate a favicon.

---

## 8. WHAT THIS SYSTEM FORBIDS

Any colour outside the five above. Rounded corners. Card containers. Drop shadows. Gradient fills. Green and red as directional indicators. Status dots. Loading spinners. Pulsing anything. Serif type. Orange or red as a fill. More than one orange or one red element on a screen at once.
