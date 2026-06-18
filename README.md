# Lofi Bot

Discordのボイスチャンネルに常駐して、Jamendoのランキング上位曲をカテゴリ別にランダム再生するBotです。

操作はシンプルに `/vc` だけです。ユーザーがVCに入った状態で `/vc` を実行するとBotが接続し、表示された操作パネルからランキングカテゴリをドロップダウンで選べます。

## Features

- `/vc` で実行者がいるVCへ接続
- ドロップダウンでランキングカテゴリを選択
- `lofi`, `chill`, `hiphop`, `relaxation`, `instrumental`, `beats`
- `Skip` / `Leave` ボタンつき操作パネル
- Jamendo APIは起動時と1日1回の定期更新で使用
- 再生中はPostgresに保存したメタデータから選曲
- 音源ファイルは保存せず、Jamendoの `audio` URLをffmpegで再生
- Coolify向けDocker Compose構成
- package by feature構成、テストはfeature配下にコロケーション

## Architecture

```text
src/lofi_bot/
  core/
    database.py          # Postgres接続と簡易マイグレーション
    logging.py

  features/
    catalog/             # Jamendo同期、カテゴリ定義、曲リポジトリ
      test_*.py
    discord_ui/          # /vc、操作パネル、Select/Button
    guild_settings/      # ギルドごとの設定保存
    playback/            # VC接続、ffmpeg再生、再生ループ
      test_*.py
```

Botの基本フロー:

```text
/vc
  -> 実行者のVCへ接続
  -> 操作パネルを投稿
  -> DBに保存済みの選択カテゴリからランダム再生

毎日 04:00 Asia/Tokyo
  -> Jamendo APIからカテゴリごとの上位曲を取得
  -> tracksテーブルへupsert
```

## Requirements

- Docker / Docker Compose
- Discord Bot Token
- Jamendo Developer Client ID
- Coolifyで動かす場合はDocker Compose対応のApplication

Botコンテナには `ffmpeg` を入れています。

## Environment Variables

必須:

| Name | Description |
| --- | --- |
| `DISCORD_TOKEN` | Discord Bot Token |
| `JAMENDO_CLIENT_ID` | Jamendo Developer Portalで取得するClient ID |

任意:

| Name | Default | Description |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | `SERVICE_PASSWORD_POSTGRES` or `change-me` | Compose内Postgresユーザー `lofi` のパスワード。ローカル上書き用 |
| `SERVICE_PASSWORD_POSTGRES` | Coolify generated | Coolifyの自動生成パスワード。`POSTGRES_PASSWORD` が未指定のとき使用 |
| `DISCORD_GUILD_ID` | empty | 開発用。指定するとslash commandを対象ギルドへ即時同期 |
| `DEFAULT_CATEGORY` | `lofi` | 初期カテゴリ |
| `JAMENDO_REFRESH_HOUR` | `4` | 毎日同期する時刻 |
| `REFRESH_TIMEZONE` | `Asia/Tokyo` | 同期時刻のタイムゾーン |
| `JAMENDO_LIMIT_PER_CATEGORY` | `200` | カテゴリごとの取得上限。Jamendo API上限に合わせて最大200 |
| `SYNC_COMMANDS` | `true` | 起動時にslash commandを同期するか |

`.env.example`:

```env
DISCORD_TOKEN=
JAMENDO_CLIENT_ID=

# Local override. Coolify can generate SERVICE_PASSWORD_POSTGRES automatically.
POSTGRES_PASSWORD=change-me

DISCORD_GUILD_ID=
DEFAULT_CATEGORY=lofi
JAMENDO_REFRESH_HOUR=4
REFRESH_TIMEZONE=Asia/Tokyo
JAMENDO_LIMIT_PER_CATEGORY=200
SYNC_COMMANDS=true
```

## Jamendo Setup

1. Jamendo Developer Portalでアプリを作成します。
2. Client IDを取得します。
3. Coolifyまたは `.env` の `JAMENDO_CLIENT_ID` に設定します。

