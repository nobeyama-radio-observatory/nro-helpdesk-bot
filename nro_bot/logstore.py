"""記録：問い、回答、反応、担当者の助言を JSON Lines で残す。

記録には投稿者の ID と本文が含まれるので非公開。ラズパイの log_dir にだけ置き、リポジトリには入れない。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))


def now_jst() -> datetime:
    return datetime.now(JST)


class LogStore:
    def __init__(self, log_dir: Path):
        self.dir = log_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.dir, 0o700)

    def write(self, kind: str, **data) -> None:
        rec = {"ts": now_jst().isoformat(timespec="seconds"), "kind": kind, **data}
        path = self.dir / f"{now_jst():%Y-%m}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
