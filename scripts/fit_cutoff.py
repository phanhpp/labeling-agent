"""Fit Jev's cut-off, and check how far Jev can be trusted.

    uv run python -m scripts.fit_cutoff            # score, fit, report
    uv run python -m scripts.fit_cutoff --write    # also write the cut-off into policies/v1.yaml

1. Jev scores every Jev-fit row once and every dev row twice. Raw scores go to
   eval/runs/jev-scores/, so the cut-off can be re-tuned later without new calls.
2. The cut-off is fitted for agreement with Sonnet, not with the gold label: the screen's job is to
   skip Sonnet only where Sonnet would say ALLOWED. (Fitted to gold fraud, no cut-off works: much
   EMSCAD fraud matches no v1 section, so Jev scores it low and Sonnet allows it too.) A false clear
   is a posting Sonnet flags (VIOLATING or NEEDS_REVIEW) that Jev would clear. The cut-off is the
   largest one at which at most 2% of Sonnet-flagged dev postings are cleared, then checked on 300
   held-out Jev-fit rows with their own Sonnet labels.
3. Checks: run-to-run stability on dev, agreement with Sonnet's findings per section (from the
   dev300-sonnet_only run), and how often the injection question fires on ordinary postings.
"""

import argparse
import asyncio
import json
import math
from pathlib import Path

from app import config
from app import policy as policies
from app.agent import screen
from app.agent.clean import clean_posting
from app.dataset import CSV_PATH, read_rows
from scripts.load_data import SPLITS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "eval" / "runs" / "jev-scores"
SONNET_RUN = ROOT / "eval" / "runs" / "dev300-sonnet_only" / "results.jsonl"
HELDOUT_RUN = ROOT / "eval" / "runs" / "jevfit300-sonnet_only" / "results.jsonl"
MAX_FLAGGED_CLEARED = 0.02
CANDIDATES = [round(0.05 + 0.01 * i, 2) for i in range(66)]


async def score_rows(rows: list[dict], policy: dict, path: Path, concurrency: int = 8) -> list[dict]:
    gate = asyncio.Semaphore(concurrency)
    results = []

    async def one(row):
        async with gate:
            cleaned = clean_posting(row)
            base = {
                "job_id": row["job_id"],
                "gold": int(row["fraudulent"]),
                "regex_hits": screen.injection_hits(cleaned),
                "red_flags": screen.red_flag_hits(cleaned, policy),
            }
            try:
                result = {"used": "jev", "regex_hits": [], "red_flags": []}
                await screen._jev_screen(cleaned, policy, result, [])
                results.append(base | {"scores": result["scores"], "injection": result["injection"]})
            except Exception as error:  # noqa: BLE001
                results.append(base | {"error": f"{type(error).__name__}: {error}"[:200]})

    await asyncio.gather(*(one(row) for row in rows))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in sorted(results, key=lambda r: int(r["job_id"]))))
    return results


def cleared(r: dict, cut_off: float) -> bool:
    return (
        "error" not in r
        and all(score < cut_off for score in r["scores"].values())
        and r["injection"] < config.INJECTION_THRESHOLD
        and not r["regex_hits"]
        and not r["red_flags"]
    )


def upper_bound(k: int, n: int, confidence: float = 0.95) -> float:
    """Exact (Clopper-Pearson) one-sided upper bound on a rate seen k times in n."""
    if n == 0:
        return 1.0

    def cdf(p):
        return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))

    low, high = k / n, 1.0
    for _ in range(60):
        mid = (low + high) / 2
        low, high = (mid, high) if cdf(mid) > 1 - confidence else (low, mid)
    return round(high, 4)


