"""記録（logs/YYYY-MM.jsonl）を集計して表示する。

    python scripts/report.py                    # 今月。所内で見る形（問いの本文とスレッドへのリンクを含む）
    python scripts/report.py --month 2026-11
    python scripts/report.py --all              # すべての月
    python scripts/report.py --since 2026-11-20 --until 2026-11-30
    python scripts/report.py --public           # 公開してよい形（本文、ID、リンクを含まない数だけ）

所内で見る形は、問いの本文を含むので非公開。公開側（nro-context の試行の記録など）には --public の出力だけを載せる。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import mean, median

GOOD, PARTIAL, BAD = "👍", "⚠️", "❌"
ERROR_LABELS = {
    "timeout": "時間切れ",
    "max_rounds": "呼び出しの上限",
    "refusal": "拒否",
}


def load(log_dir: Path, months: list[str] | None) -> list[dict]:
    files = sorted(log_dir.glob("*.jsonl"))
    if months is not None:
        files = [f for f in files if f.stem in months]
    recs = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return recs


def _day(rec: dict) -> date:
    return datetime.fromisoformat(rec["ts"]).date()


def summarize(recs: list[dict], since: date | None = None, until: date | None = None) -> dict:
    if since or until:
        recs = [r for r in recs if (not since or _day(r) >= since) and (not until or _day(r) <= until)]

    threads: dict[int, dict] = defaultdict(lambda: {"answers": [], "followups": 0, "advice": 0, "reactions": Counter()})
    notices = quota = 0
    for r in recs:
        kind, tid = r.get("kind"), r.get("thread_id")
        if kind == "question":
            threads[tid]["question"] = r
        elif kind == "followup":
            threads[tid]["followups"] += 1
        elif kind == "answer":
            threads[tid]["answers"].append(r)
        elif kind == "advice":
            threads[tid]["advice"] += 1
        elif kind == "reaction":
            threads[tid]["reactions"][r.get("emoji", "")] += 1
        elif kind == "notice":
            notices += 1
        elif kind == "quota":
            quota += 1

    # 問いの記録があるスレッドだけを数える（期間の外で始まったスレッドを除く）
    threads = {k: v for k, v in threads.items() if "question" in v}
    answers = [a for t in threads.values() for a in t["answers"]]
    first_answers = [t["answers"][0] for t in threads.values() if t["answers"]]
    reactions = sum((t["reactions"] for t in threads.values()), Counter())
    files = Counter(f for a in answers for f in set(a.get("files_read") or []))
    urls = Counter(u for a in answers for u in set(a.get("urls_fetched") or []))
    errors = Counter(a.get("error") for a in answers if a.get("error"))
    costs = [a.get("cost_usd") or 0 for a in answers]
    times = [a.get("elapsed_s") or 0 for a in answers]
    rounds = [a.get("rounds") or 0 for a in answers]
    days = Counter(_day(t["question"]).isoformat() for t in threads.values())

    return {
        "period": (min((_day(r) for r in recs), default=None), max((_day(r) for r in recs), default=None)),
        "questions": len(threads),
        "followups": sum(t["followups"] for t in threads.values()),
        "answers": len(answers),
        "escalated": sum(1 for a in first_answers if a.get("escalate")),
        "first_answers": len(first_answers),
        "errors": errors,
        "threads_with_advice": sum(1 for t in threads.values() if t["advice"]),
        "advice": sum(t["advice"] for t in threads.values()),
        "reactions": reactions,
        "threads_rated": {
            k: sum(1 for t in threads.values() if t["reactions"][k]) for k in (GOOD, PARTIAL, BAD)
        },
        "notices": notices,
        "quota": quota,
        "cost_total": sum(costs),
        "cost_mean": mean(costs) if costs else 0,
        "cost_max": max(costs, default=0),
        "time_median": median(times) if times else 0,
        "time_max": max(times, default=0),
        "rounds_mean": mean(rounds) if rounds else 0,
        "files": files,
        "urls": urls,
        "days": days,
        "threads": threads,
    }


def _pct(n: int, d: int) -> str:
    return f"{n}（{n / d:.0%}）" if d else "0"


def render(s: dict, public: bool) -> str:
    out = []
    p0, p1 = s["period"]
    out.append(f"# 試行の集計（{p0} 〜 {p1}）" if p0 else "# 試行の集計（記録なし）")
    out.append("")
    if public:
        out.append("問いの本文、投稿者、スレッドを含まない、公開用の集計です。")
        out.append("")

    q = s["questions"]
    out += [
        "## 全体",
        "",
        f"- 問い：{q} 件（続きの問い {s['followups']} 件、回答 {s['answers']} 件）",
        f"- ヘルプデスクへのエスカレーション（最初の回答）：{_pct(s['escalated'], s['first_answers'])}",
        f"- 担当者が助言したスレッド：{_pct(s['threads_with_advice'], q)}（書き込み {s['advice']} 件）",
        f"- 反応のあったスレッド：{GOOD} {s['threads_rated'][GOOD]} 件、{PARTIAL} {s['threads_rated'][PARTIAL]} 件、{BAD} {s['threads_rated'][BAD]} 件",
        f"- エラー：{sum(s['errors'].values())} 件"
        + (f"（{'、'.join(f'{ERROR_LABELS.get(k, k)} {v}' for k, v in s['errors'].items())}）" if s["errors"] else ""),
        f"- お知らせとして答えなかった投稿：{s['notices']} 件、上限で断った問い：{s['quota']} 件",
        "",
        "## 費用と時間",
        "",
        f"- 費用の概算：合計 ${s['cost_total']:.2f}、一回答あたり平均 ${s['cost_mean']:.3f}、最大 ${s['cost_max']:.3f}",
        f"- 回答までの時間：中央値 {s['time_median']:.0f} 秒、最大 {s['time_max']:.0f} 秒",
        f"- 一回答あたりの API 呼び出し：平均 {s['rounds_mean']:.1f} 回",
        "",
        "費用は記録のトークン数からの概算です。実際の請求は Claude Console の Usage で確かめてください。",
        "",
        "## 日ごとの問いの数",
        "",
    ]
    out += [f"- {d}：{n} 件" for d, n in sorted(s["days"].items())] or ["- なし"]
    out += ["", "## よく読まれたファイル（上位 15）", ""]
    out += [f"- {f}：{n} 回" for f, n in s["files"].most_common(15)] or ["- なし"]
    out += ["", "## 開いたウェブページ（上位 10）", ""]
    out += [f"- {u}：{n} 回" for u, n in s["urls"].most_common(10)] or ["- なし"]

    if not public:
        out += ["", "## 問いの一覧", ""]
        for tid, t in sorted(s["threads"].items(), key=lambda kv: kv[1]["question"]["ts"]):
            qr = t["question"]
            first = t["answers"][0] if t["answers"] else {}
            text = " ".join((qr.get("text") or "").split())[:120]
            marks = []
            if first.get("escalate"):
                marks.append("エスカレーション")
            if first.get("error"):
                marks.append(f"エラー：{ERROR_LABELS.get(first['error'], first['error'])}")
            if t["advice"]:
                marks.append(f"助言 {t['advice']}")
            if t["followups"]:
                marks.append(f"続き {t['followups']}")
            rx = " ".join(f"{k}{v}" for k, v in t["reactions"].items() if k)
            if rx:
                marks.append(rx)
            cost = sum(a.get("cost_usd") or 0 for a in t["answers"])
            link = (
                f" https://discord.com/channels/{qr['guild_id']}/{tid}" if qr.get("guild_id") else ""
            )
            out.append(f"- {qr['ts'][:16].replace('T', ' ')}　{text}")
            out.append(f"  - {'、'.join(marks) or '—'}　${cost:.3f}{link}")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log-dir", type=Path, default=Path("/srv/nro-bot/logs"))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--month", help="YYYY-MM（既定は今月）")
    g.add_argument("--all", action="store_true", help="すべての月")
    ap.add_argument("--since", type=date.fromisoformat, help="YYYY-MM-DD 以降")
    ap.add_argument("--until", type=date.fromisoformat, help="YYYY-MM-DD 以前")
    ap.add_argument("--public", action="store_true", help="本文、ID、リンクを含まない公開用の集計")
    a = ap.parse_args(argv)

    if a.all or a.since or a.until:
        months = None
    else:
        months = [a.month or date.today().strftime("%Y-%m")]
    recs = load(a.log_dir, months)
    sys.stdout.write(render(summarize(recs, a.since, a.until), a.public))
    return 0


if __name__ == "__main__":
    sys.exit(main())
