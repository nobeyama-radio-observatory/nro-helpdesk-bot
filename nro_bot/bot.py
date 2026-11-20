"""Discord のボット本体。

- 対象のチャンネルに新しい投稿があると、その投稿からスレッドを立てて答える。
- スレッドの中では、質問した本人の続きの投稿に答える。
- ほかの人（ヘルプデスクの担当者など）の書き込みには反応せず、助言として記録する。
  本人の続きの問いに答えるときは、担当者の書き込みも文脈として Claude に渡す。
- 回答への反応（絵文字）を記録する。
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter

import discord

from .agent import Agent, Answer
from .config import Config
from .logstore import LogStore, now_jst

log = logging.getLogger("nro_bot")

HEADER = "🤖 **AI の回答（試行）**　観測所の正式な回答ではありません。正本は観測所のウェブサイトとヘルプデスクです。"
FOOTER = (
    "⚠️ まだ試験運用中のため、回答の精度が低いことがあります。大事な点は正本とヘルプデスクで確かめてください。\n"
    "-# 回答に 👍（役に立った）⚠️（一部に誤りや不足）❌（誤り）で反応していただけると、改善に使います。"
)
THINKING = "🔎 文脈基盤を調べています…（1〜数分かかります）"
DISCORD_LIMIT = 1900


def split_message(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    chunks, buf = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(buf) + len(line) > limit:
            chunks.append(buf)
            buf = ""
        buf += line
    if buf.strip():
        chunks.append(buf)
    return chunks or [""]


class HelpdeskBot(discord.Client):
    def __init__(self, cfg: Config, agent: Agent, store: LogStore):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions(everyone=False, users=True, roles=True))
        self.cfg = cfg
        self.agent = agent
        self.store = store
        self.sem = asyncio.Semaphore(cfg.concurrency)
        self.day = now_jst().date()
        self.count_total = 0
        self.count_user: Counter[int] = Counter()

    # --- 上限 ---
    def _take_quota(self, user_id: int) -> str | None:
        today = now_jst().date()
        if today != self.day:
            self.day, self.count_total, self.count_user = today, 0, Counter()
        if self.count_total >= self.cfg.daily_limit:
            return "本日の試行の上限に達しました。明日以降にもう一度お試しいただくか、ヘルプデスクにお問い合わせください。"
        if self.cfg.per_user_daily_limit and self.count_user[user_id] >= self.cfg.per_user_daily_limit:
            return "お一人あたりの本日の上限に達しました。明日以降にもう一度お試しください。"
        self.count_total += 1
        self.count_user[user_id] += 1
        return None

    # --- イベント ---
    async def on_ready(self) -> None:
        log.info("logged in as %s (channels=%s)", self.user, sorted(self.cfg.channel_ids))
        self.store.write("start", model=self.cfg.model, effort=self.cfg.effort)

    async def on_message(self, msg: discord.Message) -> None:
        if msg.author.bot or msg.type not in (discord.MessageType.default, discord.MessageType.reply):
            return
        ch = msg.channel
        if isinstance(ch, discord.Thread):
            if ch.parent_id in self.cfg.channel_ids and ch.owner_id == self.user.id:
                await self._on_thread_message(ch, msg)
            return
        if ch.id in self.cfg.channel_ids:
            if self._is_staff(msg.author) or self._is_notice(msg.content):
                # 担当者の投稿と、お知らせの印から始まる投稿には答えない
                self.store.write("notice", message_id=msg.id, user_id=msg.author.id, text=msg.clean_content)
                return
            await self._on_new_question(msg)

    def _is_notice(self, content: str) -> bool:
        text = (content or "").lstrip()
        return any(text.startswith(p) for p in self.cfg.notice_prefixes)

    def _is_staff(self, author) -> bool:
        role_ids = {r.id for r in getattr(author, "roles", [])}
        return bool(role_ids & self.cfg.staff_role_ids())

    async def on_raw_reaction_add(self, ev: discord.RawReactionActionEvent) -> None:
        if ev.user_id == self.user.id:
            return
        ch = self.get_channel(ev.channel_id)
        if isinstance(ch, discord.Thread) and ch.owner_id == self.user.id and ch.parent_id in self.cfg.channel_ids:
            self.store.write("reaction", thread_id=ch.id, message_id=ev.message_id, user_id=ev.user_id, emoji=str(ev.emoji))

    # --- 処理 ---
    async def _on_new_question(self, msg: discord.Message) -> None:
        name = (msg.clean_content.strip().splitlines() or ["質問"])[0][:80] or "質問"
        thread = await msg.create_thread(name=name, auto_archive_duration=10080)
        self.store.write("question", thread_id=thread.id, message_id=msg.id, user_id=msg.author.id, text=msg.clean_content)
        await self._respond(thread, msg.author.id, [{"role": "user", "content": msg.clean_content}])

    async def _on_thread_message(self, thread: discord.Thread, msg: discord.Message) -> None:
        starter = await self._starter(thread)
        asker_id = starter.author.id if starter else None
        if msg.author.id != asker_id:
            self.store.write("advice", thread_id=thread.id, message_id=msg.id, user_id=msg.author.id, text=msg.clean_content)
            return
        self.store.write("followup", thread_id=thread.id, message_id=msg.id, user_id=msg.author.id, text=msg.clean_content)
        conversation = await self._build_conversation(thread, starter, asker_id)
        await self._respond(thread, asker_id, conversation)

    async def _starter(self, thread: discord.Thread) -> discord.Message | None:
        parent = thread.parent
        if parent is None:
            return None
        try:
            return await parent.fetch_message(thread.id)  # スレッドの ID は起点の投稿の ID と同じ
        except discord.NotFound:
            return None

    async def _build_conversation(self, thread: discord.Thread, starter: discord.Message | None, asker_id: int) -> list[dict]:
        """スレッドの履歴から会話を組み立てる。担当者の書き込みは、本人の発言に添える形で渡す。"""
        turns: list[dict] = []
        if starter:
            turns.append({"role": "user", "content": starter.clean_content})
        async for m in thread.history(limit=100, oldest_first=True):
            if m.type not in (discord.MessageType.default, discord.MessageType.reply):
                continue
            if m.author.id == self.user.id:
                text = m.content.replace(HEADER, "").replace(FOOTER, "").strip()
                if not text or text == THINKING:
                    continue
                role, content = "assistant", text
            elif m.author.id == asker_id:
                role, content = "user", m.clean_content
            else:
                role, content = "user", f"（ヘルプデスクの担当者 {m.author.display_name} の書き込み。参考にする）\n{m.clean_content}"
            if turns and turns[-1]["role"] == role:
                turns[-1]["content"] += "\n\n" + content
            else:
                turns.append({"role": role, "content": content})
        # API は user で始まり user で終わる必要がある
        while turns and turns[0]["role"] != "user":
            turns.pop(0)
        while turns and turns[-1]["role"] != "user":
            turns.pop()
        return turns

    async def _respond(self, thread: discord.Thread, asker_id: int, conversation: list[dict]) -> None:
        refused = self._take_quota(asker_id)
        if refused:
            await thread.send(refused)
            self.store.write("quota", thread_id=thread.id, user_id=asker_id)
            return
        placeholder = await thread.send(THINKING)
        async with self.sem:
            async with thread.typing():
                ans: Answer = await self.agent.answer(conversation)
        self.store.write(
            "answer", thread_id=thread.id, user_id=asker_id, text=ans.text, escalate=ans.escalate,
            stop_reason=ans.stop_reason, error=ans.error, rounds=ans.rounds, elapsed_s=ans.elapsed_s,
            usage=ans.usage, cost_usd=ans.cost_usd, files_read=ans.files_read,
            urls_fetched=ans.urls_fetched, request_ids=ans.request_ids,
        )
        log.info("answered thread=%s rounds=%s cost=$%.3f error=%s", thread.id, ans.rounds, ans.cost_usd, ans.error)

        if ans.error or not ans.text:
            body = "うまく回答を作れませんでした。ヘルプデスクの担当者が確認します。"
            escalate = True
        else:
            body, escalate = ans.text, ans.escalate
        if escalate and self.cfg.helpdesk_role_id:
            body += f"\n\n<@&{self.cfg.helpdesk_role_id}> 確認をお願いします。"

        parts = split_message(f"{HEADER}\n\n{body}\n\n{FOOTER}")
        await placeholder.edit(content=parts[0])
        for p in parts[1:]:
            await thread.send(p)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.from_env()
    if not cfg.discord_token or not cfg.channel_ids:
        raise SystemExit("DISCORD_TOKEN と NRO_BOT_CHANNEL_IDS を設定してください")
    bot = HelpdeskBot(cfg, Agent(cfg), LogStore(cfg.log_dir))
    bot.run(cfg.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