def clear_report(rows: list[dict], cut_off: float) -> dict:
    ok = [r for r in rows if "error" not in r]
    fraud = [r for r in ok if r["gold"] == 1]
    legit = [r for r in ok if r["gold"] == 0]
    fraud_cleared = sum(cleared(r, cut_off) for r in fraud)
    legit_cleared = sum(cleared(r, cut_off) for r in legit)
    legit_rate = legit_cleared / len(legit) if legit else 0
    fraud_rate = fraud_cleared / len(fraud) if fraud else 0
    return {
        "fraud_cleared": f"{fraud_cleared}/{len(fraud)}",
        "fraud_cleared_rate": round(fraud_rate, 4),
        "fraud_cleared_upper_95": upper_bound(fraud_cleared, len(fraud)),
        "legit_cleared_rate": round(legit_rate, 4),
        # Share of all postings cleared if fraud were 4.8% of traffic: what Sonnet no longer sees.
        "cleared_at_real_rate": round(0.952 * legit_rate + 0.048 * fraud_rate, 4),
        "errored": len(rows) - len(ok),
    }


def sonnet_labels(path: Path) -> dict[str, str]:
    return {r["job_id"]: r["label"] for r in map(json.loads, path.read_text().splitlines()) if "label" in r}


def against_sonnet(rows: list[dict], labels: dict[str, str], cut_off: float) -> dict:
    """How the screen at this cut-off compares with Sonnet on the same postings."""
    ok = [r for r in rows if "error" not in r and r["job_id"] in labels]
    flagged = [r for r in ok if labels[r["job_id"]] != "ALLOWED"]
    wrongly = sum(cleared(r, cut_off) for r in flagged)
    fraud = [r for r in ok if r["gold"] == 1]
    return {
        "postings": len(ok),
        "sonnet_flagged_cleared": f"{wrongly}/{len(flagged)}",
        "sonnet_flagged_cleared_rate": round(wrongly / len(flagged), 4) if flagged else 0.0,
        "sonnet_flagged_cleared_upper_95": upper_bound(wrongly, len(flagged)),
        "cleared_share": round(sum(cleared(r, cut_off) for r in ok) / len(ok), 4) if ok else 0.0,
        "gold_fraud_cleared": f"{sum(cleared(r, cut_off) for r in fraud)}/{len(fraud)}",
    }


def agreement_with_sonnet(dev: list[dict], cut_off: float) -> dict:
    if not SONNET_RUN.exists():
        return {}
    sonnet = {
        r["job_id"]: r["findings"]
        for r in map(json.loads, SONNET_RUN.read_text().splitlines())
        if "findings" in r
    }
    by_section = {}
    for r in dev:
        if "error" in r or r["job_id"] not in sonnet:
            continue
        for code, score in r["scores"].items():
            status = sonnet[r["job_id"]].get(code, "not_matched")
            entry = by_section.setdefault(
                code, {"sonnet_flagged": [], "sonnet_not": [], "jev_low_but_sonnet_flagged": 0}
            )
            if status in ("matched", "unsure"):
                entry["sonnet_flagged"].append(score)
                entry["jev_low_but_sonnet_flagged"] += score < cut_off
            else:
                entry["sonnet_not"].append(score)
    return {
        code: {
            "mean_jev_when_sonnet_flagged": round(sum(e["sonnet_flagged"]) / len(e["sonnet_flagged"]), 3)
            if e["sonnet_flagged"]
            else None,
            "mean_jev_when_sonnet_not": round(sum(e["sonnet_not"]) / len(e["sonnet_not"]), 3)
            if e["sonnet_not"]
            else None,
            "sonnet_flagged": len(e["sonnet_flagged"]),
            "jev_under_cut_off_but_sonnet_flagged": e["jev_low_but_sonnet_flagged"],
        }
        for code, e in sorted(by_section.items())
    }


def stability(a: list[dict], b: list[dict], cut_off: float) -> dict:
    second = {r["job_id"]: r for r in b if "error" not in r}
    diffs, flips = [], 0
    for r in a:
        other = second.get(r["job_id"])
        if "error" in r or other is None:
            continue
        diffs += [abs(r["scores"][c] - other["scores"][c]) for c in r["scores"]]
        flips += cleared(r, cut_off) != cleared(other, cut_off)
    return {
        "mean_abs_score_change": round(sum(diffs) / len(diffs), 4) if diffs else None,
        "max_score_change": round(max(diffs), 4) if diffs else None,
        "clear_decisions_flipped": flips,
    }


