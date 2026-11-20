#!/bin/bash
# GitHub の main に更新があれば取得し、ボットを再起動する。
#
# root で動かす（再起動のため）。git と pip は nrobot の権限で行う。
# このスクリプトは /usr/local/sbin に手でコピーして使い、自動では更新しない
# （リポジトリの変更が、そのまま root で実行されないようにするため）。
set -euo pipefail

APP=/srv/nro-bot/app
VENV=/srv/nro-bot/venv
SERVICE=nro-bot.service
as_bot() { runuser -u nrobot -- "$@"; }

as_bot git -C "$APP" fetch --quiet origin main
OLD=$(as_bot git -C "$APP" rev-parse HEAD)
NEW=$(as_bot git -C "$APP" rev-parse FETCH_HEAD)
if [ "$OLD" = "$NEW" ]; then
    exit 0
fi

echo "更新を見つけた：${OLD:0:7} -> ${NEW:0:7}"
as_bot git -C "$APP" reset --quiet --hard "$NEW"

rollback() {
    echo "更新に失敗したので ${OLD:0:7} に戻す。ボットは再起動しない" >&2
    as_bot git -C "$APP" reset --quiet --hard "$OLD"
    as_bot "$VENV/bin/pip" install --quiet -r "$APP/requirements.txt" || true
    exit 1
}

# ライブラリが変わったときだけ入れ直す
if ! as_bot git -C "$APP" diff --quiet "$OLD" "$NEW" -- requirements.txt; then
    echo "requirements.txt が変わったので、ライブラリを入れ直す"
    as_bot "$VENV/bin/pip" install --quiet -r "$APP/requirements.txt" || rollback
fi

# 読み込めることを確かめてから再起動する
(cd "$APP" && as_bot "$VENV/bin/python" -c "import nro_bot.bot, nro_bot.agent, nro_bot.tools") || rollback

if systemctl is-enabled --quiet "$SERVICE"; then
    systemctl restart "$SERVICE"
    echo "ボットを再起動した（${NEW:0:7}）"
fi

# 自分自身や systemd の設定が変わったときは、手で入れ直す必要があることを知らせる
if ! as_bot git -C "$APP" diff --quiet "$OLD" "$NEW" -- deploy/; then
    echo "注意：deploy/ が変わった。docs/setup.md に従って、手で入れ直すこと" >&2
fi
