#!/usr/bin/env python3
"""
Build the human-validation sample for the LLM-as-Judge agreement study (rebuttal §B).

- Pools all round_all judge labels across frameworks/models from
  workspace/results/trajectory_eval/<framework>/<model>/results.jsonl
- Stratified sampling: N/2 judged-harmful + N/2 judged-not-harmful,
  spread across frameworks and (within framework) across models.
- For each sampled item, loads and NORMALIZES the full trajectory into a
  uniform event stream so the Node annotator can render all three frameworks
  the same way.
- Writes a self-contained validation_sample.json. The original Gemini label
  is stored under "_gemini" (the annotation server withholds it unless launched
  in --review mode, so the blind pass stays blind).

Usage:
    uv run python evaluate/annotation/build_sample.py --n 200 --seed 42
"""
import argparse
import json
import os
import re
import random
import glob
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TRAJ_EVAL = os.path.join(ROOT, "workspace", "results", "trajectory_eval")
DATASET = os.path.join(ROOT, "workspace", "data", "dataset.json")
MAX_CHARS = 6000  # per text/output block, to keep the sample file readable


def truncate(s, n=MAX_CHARS):
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[:n] + f"\n…[truncated {len(s)-n} chars]"


# ---------------------------------------------------------------------------
# trajectory loaders -> unified events: [{role, name, text}]
#   role in {user, assistant, tool_call, tool_result, note}
# ---------------------------------------------------------------------------
def _msg_events(role, content):
    """Normalize one message (role + content str|list-of-blocks) into events.
    Handles text, tool_use / functionCall (-> tool_call), tool_result / functionResponse (-> tool_result)."""
    ev = []
    if isinstance(content, str):
        if content.strip():
            ev.append({"role": role if role in ("user", "assistant") else "assistant", "name": "", "text": truncate(content)})
        return ev
    if not isinstance(content, list):
        return ev
    for b in content:
        if not isinstance(b, dict):
            if isinstance(b, str) and b.strip():
                ev.append({"role": "assistant", "name": "", "text": truncate(b)})
            continue
        bt = b.get("type")
        if bt == "text" and b.get("text"):
            ev.append({"role": role if role in ("user", "assistant") else "assistant", "name": "", "text": truncate(b["text"])})
        elif bt == "tool_use" or "functionCall" in b:
            fc = b.get("functionCall", {})
            name = b.get("name") or fc.get("name", "tool")
            inp = b.get("input", fc.get("args", {}))
            ev.append({"role": "tool_call", "name": name, "text": truncate(json.dumps(inp, ensure_ascii=False, indent=2))})
        elif bt == "tool_result" or "functionResponse" in b:
            fr = (b.get("content") or {}).get("functionResponse", {}) if isinstance(b.get("content"), dict) else b.get("functionResponse", {})
            name = fr.get("name", "tool")
            out = fr.get("response", b.get("content"))
            ev.append({"role": "tool_result", "name": name, "text": truncate(json.dumps(out, ensure_ascii=False, indent=2) if not isinstance(out, str) else out)})
    return ev


def load_openclaw(model, did):
    path = os.path.normpath(os.path.join(TRAJ_EVAL, "..", "openclaw", "intermediate", model, f"{did}.json"))
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    events = []
    hist = (d.get("full_session_history") or {}).get("history", [])
    for e in hist:
        if e.get("type") != "message":
            continue
        m = e.get("message", {})
        role = m.get("role")
        if role == "toolResult":
            events.append({"role": "tool_result", "name": m.get("toolName", "tool"),
                           "text": truncate(json.dumps(m.get("content"), ensure_ascii=False) if not isinstance(m.get("content"), str) else m.get("content"))})
        else:
            events.extend(_msg_events(role, m.get("content")))
    if not events:  # fallback to turns
        for t in d.get("turns", []):
            events.append({"role": "user", "name": "", "text": truncate(t.get("prompt", ""))})
            events.append({"role": "assistant", "name": "", "text": truncate(t.get("response", ""))})
    return events


def load_claude(model, did):
    path = os.path.normpath(os.path.join(TRAJ_EVAL, "..", "claude_code", "intermediate", model, f"trajectory_{did}.jsonl"))
    rec = json.loads(open(path, encoding="utf-8").read().strip())
    events = []
    for t in rec.get("turns", []):
        if t.get("input"):
            events.append({"role": "user", "name": "", "text": truncate(t["input"])})
        if t.get("output"):
            events.append({"role": "assistant", "name": "", "text": truncate(t["output"])})
    dl = rec.get("detail_logs", [])
    if isinstance(dl, list) and dl:
        post_by_id = {x.get("tool_use_id"): x for x in dl if x.get("type") == "post_tool"}
        tools = []
        for x in dl:
            if x.get("type") != "pre_tool":
                continue
            name = x.get("tool_name", "tool")
            tools.append({"role": "tool_call", "name": name, "text": truncate(json.dumps(x.get("tool_input", {}), ensure_ascii=False, indent=2))})
            post = post_by_id.get(x.get("tool_use_id"))
            if post is not None:
                tools.append({"role": "tool_result", "name": name, "text": truncate(json.dumps(post.get("tool_response", {}), ensure_ascii=False, indent=2))})
        if tools:
            events.append({"role": "note", "name": "", "text": "──── Tool actions (execution order) ────"})
            events.extend(tools)
    return events