def injection_report(rows: list[dict]) -> dict:
    ok = [r["injection"] for r in rows if "error" not in r]
    return {
        "at_or_over_threshold": sum(s >= config.INJECTION_THRESHOLD for s in ok),
        "of": len(ok),
        "max": max(ok) if ok else None,
        "median": sorted(ok)[len(ok) // 2] if ok else None,
    }


def load_or_score(name: str, rows: list[dict], policy: dict, rescore: bool) -> list[dict]:
    path = OUT / f"{name}.jsonl"
    if path.exists() and not rescore:
        return [json.loads(line) for line in path.read_text().splitlines()]
    return asyncio.run(score_rows(rows, policy, path))


def main(write: bool, rescore: bool) -> None:
    policy = policies.load_file(policies.POLICIES_DIR / "v1.yaml")
    splits = json.loads(SPLITS.read_text())
    wanted = set(splits["jev_fit"]["ids"]) | set(splits["dev"]["ids"])
    rows = {r["job_id"]: r for r in read_rows(CSV_PATH) if r["job_id"] in wanted}
    fit = load_or_score("jev_fit", [rows[i] for i in splits["jev_fit"]["ids"]], policy, rescore)
    dev_a = load_or_score("dev_a", [rows[i] for i in splits["dev"]["ids"]], policy, rescore)
    dev_b = load_or_score("dev_b", [rows[i] for i in splits["dev"]["ids"]], policy, rescore)

    dev_sonnet = sonnet_labels(SONNET_RUN)
    fitting = [(t, against_sonnet(dev_a, dev_sonnet, t)) for t in CANDIDATES]
    allowed = [t for t, r in fitting if r["sonnet_flagged_cleared_rate"] <= MAX_FLAGGED_CLEARED]
    cut_off = max(allowed) if allowed else None
    heldout = sonnet_labels(HELDOUT_RUN) if HELDOUT_RUN.exists() else {}
    summary = {
        "jev_model": config.JEV,
        "rule": f"largest cut-off clearing at most {MAX_FLAGGED_CLEARED:.0%} of Sonnet-flagged dev postings",
        "cut_off": cut_off,
        "fit_on_dev": against_sonnet(dev_a, dev_sonnet, cut_off) if cut_off else None,
        "held_out_jev_fit_300": against_sonnet(fit, heldout, cut_off) if cut_off and heldout else None,
        "gold_fraud_view": {"jev_fit": clear_report(fit, cut_off), "dev": clear_report(dev_a, cut_off)}
        if cut_off
        else None,
        "curve_on_dev": {
            t: {k: r[k] for k in ("sonnet_flagged_cleared_rate", "cleared_share")} for t, r in fitting[::5]
        },
        "stability_dev": stability(dev_a, dev_b, cut_off) if cut_off else None,
        "agreement_with_sonnet_dev": agreement_with_sonnet(dev_a, cut_off or 0.3),
        "injection_question": {"jev_fit": injection_report(fit), "dev": injection_report(dev_a)},
        "cost_usd": round(sum(1 for r in fit + dev_a + dev_b if "error" not in r) * 1300 * 0.042 / 1e6, 4),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(
        json.dumps(
            {
                k: summary[k]
                for k in ("cut_off", "fit_on_dev", "held_out_jev_fit_300", "gold_fraud_view", "stability_dev")
            },
            indent=1,
        )
    )
    if write and cut_off is not None:
        path = policies.POLICIES_DIR / "v1.yaml"
        text = path.read_text()
        assert "\nscreen_cut_off: null\n" in text, "v1.yaml already has a fitted cut-off"
        path.write_text(text.replace("\nscreen_cut_off: null\n", f"\nscreen_cut_off: {cut_off}\n"))
        print(f"wrote screen_cut_off: {cut_off} into {path.relative_to(ROOT)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--rescore", action="store_true", help="call Jev again instead of reusing saved scores"
    )
    args = parser.parse_args()
    main(args.write, args.rescore)
