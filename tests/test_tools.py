from pathlib import Path

import pytest

from nro_bot.bot import split_message
from nro_bot.tools import RepoTools


@pytest.fixture
def repos(tmp_path: Path) -> Path:
    root = tmp_path / "repos"
    (root / "nro-context" / "users").mkdir(parents=True)
    (root / "nro-context" / "README.md").write_text("# hub\nline2 Helpdesk\n", encoding="utf-8")
    (root / "nro-context" / "users" / "README.md").write_text("窓口 Discord\n", encoding="utf-8")
    (root / "nro-context" / ".git").mkdir()
    (root / "nro-context" / ".git" / "config").write_text("secret", encoding="utf-8")
    (tmp_path / "outside.md").write_text("outside secret", encoding="utf-8")
    (root / "nro-context" / "link.md").symlink_to(tmp_path / "outside.md")
    return root


def tools(root: Path) -> RepoTools:
    return RepoTools(root, "nobeyama-radio-observatory")


def test_read_with_url(repos):
    t = tools(repos)
    out, err = t.run("read_file", {"path": "nro-context/README.md", "offset": 1})
    assert not err
    assert out.startswith("https://github.com/nobeyama-radio-observatory/nro-context/blob/main/README.md")
    assert "1\t# hub" in out
    assert t.files_read == ["nro-context/README.md"]


@pytest.mark.parametrize("path", ["../outside.md", "/etc/passwd", "nro-context/../../outside.md", "nro-context/link.md", "nro-context/.git/config"])
def test_cannot_escape(repos, path):
    out, err = tools(repos).run("read_file", {"path": path, "offset": 1})
    assert err
    assert "secret" not in out


def test_search_skips_git_and_symlink(repos):
    out, err = tools(repos).run("search", {"pattern": "secret|helpdesk|discord", "path": ""})
    assert not err
    assert "README.md:2" in out
    assert "users/README.md:1" in out
    assert "secret" not in out


def test_list_root(repos):
    out, err = tools(repos).run("list_files", {"path": ""})
    assert not err and "nro-context/" in out


def test_bad_regex(repos):
    _, err = tools(repos).run("search", {"pattern": "(", "path": ""})
    assert err


def test_split_message():
    text = "a" * 50 + "\n" + "b" * 4000
    parts = split_message(text, limit=1000)
    assert all(len(p) <= 1000 for p in parts)
    assert "".join(parts) == text


def test_quota_default_unlimited_per_user():
    from nro_bot.bot import HelpdeskBot, FOOTER
    from nro_bot.config import Config

    bot = HelpdeskBot.__new__(HelpdeskBot)  # Discord に接続せずに上限の処理だけ試す
    from collections import Counter
    from nro_bot.logstore import now_jst
    bot.cfg = Config(daily_limit=100)
    bot.day, bot.count_total, bot.count_user = now_jst().date(), 0, Counter()
    assert all(bot._take_quota(1) is None for _ in range(100))
    assert bot._take_quota(2) is not None  # 全体の 101 件目は断る
    assert "精度が低いことがあります" in FOOTER


def test_staff_posts_are_not_questions():
    from types import SimpleNamespace as NS
    from nro_bot.bot import HelpdeskBot
    from nro_bot.config import Config

    bot = HelpdeskBot.__new__(HelpdeskBot)
    bot.cfg = Config(helpdesk_role_id=111)
    assert bot._is_staff(NS(roles=[NS(id=111)]))
    assert not bot._is_staff(NS(roles=[NS(id=222)]))
    assert not bot._is_staff(NS())  # ロールの情報がない（DM など）
    bot.cfg = Config(helpdesk_role_id=111, quiet_role_ids=frozenset({333}))
    assert bot._is_staff(NS(roles=[NS(id=333)]))
    assert not bot._is_staff(NS(roles=[NS(id=111)]))
