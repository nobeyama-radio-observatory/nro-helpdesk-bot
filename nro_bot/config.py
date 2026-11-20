"""設定。値はすべて環境変数から読む（secrets.env を systemd の EnvironmentFile で渡す）。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _ids(name: str) -> frozenset[int]:
    raw = os.environ.get(name, "")
    return frozenset(int(x) for x in raw.replace(" ", "").split(",") if x)


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class Config:
    # Discord
    discord_token: str = field(repr=False, default="")
    channel_ids: frozenset[int] = frozenset()  # ボットが答えるチャンネル
    helpdesk_role_id: int | None = None  # 記録がないときにメンションするロール
    # このロールを持つ人のチャンネルへの投稿（お知らせ、注意喚起）には答えない。空ならヘルプデスクのロール
    quiet_role_ids: frozenset[int] = frozenset()

    def staff_role_ids(self) -> frozenset[int]:
        if self.quiet_role_ids:
            return self.quiet_role_ids
        return frozenset({self.helpdesk_role_id}) if self.helpdesk_role_id else frozenset()

    # Claude
    model: str = "claude-sonnet-5-5"
    effort: str = "medium"
    max_rounds: int = 25  # 一問あたりの API 呼び出しの上限
    timeout_s: int = 300  # 一問あたりの時間の上限
    web_fetch_max_uses: int = 6

    # 上限
    daily_limit: int = 100  # 一日あたりの問いの数（全体）
    per_user_daily_limit: int = 0  # 一日あたりの問いの数（一人あたり）。0 は制限なし
    concurrency: int = 2

    # 場所
    repos_dir: Path = Path("/srv/nro-bot/repos")
    log_dir: Path = Path("/srv/nro-bot/logs")
    github_org: str = "nobeyama-radio-observatory"

    @classmethod
    def from_env(cls) -> "Config":
        role = os.environ.get("NRO_BOT_HELPDESK_ROLE_ID")
        return cls(
            discord_token=os.environ.get("DISCORD_TOKEN", ""),
            channel_ids=_ids("NRO_BOT_CHANNEL_IDS"),
            helpdesk_role_id=int(role) if role else None,
            quiet_role_ids=_ids("NRO_BOT_QUIET_ROLE_IDS"),
            model=os.environ.get("NRO_BOT_MODEL", cls.model),
            effort=os.environ.get("NRO_BOT_EFFORT", cls.effort),
            max_rounds=_int("NRO_BOT_MAX_ROUNDS", cls.max_rounds),
            timeout_s=_int("NRO_BOT_TIMEOUT_S", cls.timeout_s),
            web_fetch_max_uses=_int("NRO_BOT_WEB_FETCH_MAX_USES", cls.web_fetch_max_uses),
            daily_limit=_int("NRO_BOT_DAILY_LIMIT", cls.daily_limit),
            per_user_daily_limit=_int("NRO_BOT_PER_USER_DAILY_LIMIT", cls.per_user_daily_limit),
            concurrency=_int("NRO_BOT_CONCURRENCY", cls.concurrency),
            repos_dir=Path(os.environ.get("NRO_BOT_REPOS_DIR", cls.repos_dir)),
            log_dir=Path(os.environ.get("NRO_BOT_LOG_DIR", cls.log_dir)),
            github_org=os.environ.get("NRO_BOT_GITHUB_ORG", cls.github_org),
        )
