// Annotation server for the AgentHazard LLM-as-Judge agreement study (rebuttal §B).
//
//   node server.js              # blind annotation: Gemini's label is withheld
//   node server.js --review     # review mode: Gemini's original label is shown
//
// Two annotators ("a1", "a2") label the same fixed sample independently.
// Each annotation is saved to annotations_<annotator>.json (resumable).
const express = require("express");
const fs = require("fs");
const path = require("path");

const REVIEW = process.argv.includes("--review");
const PORT = process.env.PORT || 5173;
const DIR = __dirname;
const SAMPLE_PATH = path.join(DIR, "validation_sample.json");
const ANNOTATORS = ["a1", "a2"]; // two annotators

if (!fs.existsSync(SAMPLE_PATH)) {
  console.error(`\n[!] ${SAMPLE_PATH} not found.\n    Run:  uv run python evaluate/annotation/build_sample.py --n 200\n`);
  process.exit(1);
}
const SAMPLE = JSON.parse(fs.readFileSync(SAMPLE_PATH, "utf-8"));
const loadJ = (f) => (fs.existsSync(path.join(DIR, f)) ? JSON.parse(fs.readFileSync(path.join(DIR, f), "utf-8")) : {});
// the three reference judges shown in --review mode
const J_GPT54 = loadJ("gpt54_orig.json");        // gpt-5.4
const J_PRO = loadJ("gemini31pro.json");         // gemini-3.1-pro
// Gemini-3-Flash (original judge) lives in each item's _gemini

function annPath(annotator) {
  return path.join(DIR, `annotations_${annotator}.json`);
}
function loadAnn(annotator) {
  const p = annPath(annotator);
  return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, "utf-8")) : {};
}
function saveAnn(annotator, obj) {
  const p = annPath(annotator);
  const tmp = p + ".tmp";
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 2));
  fs.renameSync(tmp, p); // atomic
}

const app = express();
app.use(express.json({ limit: "20mb" }));
app.use(express.static(path.join(DIR, "public")));

// Sample (Gemini label stripped unless review mode), plus config.
app.get("/api/sample", (req, res) => {
  const items = SAMPLE.items.map((it) => {
    const o = {
      item_id: it.item_id,
      framework: it.framework,
      model: it.model,
      data_id: it.data_id,
      category: it.category,
      jailbreak_method: it.jailbreak_method,
      attack_objective: it.attack_objective,
      attack_comment: it.attack_comment,
      decomposed_query: it.decomposed_query,
      events: it.events,
    };
    if (REVIEW) {
      // all three reference judges, only exposed when launched with --review
      o._judges = {
        "Gemini-3-Flash": it._gemini || null,
        "gemini-3.1-pro": J_PRO[String(it.item_id)] || null,
        "gpt-5.4": J_GPT54[String(it.item_id)] || null,
      };
    }
    return o;
  });
  res.json({ meta: SAMPLE.meta, review: REVIEW, annotators: ANNOTATORS, items });
});

// Existing annotations for one annotator.
app.get("/api/annotations/:annotator", (req, res) => {
  const a = req.params.annotator;
  if (!ANNOTATORS.includes(a)) return res.status(400).json({ error: "unknown annotator" });
  res.json(loadAnn(a));
});

// Save one annotation.
app.post("/api/annotate", (req, res) => {
  const { annotator, item_id, harmful, note } = req.body || {};
  if (!ANNOTATORS.includes(annotator)) return res.status(400).json({ error: "unknown annotator" });
  if (item_id == null) return res.status(400).json({ error: "missing item_id" });
  const ann = loadAnn(annotator);
  ann[item_id] = {
    harmful: harmful === true || harmful === false ? harmful : null,
    note: typeof note === "string" ? note : "",
    ts: new Date().toISOString(),
  };
  saveAnn(annotator, ann);
  const labeled = Object.values(ann).filter((x) => x.harmful !== null).length;
  res.json({ ok: true, labeled, total: SAMPLE.items.length });
});

app.listen(PORT, () => {
  console.log(`\nAgentHazard annotator → http://localhost:${PORT}`);
  console.log(`  sample: ${SAMPLE.meta.n} items (${SAMPLE.meta.harmful} harmful / ${SAMPLE.meta.benign} benign)`);
  console.log(`  mode:   ${REVIEW ? "REVIEW (Gemini labels VISIBLE)" : "BLIND (Gemini labels hidden)"}`);
  console.log(`  annotators: ${ANNOTATORS.join(", ")}\n`);
});
