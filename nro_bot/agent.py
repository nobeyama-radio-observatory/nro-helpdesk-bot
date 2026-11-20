"""Claude に問いを渡し、公開リポジトリを読ませて回答を作る。"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from .config import Config
from .tools import TOOL_DEFINITIONS, RepoTools

SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text(encoding="utf-8")
ESCALATE_RE = re.compile(r"\[\[ESCALATE:(yes|no)\]\]\s*$", re.IGNORECASE)

# Claude Opus 5.5 の単価（USD / 100万トークン）。概算の記録用
PRICE = {"input": 4.0, "output": 20.0, "cache_write": 5.0, "cache_read": 0.20}


@dataclass
class Answer:
    text: str
    escalate: bool
    stop_reason: str | None
    rounds: int
    elapsed_s: float
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    files_read: list[str] = field(default_factory=list)
    urls_fetched: list[str] = field(default_factory=list)
    request_ids: list[str] = field(default_factory=list)
    error: str | None = None


def _add_usage(total: dict, u) -> None:
    for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        total[k] = total.get(k, 0) + (getattr(u, k, 0) or 0)


def _cost(u: dict) -> float:
    return (
        u.get("input_tokens", 0) * PRICE["input"]
        + u.get("output_tokens", 0) * PRICE["output"]
        + u.get("cache_creation_input_tokens", 0) * PRICE["cache_write"]
        + u.get("cache_read_input_tokens", 0) * PRICE["cache_read"]
    ) / 1_000_000


class Agent:
    def __init__(self, cfg: Config, client: anthropic.AsyncAnthropic | None = None):
        self.cfg = cfg
        self.client = client or anthropic.AsyncAnthropic()
        self.tools = [
            *TOOL_DEFINITIONS,
            {
                "type": "web_fetch_20260209",
                "name": "web_fetch",
                "allowed_domains": ["nro.nao.ac.jp"],
                "max_uses": cfg.web_fetch_max_uses,
                "max_content_tokens": 20_000,
            },
        ]

    async def answer(self, conversation: list[dict]) -> Answer:
        """conversation は [{"role": "user"|"assistant", "content": str}, ...]。最後は user。"""
        t0 = time.monotonic()
        repo = RepoTools(self.cfg.repos_dir, self.cfg.github_org)
        ans = Answer(text="", escalate=True, stop_reason=None, rounds=0, elapsed_s=0.0)
        try:
            await asyncio.wait_for(self._loop(conversation, repo, ans), timeout=self.cfg.timeout_s)
        except asyncio.TimeoutError:
            ans.error = "timeout"
        except anthropic.APIError as e:
            ans.error = f"{type(e).__name__}: {getattr(e, 'message', e)}"
        ans.elapsed_s = round(time.monotonic() - t0, 1)
        ans.files_read = repo.files_read
        ans.cost_usd = round(_cost(ans.usage), 4)
        return ans

    async def _loop(self, conversation: list[dict], repo: RepoTools, ans: Answer) -> None:
        messages: list[dict] = [dict(m) for m in conversation]
        while ans.rounds < self.cfg.max_rounds:
            ans.rounds += 1
            resp = await self.client.beta.messages.create(
                model=self.cfg.model,
                max_tokens=16_000,
                system=SYSTEM_PROMPT,
                tools=self.tools,
                messages=messages,
                output_config={"effort": self.cfg.effort},
                cache_control={"type": "ephemeral"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            ans.request_ids.append(resp._request_id or "")
            _add_usage(ans.usage, resp.usage)
            ans.stop_reason = resp.stop_reason
            for b in resp.content:
                if b.type == "server_tool_use" and b.name == "web_fetch":
                    ans.urls_fetched.append(str((b.input or {}).get("url", "")))

            if resp.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": resp.content})
                continue
            if resp.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": resp.content})
                results = []
                for b in resp.content:
                    if b.type != "tool_use":
                        continue
                    out, is_err = await asyncio.to_thread(repo.run, b.name, dict(b.input or {}))
                    results.append(
                        {"type": "tool_result", "tool_use_id": b.id, "content": out, "is_error": is_err}
                    )
                messages.append({"role": "user", "content": results})
                continue

            # end_turn / max_tokens / refusal など
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            if resp.stop_reason == "refusal":
                ans.error = "refusal"
                text = ""
            m = ESCALATE_RE.search(text)
            ans.escalate = (m.group(1).lower() == "yes") if m else True
            ans.text = ESCALATE_RE.sub("", text).strip()
            return
        ans.error = "max_rounds"
