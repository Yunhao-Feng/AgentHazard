#!/usr/bin/env python3
"""
Compute the §B agreement metrics from the human annotations + the Gemini labels
(and optionally GPT labels). Prints the numbers that fill rebuttal Table 1.

Inputs (same dir):
  validation_sample.json           (has _gemini per item)
  annotations_a1.json, annotations_a2.json
  gpt_labels.json   (optional: {item_id: {"harmful": bool}})  -- from gpt_relabel

Usage:
  uv run python evaluate/annotation/compute_agreement.py
"""
import json
import os

DIR = os.path.dirname(__file__)


def load(p):
    p = os.path.join(DIR, p)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def kappa(a, b):
    """Cohen's kappa for two equal-length lists of bool labels."""
    n = len(a)
    if n == 0:
        return float("nan"), float("nan")
    agree = sum(1 for x, y in zip(a, b) if x == y) / n
    pa_t = sum(a) / n
    pb_t = sum(b) / n
    pe = pa_t * pb_t + (1 - pa_t) * (1 - pb_t)
    k = (agree - pe) / (1 - pe) if pe < 1 else 1.0
    return agree * 100, k


def line(name, agree, k, extra=""):
    print(f"  {name:34} agreement={agree:5.1f}%  kappa={k:5.3f}  {extra}")


def main():
    sample = load("validation_sample.json")
    if sample is None:
        print("validation_sample.json not found — run build_sample.py first.")
        return
    gem = {str(it["item_id"]): bool(it["_gemini"]["harmful"]) for it in sample["items"]}
    a1 = load("annotations_a1.json") or {}
    a2 = load("annotations_a2.json") or {}
    gpt = load("gpt_labels.json")

    ids = [str(it["item_id"]) for it in sample["items"]]

    def lab(d, i):
        v = d.get(i)
        return None if v is None else v.get("harmful")

    # Per-annotator vs Gemini (runs even if only one annotator has labeled so far).
    print(f"\nSample N={len(ids)}")
    print("\n=== Each annotator vs Gemini (interim) ===")
    for nm, d in (("Annotator1", a1), ("Annotator2", a2)):
        labeled = [i for i in ids if lab(d, i) is not None]
        if not labeled:
            print(f"  {nm:11} (no labels yet)")
            continue
        hh = [lab(d, i) for i in labeled]
        gg = [gem[i] for i in labeled]
        ag, k = kappa(hh, gg)
        fp = sum(1 for x, y in zip(hh, gg) if (y and not x))  # Gemini harmful, human benign
        fn = sum(1 for x, y in zip(hh, gg) if (not y and x))  # Gemini benign, human harmful
        line(f"{nm} vs Gemini", ag, k, f"(labeled {len(labeled)}/{len(ids)}; vs-Gemini FP={fp}, FN={fn})")

    # Inter-judge (Gemini vs GPT) needs NO humans -> available as soon as gpt_labels exists.
    if gpt is not None:
        gp_all = {str(k2): bool(v.get("harmful")) for k2, v in gpt.items() if "_error" not in v}
        ij = [i for i in ids if i in gp_all]
        if ij:
            ag, k = kappa([gem[i] for i in ij], [gp_all[i] for i in ij])
            line("Gemini-3 ∩ GPT-5.4 (inter-judge)", ag, k, f"(n={len(ij)})")
        for nm, d in (("Annotator1", a1), ("Annotator2", a2)):
            lj = [i for i in ids if lab(d, i) is not None and i in gp_all]
            if lj:
                ag, k = kappa([lab(d, i) for i in lj], [gp_all[i] for i in lj])
                line(f"{nm} vs GPT-5.4", ag, k, f"(n={len(lj)})")

    both = [i for i in ids if lab(a1, i) is not None and lab(a2, i) is not None]
    print(f"\nboth annotators labeled: {len(both)}")
    if not both:
        print("(inter-annotator κ + human-gold table pending the second annotator)")
        return

    h1 = [lab(a1, i) for i in both]
    h2 = [lab(a2, i) for i in both]

    print("\n=== Table 1 ===")
    ag, k = kappa(h1, h2)
    line("Human1 vs Human2 (inter-annotator)", ag, k)

    # consensus = items where the two humans agree (gold). Disagreements need adjudication.
    consensus = {i: lab(a1, i) for i in both if lab(a1, i) == lab(a2, i)}
    n_disagree = len(both) - len(consensus)
    g_ids = list(consensus)
    gold = [consensus[i] for i in g_ids]

    gj = [gem[i] for i in g_ids]
    ag, k = kappa(gold, gj)
    # confusion treating human consensus as gold
    fp = sum(1 for x, y in zip(gold, gj) if (y and not x))
    fn = sum(1 for x, y in zip(gold, gj) if (not y and x))
    line("Gemini-3-Flash vs human gold", ag, k, f"(gold N={len(gold)}; FP={fp}, FN={fn})")

    if gpt is not None:
        gp_all = {str(k2): bool(v.get("harmful")) for k2, v in gpt.items()}
        gp = [gp_all[i] for i in g_ids if i in gp_all]
        gld = [consensus[i] for i in g_ids if i in gp_all]
        if gp:
            ag, k = kappa(gld, gp)
            line("GPT-5.4 vs human gold", ag, k)
        # inter-judge on items both judges cover
        ij = [i for i in both if i in gp_all]
        if ij:
            ag, k = kappa([gem[i] for i in ij], [gp_all[i] for i in ij])
            line("Gemini-3 ∩ GPT-5.4 (inter-judge)", ag, k)
    else:
        print("  (GPT labels absent — run gpt_relabel.py to fill the GPT/inter-judge rows)")

    print(f"\n  human disagreements needing adjudication: {n_disagree}")


if __name__ == "__main__":
    main()
