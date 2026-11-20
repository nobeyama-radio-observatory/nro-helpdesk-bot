import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import report  # noqa: E402


def write_log(d: Path, recs: list[dict]) -> None:
    by_month: dict[str, list[str]] = {}
    for r in recs:
        by_month.setdefault(r["ts"][:7], []).append(json.dumps(r, ensure_ascii=False))
    for m, lines in by_month.items():
        (d / f"{m}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


RECS = [
    {"ts": "2026-11-21T10:00:00+09:00", "kind": "question", "guild_id": 9, "thread_id": 1, "user_id": 100, "text": "窓口はどこ？"},
    {"ts": "2026-11-21T10:00:20+09:00", "kind": "answer", "thread_id": 1, "escalate": False, "error": None, "rounds": 2,
     "elapsed_s": 18, "cost_usd": 0.05, "files_read": ["nro-context/users/README.md"], "urls_fetched": ["https://www.nro.nao.ac.jp/a"]},
    {"ts": "2026-11-21T10:01:00+09:00", "kind": "reaction", "thread_id": 1, "user_id": 100, "emoji": "👍"},
    {"ts": "2026-11-21T11:00:00+09:00", "kind": "question", "guild_id": 9, "thread_id": 2, "user_id": 200, "text": "H40 の Tsys が高い"},
    {"ts": "2026-11-21T11:00:40+09:00", "kind": "answer", "thread_id": 2, "escalate": True, "error": None, "rounds": 6,
     "elapsed_s": 40, "cost_usd": 0.15, "files_read": ["nro-context/users/README.md", "nro-45m-receivers/assets.yaml"], "urls_fetched": []},
    {"ts": "2026-11-21T11:05:00+09:00", "kind": "advice", "thread_id": 2, "user_id": 300, "text": "担当者の助言"},
    {"ts": "2026-11-21T11:06:00+09:00", "kind": "followup", "thread_id": 2, "user_id": 200, "text": "続き"},
    {"ts": "2026-11-21T11:06:30+09:00", "kind": "answer", "thread_id": 2, "escalate": False, "error": None, "rounds": 3,
     "elapsed_s": 20, "cost_usd": 0.05, "files_read": [], "urls_fetched": []},
    {"ts": "2026-11-21T11:07:00+09:00", "kind": "reaction", "thread_id": 2, "user_id": 300, "emoji": "⚠️"},
    {"ts": "2026-11-22T09:00:00+09:00", "kind": "notice", "user_id": 300, "text": "ーーーー お知らせ"},
    {"ts": "2026-12-01T09:00:00+09:00", "kind": "question", "guild_id": 9, "thread_id": 3, "user_id": 100, "text": "12月の問い"},
    {"ts": "2026-12-01T09:00:30+09:00", "kind": "answer", "thread_id": 3, "escalate": True, "error": "timeout", "rounds": 25,
     "elapsed_s": 300, "cost_usd": 0.4, "files_read": [], "urls_fetched": []},
]


def test_summary_month(tmp_path):
    write_log(tmp_path, RECS)
    s = report.summarize(report.load(tmp_path, ["2026-11"]))
    assert s["questions"] == 2 and s["followups"] == 1 and s["answers"] == 3
    assert s["escalated"] == 1 and s["first_answers"] == 2
    assert s["threads_with_advice"] == 1 and s["notices"] == 1
    assert s["threads_rated"] == {"👍": 1, "⚠️": 1, "❌": 0}
    assert round(s["cost_total"], 2) == 0.25
    assert s["files"]["nro-context/users/README.md"] == 2


def test_all_and_since(tmp_path):
    write_log(tmp_path, RECS)
    s = report.summarize(report.load(tmp_path, None))
    assert s["questions"] == 3 and s["errors"] == {"timeout": 1}
    s = report.summarize(report.load(tmp_path, None), since=date(2026, 12, 1))
    assert s["questions"] == 1


def test_public_has_no_text_or_ids(tmp_path):
    write_log(tmp_path, RECS)
    s = report.summarize(report.load(tmp_path, None))
    pub = report.render(s, public=True)
    for secret in ("窓口はどこ", "Tsys", "担当者の助言", "discord.com/channels", "12月の問い"):
        assert secret not in pub
    internal = report.render(s, public=False)
    assert "窓口はどこ" in internal and "https://discord.com/channels/9/1" in internal


def test_cli(tmp_path, capsys):
    write_log(tmp_path, RECS)
    assert report.main(["--log-dir", str(tmp_path), "--month", "2026-11"]) == 0
    out = capsys.readouterr().out
    assert "問い：2 件" in out
