# nro-helpdesk-bot

国立天文台 野辺山宇宙電波観測所の Discord で、利用者の問いに答えるボットです。文脈基盤のハブ [nro-context](https://github.com/nobeyama-radio-observatory/nro-context) と、その目録にある公開リポジトリを根拠に答えます。**試行中です。**

- ボットの回答は AI によるもので、観測所の正式な回答ではありません。正本は観測所のウェブサイトとヘルプデスクです。
- ボットが読むのは公開の情報だけです。

## 動き

- 対象のチャンネルに新しい投稿があると、その投稿からスレッドを立てて答えます。
- スレッドの中では、質問した本人の続きの投稿に答えます。ほかの人（ヘルプデスクの担当者など）の書き込みには反応せず、次に答えるときの参考にします。
- 記録がないとき、答えられないとき、緊急の事態のときは、ヘルプデスクのロールにメンションします。
- 回答の冒頭に「AI の回答（試行）」と表示し、出典の URL を付けます。末尾には、試験運用中で回答の精度が低いことがある旨を記します。

## Claude に許していること

| 許す | 許さない |
|---|---|
| 公開リポジトリのクローンの一覧、検索、読み取り（[nro_bot/tools.py](nro_bot/tools.py)） | 書き込み、シェル、クローンの外のファイル |
| 観測所のウェブサイト（nro.nao.ac.jp）の取得 | ほかのサイトの取得、ウェブ検索 |

答え方の指示は [nro_bot/system_prompt.md](nro_bot/system_prompt.md) にあります。モデルは Claude Sonnet 5.5 です。拒否されたときは、サーバー側の既定の代替モデルで答え直します（`fallbacks: "default"`）。

## 上限

一問あたりの API 呼び出しは 25 回、時間は 5 分まで。一日あたりの問いは全体で 100 件まで（一人あたりの制限はなし）。設定は [secrets.env.example](secrets.env.example) と [nro_bot/config.py](nro_bot/config.py) にあります。費用は Claude Console のワークスペースの上限でも止まります。

## 設置

[docs/setup.md](docs/setup.md) を参照してください。

## 試す

```bash
pip install -r requirements.txt pytest
python -m pytest tests        # API を使わない試験
python scripts/sync_repos.py ./repos
ANTHROPIC_API_KEY=... NRO_BOT_REPOS_DIR=./repos python -m nro_bot.ask "質問"   # API の利用料がかかる
```