JamendoのAPIレスポンスから以下を保存します。

- 曲ID
- タイトル
- アーティスト
- `audio` URL
- Jamendo共有URL
- Creative CommonsライセンスURL
- タグ
- ランキングカテゴリ

音源ファイル自体はDBやローカルストレージに保存しません。

## Discord Setup

Discord Developer PortalでBotを作成し、Bot Tokenを取得します。

Invite URLには以下のscope/権限を付与してください。

Scopes:

- `bot`
- `applications.commands`

Bot Permissions:

- `Connect`
- `Speak`
- `Use Voice Activity`
- `Send Messages`
- `Embed Links`

開発中は `DISCORD_GUILD_ID` にテストサーバーIDを入れると、`/vc` がすぐ反映されます。未指定の場合はグローバルコマンドとして同期されるため、Discord側の反映に時間がかかることがあります。

## Run Locally

`.env` を作成します。

```bash
cp .env.example .env
```

値を入れて起動します。

```bash
docker compose up --build
```

Botが起動したら、DiscordでVCに入って `/vc` を実行してください。

## Coolify Deployment

Coolifyでは `docker-compose.yml` を使うApplicationとして作成します。

設定する環境変数:

```env
DISCORD_TOKEN=...
JAMENDO_CLIENT_ID=...
```

`POSTGRES_PASSWORD` は未設定でも構いません。CoolifyではCompose内の `SERVICE_PASSWORD_POSTGRES` からDBパスワードを自動生成し、`bot` と `db` の両方で同じ値を使います。自分で固定したい場合だけ `POSTGRES_PASSWORD` を設定してください。

必要なら開発/検証用に:

```env
DISCORD_GUILD_ID=...
```

BotはHTTPサーバーではないため、外部公開ポートやドメイン設定は不要です。

Composeには低めのリソース制限を入れています。

| Service | Memory | CPU |
| --- | --- | --- |
| `bot` | 256MB | 0.50 |
| `db` | 256MB | 0.50 |

Postgresも小さめに調整しています。

- `shared_buffers=64MB`
- `work_mem=4MB`
- `maintenance_work_mem=32MB`
- `max_connections=20`

## Commands

ユーザー向けコマンドは1つだけです。

```text
/vc
```

実行後に表示される操作パネル:

- Category select: `lofi`, `chill`, `hiphop`, `relaxation`, `instrumental`, `beats`
- `Skip`: 次の曲へ
- `Leave`: VCから退出

カテゴリの直指定コマンドはありません。操作はパネルのドロップダウンに寄せています。

## Development

Python 3.12を使います。

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Lint:

```bash
ruff check .
```

Test:

```bash
pytest -q
```

Docker build:

```bash
docker build -t lofi-bot:check .
```

Compose config check:

```bash
DISCORD_TOKEN=x JAMENDO_CLIENT_ID=x POSTGRES_PASSWORD=x docker compose config
```

## CI

GitHub Actionsで以下を実行します。

- `ruff check .`
- `pytest -q`

Workflow:

```text
.github/workflows/ci.yml
```

実行タイミング:

- `push`
- `pull_request`
- `workflow_dispatch`

## Operational Notes

- Jamendo APIが一時的に0件を返したカテゴリでは、既存キャッシュを保持します。
- 再生に失敗した曲は失敗回数を記録し、一定回数で無効化します。
- 起動直後に曲キャッシュが空の場合は、同期完了後に再生を再試行します。
- `chill` と `relaxation` はタグが近いため、上位曲が被ることがあります。
- 音源URLは長期固定とは限らないため、毎日同期してメタデータを更新します。

## License and Attribution

Jamendo上の各曲は曲ごとにCreative Commonsライセンスが異なります。Botは操作パネルのNow PlayingにJamendo共有URLとライセンスURLを表示します。

このBot自体はJamendoの音源ファイルを再配布しません。
