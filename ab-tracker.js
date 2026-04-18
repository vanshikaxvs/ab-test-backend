/**
 * ab-tracker.js
 * ─────────────────────────────────────────────────────────────────
 * Drop this <script> into BOTH your landing page variants (A & B).
 * It automatically:
 *   1. Logs the visit and receives the assigned variant (A or B)
 *   2. Renders the correct variant HTML
 *   3. Tracks session duration
 *   4. Sends a conversion event when the CTA button is clicked
 *   5. Records colour preference when the user picks one
 *   6. Logs bounces on page exit
 *
 * USAGE in your HTML:
 *   <script src="ab-tracker.js" data-api="http://localhost:5000" data-cta="signup-btn"></script>
 *
 * data-api  → URL of your Flask backend (change to your server)
 * data-cta  → ID of your Call-To-Action button
 */

(function () {
  const script   = document.currentScript;
  const API_BASE = (script && script.dataset.api) || "http://localhost:5000";
  const CTA_ID   = (script && script.dataset.cta) || "cta-btn";

  let visitId   = null;
  let variant   = null;
  let startTime = Date.now();
  let colorPref = null;

  // ── 1. LOG VISIT ────────────────────────────────────────────────
  async function logVisit() {
    try {
      const res = await fetch(`${API_BASE}/api/visit`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          device:  /Mobi|Android/i.test(navigator.userAgent) ? "mobile" : "desktop",
          country: Intl.DateTimeFormat().resolvedOptions().timeZone || "unknown"
        })
      });
      const data = await res.json();
      visitId  = data.visit_id;
      variant  = data.variant;
      sessionStorage.setItem("ab_visit_id", visitId);
      sessionStorage.setItem("ab_variant",  variant);
      applyVariant(variant);
    } catch (e) {
      console.warn("[AB] Could not log visit:", e);
    }
  }

  // ── 2. APPLY VARIANT (show A or B content) ──────────────────────
  function applyVariant(v) {
    document.querySelectorAll("[data-variant]").forEach(el => {
      el.style.display = (el.dataset.variant === v) ? "" : "none";
    });
    document.body.dataset.abVariant = v;
    console.log(`[AB] Assigned variant: ${v}`);
  }

  // ── 3. LOG CONVERSION ───────────────────────────────────────────
  async function logConversion() {
    if (!visitId) return;
    const dur = Math.round((Date.now() - startTime) / 1000);
    try {
      await fetch(`${API_BASE}/api/convert`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ visit_id: visitId, session_duration: dur, color_pref: colorPref })
      });
      console.log("[AB] Conversion logged");
    } catch (e) {
      console.warn("[AB] Could not log conversion:", e);
    }
  }

  // ── 4. LOG BOUNCE ───────────────────────────────────────────────
  function logBounce() {
    if (!visitId) return;
    const dur = Math.round((Date.now() - startTime) / 1000);
    navigator.sendBeacon(`${API_BASE}/api/bounce`,
      JSON.stringify({ visit_id: visitId, session_duration: dur })
    );
  }

  // ── 5. COLOUR PREFERENCE TRACKING ──────────────────────────────
  // Call this from your colour picker UI:
  //   ABTracker.setColor("#3B82F6");
  function setColor(hex) {
    colorPref = hex;
    if (visitId && variant) {
      fetch(`${API_BASE}/api/color_vote`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ variant, color: hex })
      }).catch(() => {});
    }
  }

  // ── INIT ─────────────────────────────────────────────────────────
  window.ABTracker = { setColor, logConversion, getVariant: () => variant };

  // Resume session if page refreshed
  const storedId = sessionStorage.getItem("ab_visit_id");
  if (storedId) {
    visitId = storedId;
    variant = sessionStorage.getItem("ab_variant");
    applyVariant(variant);
  } else {
    logVisit();
  }

  // Hook CTA button
  document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById(CTA_ID);
    if (btn) btn.addEventListener("click", logConversion);
  });

  // Log bounce on page exit
  window.addEventListener("pagehide", logBounce);
  window.addEventListener("beforeunload", logBounce);
})();