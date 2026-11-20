import asyncio
from types import SimpleNamespace as NS

from nro_bot.agent import Agent
from nro_bot.config import Config


def usage():
    return NS(input_tokens=100, output_tokens=50, cache_creation_input_tokens=0, cache_read_input_tokens=1000)


def resp(stop, content):
    return NS(stop_reason=stop, content=content, usage=usage(), _request_id="req_x")


class FakeMessages:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    async def create(self, **kw):
        self.calls.append(kw)
        return self.script.pop(0)


def fake_client(script):
    m = FakeMessages(script)
    return NS(beta=NS(messages=m)), m


def test_loop_tool_pause_and_escalate(tmp_path):
    (tmp_path / "nro-context").mkdir()
    (tmp_path / "nro-context" / "README.md").write_text("hub\n", encoding="utf-8")
    script = [
        resp("tool_use", [NS(type="tool_use", id="t1", name="read_file", input={"path": "nro-context/README.md", "offset": 1})]),
        resp("pause_turn", [NS(type="server_tool_use", name="web_fetch", input={"url": "https://www.nro.nao.ac.jp/x"})]),
        resp("end_turn", [NS(type="text", text="答え <https://github.com/x>\n[[ESCALATE:no]]")]),
    ]
    client, m = fake_client(script)
    ans = asyncio.run(Agent(Config(repos_dir=tmp_path), client).answer([{"role": "user", "content": "q"}]))
    assert ans.text == "答え <https://github.com/x>"
    assert ans.escalate is False
    assert ans.rounds == 3 and ans.error is None
    assert ans.files_read == ["nro-context/README.md"]
    assert ans.urls_fetched == ["https://www.nro.nao.ac.jp/x"]
    tr = m.calls[-1]["messages"][2]["content"][0]  # user, assistant(tool_use), user(tool_result), ...
    assert tr["type"] == "tool_result" and tr["tool_use_id"] == "t1" and not tr["is_error"]
    assert m.calls[0]["fallbacks"] == "default"


def test_missing_marker_escalates(tmp_path):
    client, _ = fake_client([resp("end_turn", [NS(type="text", text="わかりません")])])
    ans = asyncio.run(Agent(Config(repos_dir=tmp_path), client).answer([{"role": "user", "content": "q"}]))
    assert ans.escalate is True


def test_max_rounds(tmp_path):
    loop = [resp("tool_use", [NS(type="tool_use", id=f"t{i}", name="list_files", input={"path": ""})]) for i in range(3)]
    client, _ = fake_client(loop)
    ans = asyncio.run(Agent(Config(repos_dir=tmp_path, max_rounds=3), client).answer([{"role": "user", "content": "q"}]))
    assert ans.error == "max_rounds"


def test_sonnet_cost(tmp_path):
    client, m = fake_client([resp("end_turn", [NS(type="text", text="ok\n[[ESCALATE:no]]")])])
    ans = asyncio.run(Agent(Config(repos_dir=tmp_path), client).answer([{"role": "user", "content": "q"}]))
    assert m.calls[0]["model"] == "claude-sonnet-5-5"
    # 100*2 + 50*10 + 1000*0.10 = 800 / 1e6
    assert ans.cost_usd == 0.0008
