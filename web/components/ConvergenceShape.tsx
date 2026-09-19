"use client";

/**
 * The unconnected state renders the product with its data missing, rather than
 * a marketing page or an empty dashboard. A judge who never connects a wallet
 * still sees what Vectra is.
 *
 * Nothing here is a placeholder VALUE — every figure is an em-dash. The shape
 * is real, the numbers are absent and say so, because a fabricated state that
 * gets screenshotted by accident is disqualifying.
 */
export function ConvergenceShape() {
  return (
    <section style={{ marginBottom: 40, opacity: 0.55 }} aria-hidden>
      <div className="dim" style={{ fontSize: 12, letterSpacing: "0.08em", marginBottom: 12 }}>
        TOTAL DISTANCE FROM TARGET
      </div>

      <div style={{ display: "flex", alignItems: "baseline", gap: 16, flexWrap: "wrap" }}>
        <div
          className="mono faint"
          style={{ fontSize: "clamp(48px, 12vw, 96px)", lineHeight: 1 }}
        >
          —<span style={{ fontSize: "0.35em", marginLeft: 6 }}>%</span>
        </div>
        <div className="faint" style={{ fontSize: 13, maxWidth: 280 }}>
          connect a wallet to read your position from chain
        </div>
      </div>

      <hr className="rule" style={{ margin: "32px 0 0" }} />

      {[0, 1, 2].map((i) => (
        <div key={i} style={{ padding: "18px 0", borderBottom: "1px solid var(--bone-12)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
            <span className="mono faint" style={{ fontSize: 15 }}>—</span>
            <span className="mono faint" style={{ fontSize: 13 }}>—</span>
          </div>
          {/* Target is the hairline outline. With no position there is no fill. */}
          <div className="bar-track" />
          <div
            className="mono faint"
            style={{ display: "flex", justifyContent: "space-between", marginTop: 8, fontSize: 12 }}
          >
            <span>actual —</span>
            <span>target —</span>
            <span>gap —</span>
          </div>
        </div>
      ))}
    </section>
  );
}
