"""Claude に与える道具：公開リポジトリのクローンの中だけを読む。

書き込み、シェル、リポジトリの外のファイルには触れさせない。
パスは必ず repos_dir の中に解決されることを確かめる（シンボリックリンクで外に出るものも拒む）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_READ_LINES = 400
MAX_READ_CHARS = 40_000
MAX_LIST_ENTRIES = 300
MAX_SEARCH_HITS = 80
MAX_SEARCH_FILE_BYTES = 2_000_000
SKIP_DIRS = {".git", "__pycache__", "node_modules"}
TEXT_SUFFIXES = {
    ".md", ".txt", ".yaml", ".yml", ".json", ".csv", ".tsv", ".py", ".toml",
    ".cfg", ".ini", ".rst", ".html", ".xml", ".sh", ".c", ".h", ".v", ".sv", ".tcl",
}

TOOL_DEFINITIONS = [
    {
        "name": "list_files",
        "description": (
            "公開リポジトリのクローンの中のディレクトリの中身を一覧にする。"
            "path は repos のルートからの相対パス（例：'nro-context'、'nro-context/decisions'）。"
            "空文字列ならリポジトリの一覧を返す。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "相対パス。空ならルート"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "search",
        "description": (
            "公開リポジトリのクローンの中のテキストファイルを、正規表現で検索する（大文字小文字を区別しない）。"
            "path で範囲を絞れる（空ならすべてのリポジトリ）。一致した行を、ファイルと行番号つきで返す。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Python の正規表現"},
                "path": {"type": "string", "description": "検索する範囲の相対パス。空ならすべて"},
            },
            "required": ["pattern", "path"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "read_file",
        "description": (
            f"公開リポジトリのクローンの中のテキストファイルを、行番号つきで読む。一度に最大 {MAX_READ_LINES} 行。"
            "長いファイルは offset（1始まりの行番号）を変えて続きを読む。"
            "結果の先頭に、そのファイルの GitHub の URL を付ける。回答の出典にはこの URL を使う。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相対パス（例：'nro-context/README.md'）"},
                "offset": {"type": "integer", "description": "読み始める行（1始まり）"},
            },
            "required": ["path", "offset"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


class ToolError(Exception):
    pass


@dataclass
class RepoTools:
    root: Path
    github_org: str
    files_read: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.root = self.root.resolve()

    # --- パスの検査 ---
    def _resolve(self, rel: str) -> Path:
        rel = (rel or "").strip().lstrip("/")
        if "\x00" in rel:
            raise ToolError("不正なパスです")
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise ToolError("repos の外は読めません")
        if any(part in SKIP_DIRS for part in p.relative_to(self.root).parts):
            raise ToolError(".git などの内部のディレクトリは読めません")
        return p

    def github_url(self, p: Path) -> str:
        parts = p.relative_to(self.root).parts
        if not parts:
            return f"https://github.com/{self.github_org}"
        repo, rest = parts[0], "/".join(parts[1:])
        kind = "tree" if p.is_dir() else "blob"
        return f"https://github.com/{self.github_org}/{repo}" + (f"/{kind}/main/{rest}" if rest else "")

    # --- 道具 ---
    def list_files(self, path: str) -> str:
        p = self._resolve(path)
        if not p.is_dir():
            raise ToolError(f"ディレクトリではありません：{path}")
        entries = []
        for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name)):
            if child.name in SKIP_DIRS:
                continue
            entries.append(child.name + ("/" if child.is_dir() else ""))
        more = len(entries) - MAX_LIST_ENTRIES
        out = "\n".join(entries[:MAX_LIST_ENTRIES])
        if more > 0:
            out += f"\n…ほか {more} 件"
        return f"{self.github_url(p)}\n{out or '（空）'}"

    def _iter_text_files(self, base: Path):
        if base.is_file():
            yield base
            return
        for f in sorted(base.rglob("*")):
            if any(part in SKIP_DIRS for part in f.relative_to(self.root).parts):
                continue
            if f.is_symlink() or not f.is_file():
                continue
            if f.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if f.stat().st_size > MAX_SEARCH_FILE_BYTES:
                continue
            yield f

    def search(self, pattern: str, path: str) -> str:
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            raise ToolError(f"正規表現が不正です：{e}") from e
        base = self._resolve(path)
        hits: list[str] = []
        for f in self._iter_text_files(base):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = f.relative_to(self.root).as_posix()
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{i}: {line.strip()[:200]}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        return "\n".join(hits) + f"\n…（{MAX_SEARCH_HITS} 件で打ち切り。範囲を絞ってください）"
        return "\n".join(hits) if hits else "一致なし"

    def read_file(self, path: str, offset: int = 1) -> str:
        p = self._resolve(path)
        if not p.is_file():
            raise ToolError(f"ファイルではありません：{path}")
        if p.suffix.lower() not in TEXT_SUFFIXES:
            raise ToolError("テキストのファイルだけ読めます")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, offset)
        chunk, size = [], 0
        for i in range(start, min(len(lines), start + MAX_READ_LINES - 1) + 1):
            s = f"{i}\t{lines[i - 1]}"
            size += len(s) + 1
            if size > MAX_READ_CHARS:
                break
            chunk.append(s)
        end = start + len(chunk) - 1
        self.files_read.append(p.relative_to(self.root).as_posix())
        tail = f"\n…（{end}/{len(lines)} 行。続きは offset={end + 1}）" if end < len(lines) else ""
        return f"{self.github_url(p)}\n" + "\n".join(chunk) + tail

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        """道具を実行し、(結果, エラーか) を返す。"""
        try:
            if name == "list_files":
                return self.list_files(args.get("path", "")), False
            if name == "search":
                return self.search(args.get("pattern", ""), args.get("path", "")), False
            if name == "read_file":
                return self.read_file(args.get("path", ""), int(args.get("offset", 1) or 1)), False
            return f"未知の道具です：{name}", True
        except ToolError as e:
            return str(e), True
        except Exception as e:  # noqa: BLE001 - 道具の失敗はモデルに返して続ける
            return f"エラー：{type(e).__name__}", True