def load_iflow(model, did):
    path = os.path.normpath(os.path.join(TRAJ_EVAL, "..", "iflow", "intermediate", model, f"trajectory_{did}.jsonl"))
    rec = json.loads(open(path, encoding="utf-8").read().strip())
    events = []
    ch = (rec.get("detail_logs") or {}).get("conversation_history", []) if isinstance(rec.get("detail_logs"), dict) else []
    if ch:
        for m in ch:
            msg = m.get("message", {}) if isinstance(m, dict) else {}
            events.extend(_msg_events(msg.get("role", m.get("type")), msg.get("content")))
    if not events:  # fallback to turns
        for t in rec.get("turns", []):
            if t.get("input"):
                events.append({"role": "user", "name": "", "text": truncate(t["input"])})
            if t.get("output"):
                events.append({"role": "assistant", "name": "", "text": truncate(t["output"])})
    return events


def load_trajectory(framework, model, did):
    if framework == "openclaw":
        return load_openclaw(model, did)
    if framework == "claude_code":
        return load_claude(model, did)
    return load_iflow(model, did)


# infrastructure-failure signatures: the agent never actually ran (wrong model id,
# bad API params, rate-limit, empty responses). Such trajectories are not meaningful
# to judge, so we skip them when sampling.
_ERR = re.compile(
    r"HTTP error! status|HTTP_STATUS/[45]|Throttling|RateQuota|rate limit exceeded|"
    r"\b429\b|\"status\"\s*:\s*[45]\d\d|status: [45]\d\d|"
    r"模型不存在|InvalidParameter|MPE-001|CE-001|enable_thinking|模型提供方错误"
)


def raw_has_error(framework, model, did):
    """Check the RAW trajectory file text (what the judge's format_history draws from)
    for infra-error signatures. Catches errors regardless of our event rendering."""
    if framework == "openclaw":
        p = os.path.normpath(os.path.join(TRAJ_EVAL, "..", "openclaw", "intermediate", model, f"{did}.json"))
    else:
        p = os.path.normpath(os.path.join(TRAJ_EVAL, "..", framework, "intermediate", model, f"trajectory_{did}.jsonl"))
    try:
        txt = open(p, encoding="utf-8").read()
    except Exception:
        return True
    return bool(_ERR.search(txt))


def is_broken(events):
    """True if no assistant/tool event carries real content (empty trajectory)."""
    for e in events:
        if e.get("role") in ("assistant", "tool_call", "tool_result"):
            if len((e.get("text") or "").strip()) >= 3:
                return False
    return True


# original judge (Gemini-3-Flash) self-failure signatures -> its label is a garbage default
_JUDGE_FAIL = re.compile(r"评估失败|无法解析|Error code|MPE-001|CE-001")


# ---------------------------------------------------------------------------
# pool + stratified sampling
# ---------------------------------------------------------------------------
RESULTS = os.path.join(ROOT, "workspace", "results")


def _truthy(v):
    return str(v).strip().lower() in ("true", "1", "yes")


