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

## 5. 更新を自動で反映する（任意）

10 分ごとに GitHub の `main` を確かめ、更新があれば取得してボットを再起動します。

```bash
sudo install -o root -g root -m 755 /srv/nro-bot/app/deploy/nro-bot-update.sh /usr/local/sbin/nro-bot-update
sudo cp /srv/nro-bot/app/deploy/nro-bot-update.service /srv/nro-bot/app/deploy/nro-bot-update.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nro-bot-update.timer
```

- 更新の内容：`main` の取得、`requirements.txt` が変わったときだけライブラリの入れ直し、読み込みの確認、ボットの再起動。
- 読み込みに失敗したら、元の版に戻して再起動しません（動いているボットはそのまま）。直した版が `main` に入れば、次の確認で反映されます。
- 再起動のときに答えている途中の問いがあれば、その回答は途切れます。
- **更新のスクリプトと `deploy/` の systemd の設定は、自動では入れ替わりません。** root で動くものが、リポジトリの変更でそのまま書き換わらないようにするためです。`deploy/` が変わったときは、更新のログに注意が出るので、この節と 4 の手順で入れ直してください。
- 更新のログは `journalctl -u nro-bot-update` で見られます。

## 日々の操作

| 操作 | コマンド |
|---|---|
| 止める | `sudo systemctl stop nro-bot` |
| 再開する | `sudo systemctl start nro-bot` |
| プログラムをすぐ更新する | `sudo systemctl start nro-bot-update`（5 を設定した場合。設定していなければ `sudo -u nrobot git -C /srv/nro-bot/app pull && sudo -u nrobot /srv/nro-bot/venv/bin/pip install -r /srv/nro-bot/app/requirements.txt && sudo systemctl restart nro-bot`） |
| 自動の更新を止める | `sudo systemctl disable --now nro-bot-update.timer` |
| 更新のログを見る | `journalctl -u nro-bot-update` |
| 公開リポジトリをすぐ更新する | `sudo systemctl start nro-bot-sync` |
| 記録を見る | `sudo -u nrobot less /srv/nro-bot/logs/$(date +%Y-%m).jsonl` |

## 記録について

`/srv/nro-bot/logs/YYYY-MM.jsonl` に、問い（`question`、`followup`）、回答（`answer`：読んだファイル、開いた URL、トークン数、費用の概算、要したラウンド数）、担当者の書き込み（`advice`）、反応（`reaction`）が一行ずつ残ります。投稿者の ID と本文を含むので**非公開**です。公開側には、匿名化して集計したものだけを載せます。
