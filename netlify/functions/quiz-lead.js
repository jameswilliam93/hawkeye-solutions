// Receives a Bid Readiness Quiz submission from a tender detail page and
// writes it into the Hawkeye CRM (Supabase) as a contact + logged activity.
//
// Runs server-side only. Uses the Supabase SERVICE ROLE key (never the
// anon key) so it can check for an existing contact by email before
// deciding whether to create a new one or just log against the existing
// one -- that lookup is why this has to be a function and can't be done
// straight from the browser with the public anon key.
//
// Required Netlify environment variables (Site settings -> Environment
// variables in the Netlify dashboard -- never commit these):
//   SUPABASE_URL              e.g. https://xxxxx.supabase.co
//   SUPABASE_SERVICE_ROLE_KEY the *service_role* key from Supabase's API
//                              settings, NOT the anon/public key.

const QUESTIONS = {
  1: { text: "Delivered a similar contract before?", options: { 3: "Yes, multiple times", 2: "Once or twice", 0: "Not yet" } },
  2: { text: "Could you deliver within the timeframe?", options: { 3: "Yes, comfortably", 2: "It'd be tight", 0: "Unsure" } },
  3: { text: "Written a public-sector bid before?", options: { 3: "Yes, and won", 2: "Yes, not won yet", 0: "Never" } },
  4: { text: "Time to dedicate before the deadline?", options: { 3: "Plenty", 2: "Some, but tight", 0: "Very little" } },
};

function isValidEmail(email) {
  return typeof email === "string" && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function buildNote(body) {
  const lines = [];
  lines.push(`Bid Readiness Quiz -- ${body.tenderTitle || "a tender"}`);
  lines.push(`Score: ${body.score ?? "?"}/12 (${body.scoreTier || "unknown"})`);
  lines.push(`Recommended: ${body.recommendedService || "unknown"}`);
  lines.push("");
  if (Array.isArray(body.answers)) {
    body.answers.forEach((a) => {
      const q = QUESTIONS[a.step];
      if (!q) return;
      const label = q.options[a.points] ?? String(a.points);
      lines.push(`${q.text} -> ${label}`);
    });
    lines.push("");
  }
  if (body.sector) lines.push(`Sector: ${body.sector}`);
  if (body.value) lines.push(`Value: ${body.value}`);
  if (body.tenderUrl) lines.push(`Page: ${body.tenderUrl}`);
  return lines.join("\n");
}

exports.handler = async (event) => {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: "Method not allowed" };
  }

  const SUPABASE_URL = process.env.SUPABASE_URL;
  const SERVICE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!SUPABASE_URL || !SERVICE_KEY) {
    console.error("quiz-lead: missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY env vars");
    return { statusCode: 500, body: JSON.stringify({ ok: false, error: "server not configured" }) };
  }

  let body;
  try {
    body = JSON.parse(event.body || "{}");
  } catch {
    return { statusCode: 400, body: JSON.stringify({ ok: false, error: "invalid JSON" }) };
  }

  // Honeypot -- a real visitor never fills this in
  if (body.botField) {
    return { statusCode: 200, body: JSON.stringify({ ok: true }) };
  }

  if (!isValidEmail(body.email)) {
    return { statusCode: 400, body: JSON.stringify({ ok: false, error: "invalid email" }) };
  }
  if (!body.tenderTitle || !body.tenderSlug) {
    return { statusCode: 400, body: JSON.stringify({ ok: false, error: "missing tender context" }) };
  }

  const email = String(body.email).trim().toLowerCase();
  const sbHeaders = {
    apikey: SERVICE_KEY,
    Authorization: `Bearer ${SERVICE_KEY}`,
    "Content-Type": "application/json",
  };

  try {
    // 1. Look for an existing contact by email so the same person filling
    //    the quiz on different tenders doesn't create duplicate contacts.
    const lookupRes = await fetch(
      `${SUPABASE_URL}/rest/v1/contacts?email=eq.${encodeURIComponent(email)}&select=id&limit=1`,
      { headers: sbHeaders }
    );
    if (!lookupRes.ok) throw new Error(`contact lookup failed: ${lookupRes.status}`);
    const existing = await lookupRes.json();

    let contactId;
    if (Array.isArray(existing) && existing.length > 0) {
      contactId = existing[0].id;
    } else {
      const rawValue = typeof body.rawValue === "number" ? body.rawValue : null;
      const insertRes = await fetch(`${SUPABASE_URL}/rest/v1/contacts`, {
        method: "POST",
        headers: { ...sbHeaders, Prefer: "return=representation" },
        body: JSON.stringify([
          {
            email,
            source: "Bid Readiness Quiz",
            stage: "New Lead",
            assigned_to: "You",
            tags: ["Quiz", body.scoreTier].filter(Boolean),
            estimated_value: rawValue,
            industry: body.sector || null,
            notes: `First contact via the Bid Readiness Quiz, on "${body.tenderTitle}".`,
          },
        ]),
      });
      if (!insertRes.ok) throw new Error(`contact insert failed: ${insertRes.status}`);
      const inserted = await insertRes.json();
      contactId = inserted[0].id;
    }

    // 2. Log the quiz result as an activity so the context isn't lost,
    //    whether this was a brand-new contact or an existing one.
    const activityRes = await fetch(`${SUPABASE_URL}/rest/v1/activities`, {
      method: "POST",
      headers: sbHeaders,
      body: JSON.stringify([
        {
          contact_id: contactId,
          type: "Note",
          note: buildNote(body),
          date: new Date().toISOString().slice(0, 10),
          by: "Website Quiz",
        },
      ]),
    });
    if (!activityRes.ok) throw new Error(`activity insert failed: ${activityRes.status}`);

    return { statusCode: 200, body: JSON.stringify({ ok: true }) };
  } catch (err) {
    console.error("quiz-lead error:", err);
    return { statusCode: 500, body: JSON.stringify({ ok: false, error: "internal error" }) };
  }
};
