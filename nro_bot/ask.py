"""Discord を通さずに一問だけ試す（動作確認用）。

    python -m nro_bot.ask "45m 鏡の観測提案の締切はいつですか"

ANTHROPIC_API_KEY と NRO_BOT_REPOS_DIR を設定して実行する。API の利用料がかかる。
"""

from __future__ import annotations

import asyncio
import json
import sys

from .agent import Agent
from .config import Config


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cfg = Config.from_env()
    ans = asyncio.run(Agent(cfg).answer([{"role": "user", "content": " ".join(sys.argv[1:])}]))
    print(ans.text or f"（回答なし：{ans.error}）")
    print("\n---")
    print(json.dumps(
        {k: getattr(ans, k) for k in ("escalate", "stop_reason", "error", "rounds", "elapsed_s", "usage", "cost_usd", "files_read", "urls_fetched")},
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