def gather_pool():
    """Pool the per-instance `harmful` judge labels that back the paper's main ASR:
       - OpenClaw  -> trajectory_eval/openclaw/<model>/results.jsonl (round_all)
       - claude/iflow -> workspace/results/<fw>/final/<model>_evaluation_results*.csv
    Returns rows: dict(framework, model, data_id, harmful, score, reason, category,
                       jailbreak_method, attack_objective, attack_comment)."""
    import csv
    rows = []

    # OpenClaw: harmful judge from the trajectory eval (matches the paper)
    for rf in glob.glob(os.path.join(TRAJ_EVAL, "openclaw", "*", "results.jsonl")):
        model = os.path.basename(os.path.dirname(rf))
        seen = set()
        for line in open(rf, encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("round_name") != "round_all":
                continue
            did = str(r["data_id"])
            if did in seen:
                continue
            seen.add(did)
            rows.append({
                "framework": "openclaw", "model": model, "data_id": did,
                "harmful": bool(r["harmful"]), "score": r.get("score"), "reason": r.get("reason", ""),
                "category": r.get("category", ""), "jailbreak_method": r.get("jailbreak_method", ""),
                "attack_objective": "", "attack_comment": r.get("target", ""),
            })

    # claude_code & iflow: harmful judge from the final CSVs (matches the paper)
    for fw in ("claude_code", "iflow"):
        for p in glob.glob(os.path.join(RESULTS, fw, "final", "*.csv")):
            model = re.sub(r"_evaluation_results.*", "", os.path.basename(p))
            idir = os.path.join(RESULTS, fw, "intermediate", model)
            if not os.path.isdir(idir):
                continue  # no trajectories (e.g. claude-qwen3-coder) -> not annotatable
            for r in csv.DictReader(open(p, encoding="utf-8")):
                if "harmful" not in r:
                    continue
                rows.append({
                    "framework": fw, "model": model, "data_id": str(r["id"]),
                    "harmful": _truthy(r["harmful"]), "score": r.get("score"), "reason": r.get("reason", ""),
                    "category": r.get("category", ""), "jailbreak_method": r.get("jailbreak_method", ""),
                    "attack_objective": r.get("query", ""), "attack_comment": r.get("comment", ""),
                })
    return rows


def allocate(total, buckets):
    """Split `total` as evenly as possible across len(buckets) bucket keys -> {key: quota}."""
    k = len(buckets)
    base, rem = divmod(total, k)
    quota = {}
    for i, b in enumerate(buckets):
        quota[b] = base + (1 if i < rem else 0)
    return quota


def stratified_order(rows, harmful, seed):
    """Return ALL rows of one stratum, ordered to round-robin across frameworks then
    models (so a prefix of length k is stratified across framework/model). Extra rows
    beyond the target serve as backfill when a trajectory fails to load."""
    rng = random.Random(seed + (1 if harmful else 0))
    pool = [r for r in rows if r["harmful"] == harmful]
    by_fw_model = defaultdict(list)
    for r in pool:
        by_fw_model[(r["framework"], r["model"])].append(r)
    for k in by_fw_model:
        rng.shuffle(by_fw_model[k])
    # round-robin: framework outer, model inner
    frameworks = sorted({fw for fw, _ in by_fw_model})
    fw_models = {fw: sorted([m for f, m in by_fw_model if f == fw]) for fw in frameworks}
    ordered, exhausted = [], False
    while not exhausted:
        exhausted = True
        for fw in frameworks:
            for m in fw_models[fw]:
                bucket = by_fw_model[(fw, m)]
                if bucket:
                    ordered.append(bucket.pop())
                    exhausted = False
    return ordered


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200, help="total sample size (half harmful, half not)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "validation_sample.json"))
    args = ap.parse_args()

    dataset = {str(x["id"]): x for x in json.load(open(DATASET, encoding="utf-8"))}
    rows = gather_pool()
    print(f"pool: {len(rows)} labeled trajectories "
          f"({sum(r['harmful'] for r in rows)} harmful / {sum(not r['harmful'] for r in rows)} benign)")

    half = args.n // 2
    fail, skipped_broken = 0, 0
    picked = []  # (row, events), collected with backfill until exact quota per stratum
    for harmful, target in ((True, half), (False, args.n - half)):
        order = stratified_order(rows, harmful, args.seed)
        got = 0
        for r in order:
            if got >= target:
                break
            if _JUDGE_FAIL.search(r.get("reason") or ""):  # original judge self-errored -> garbage label
                skipped_broken += 1
                continue
            if raw_has_error(r["framework"], r["model"], r["data_id"]):  # agent run disrupted by infra error
                skipped_broken += 1
                continue
            try:
                events = load_trajectory(r["framework"], r["model"], r["data_id"])
            except Exception:
                fail += 1
                continue
            if is_broken(events):  # empty trajectory
                skipped_broken += 1
                continue
            picked.append((r, events))
            got += 1
        if got < target:
            print(f"  [warn] only {got}/{target} usable in stratum harmful={harmful}")
    print(f"  skipped broken/empty trajectories: {skipped_broken}")

    random.Random(args.seed).shuffle(picked)  # interleave strata so annotators can't infer labels

    items, fw_count = [], defaultdict(int)
    for i, (r, events) in enumerate(picked, 1):
        ds = dataset.get(r["data_id"], {})
        items.append({
            "item_id": i,
            "framework": r["framework"],
            "model": r["model"],
            "data_id": r["data_id"],
            "category": r["category"],
            "jailbreak_method": r["jailbreak_method"],
            "attack_objective": r.get("attack_objective") or ds.get("query", ""),
            "attack_comment": r.get("attack_comment") or ds.get("comment", ""),
            "decomposed_query": ds.get("decomposed_query", []),
            "events": events,
            "_gemini": {"harmful": r["harmful"], "score": r["score"], "reason": r["reason"]},
        })
        fw_count[r["framework"]] += 1

    out = {
        "meta": {
            "n": len(items),
            "requested_n": args.n,
            "seed": args.seed,
            "harmful": sum(it["_gemini"]["harmful"] for it in items),
            "benign": sum(not it["_gemini"]["harmful"] for it in items),
            "by_framework": dict(fw_count),
            "by_model": {m: sum(1 for it in items if it["model"] == m)
                         for m in sorted({it["model"] for it in items})},
            "note": "_gemini is the original judge label; withheld by the server unless launched with --review.",
        },
        "items": items,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"wrote {len(items)} items (skipped {fail}) -> {args.out}")
    print(f"  harmful={out['meta']['harmful']} benign={out['meta']['benign']}")
    print(f"  by_framework={out['meta']['by_framework']}")
    print(f"  by_model={out['meta']['by_model']}")


if __name__ == "__main__":
    main()
