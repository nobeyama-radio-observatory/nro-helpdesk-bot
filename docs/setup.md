# ラズパイへの設置

Raspberry Pi OS Lite（64-bit）に、ボット専用のユーザー `nrobot`（ホームは `/srv/nro-bot`）を作ってある前提です。管理用のユーザーで作業します。

## 1. プログラムと公開リポジトリを置く

```bash
sudo -u nrobot git clone https://github.com/nobeyama-radio-observatory/nro-helpdesk-bot.git /srv/nro-bot/app
sudo -u nrobot python3 -m venv /srv/nro-bot/venv
sudo -u nrobot /srv/nro-bot/venv/bin/pip install -r /srv/nro-bot/app/requirements.txt
sudo -u nrobot mkdir -p /srv/nro-bot/repos /srv/nro-bot/logs
sudo chmod 700 /srv/nro-bot/logs
cd /srv/nro-bot/app && sudo -u nrobot /srv/nro-bot/venv/bin/python scripts/sync_repos.py /srv/nro-bot/repos
```

最後のコマンドで、`ok nro-45m-...` が目録のリポジトリの数だけ出れば成功です。

## 2. 認証情報を置く

```bash
sudo install -o nrobot -g nrobot -m 600 /srv/nro-bot/app/secrets.env.example /srv/nro-bot/secrets.env
sudo nano /srv/nro-bot/secrets.env
```

`ANTHROPIC_API_KEY`、`DISCORD_TOKEN`、`NRO_BOT_CHANNEL_IDS` を書きます。キーとトークンは、このファイルのほかには置きません。

## 3. 一問だけ試す（Discord を通さない）

```bash
cd /srv/nro-bot/app
sudo -u nrobot bash -c 'set -a; . /srv/nro-bot/secrets.env; NRO_BOT_REPOS_DIR=/srv/nro-bot/repos /srv/nro-bot/venv/bin/python -m nro_bot.ask "45m 鏡の共同利用について質問したいときの窓口はどこですか"'
```

回答と、使った道具、費用の概算（`cost_usd`）が表示されます。API の利用料がかかります。

## 4. 常駐させる

```bash
sudo cp /srv/nro-bot/app/deploy/nro-bot.service /srv/nro-bot/app/deploy/nro-bot-sync.service /srv/nro-bot/app/deploy/nro-bot-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nro-bot-sync.timer nro-bot.service
systemctl status nro-bot.service
journalctl -u nro-bot.service -f      # ログを見る（Ctrl-C で抜ける）
```

`logged in as ...` が出れば、Discord につながっています。

## 日々の操作

| 操作 | コマンド |
|---|---|
| 止める | `sudo systemctl stop nro-bot` |
| 再開する | `sudo systemctl start nro-bot` |
| プログラムを更新する | `sudo -u nrobot git -C /srv/nro-bot/app pull && sudo -u nrobot /srv/nro-bot/venv/bin/pip install -r /srv/nro-bot/app/requirements.txt && sudo systemctl restart nro-bot` |
| 公開リポジトリをすぐ更新する | `sudo systemctl start nro-bot-sync` |
| 記録を見る | `sudo -u nrobot less /srv/nro-bot/logs/$(date +%Y-%m).jsonl` |

## 記録について

`/srv/nro-bot/logs/YYYY-MM.jsonl` に、問い（`question`、`followup`）、回答（`answer`：読んだファイル、開いた URL、トークン数、費用の概算、要したラウンド数）、担当者の書き込み（`advice`）、反応（`reaction`）が一行ずつ残ります。投稿者の ID と本文を含むので**非公開**です。公開側には、匿名化して集計したものだけを載せます。
