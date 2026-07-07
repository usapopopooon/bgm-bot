# BGM Bot

Discordのボイスチャンネルに接続して、Jamendoのchill系ボーカルなし曲をランダム再生するBot。

操作はシンプルです。許可されたユーザーがVCに入った状態で `/play` を実行するとBotが接続し、表示された操作パネルから曲送りができます。接続中に `/play` を実行するとBotは切断します。BGM再生、音量、Stay、退出は既定では管理者のみ操作でき、管理者が `/member_commands` でメンバーにも許可できます。入退室音は既定ではOFFで、誰でも `/voice_event_sounds` またはパネルの入退室音ボタンで切り替えられます。

## Features

- `/play` で実行者がいるVCへの接続と切断を切り替え
- カテゴリは `chill` 固定
- Jamendo APIの `vocalinstrumental=instrumental` でボーカルなし曲だけを取得
- `/volume` コマンドで1%刻みの音量設定
- `/stay` / `/leave` コマンドでStayと退出を操作
- 管理者用 `/member_commands` コマンドでメンバーのコマンド利用を切り替え
- `/voice_event_sounds` コマンドまたはパネルボタンで入退室音を切り替え
- `一時停止` / `次の曲へ` / `入退室音` ボタンつき操作パネル
- VC接続時にスピーカーミュートを有効化して受信側の負荷を軽減
- VCにBot以外のユーザーがいなくなったら自動退出
- `Stay` がONのサーバーではVCが空でも接続を維持
- `Stay` がONで接続先VCが保存されている場合は、再起動後に自動で復帰接続
- 操作パネルにカテゴリのJamendo検索元と再生中の曲リンクを表示
- Jamendo APIは起動時と1日1回の定期更新で使用
- 再生中はPostgresに保存したメタデータから選曲
- カタログ内の曲を一周するまで重複を避け、一周完了時にJamendoから再取得
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
    discord_ui/          # /play、操作パネル、Select/Button
    guild_settings/      # ギルドごとの設定保存
    playback/            # VC接続、ffmpeg再生、再生ループ
      test_*.py
```

Botの基本フロー:

```text
/play
  -> 未接続なら実行者のVCへ接続
  -> 操作パネルを投稿
  -> chillカテゴリの未再生曲からランダム再生

カタログ内の曲を一周した場合
  -> Jamendo APIからchillの曲を再取得
  -> 取得できなければ再生履歴をリセットして同じリストの次周へ

/play
  -> 接続中ならVCから切断
  -> 保存済みVCをクリアし、StayをOFFにする

VCにBot以外のユーザーがいなくなった場合
  -> Stay OFFなら自動退出
  -> Stay ONなら接続を維持

Botの再起動後
  -> Stay ONで保存済みVCがあるサーバーへ復帰接続
  -> 保存カテゴリの再生を再開

毎日 04:00 Asia/Tokyo
  -> Jamendo APIからchillのボーカルなし曲を取得
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
| `SERVICE_PASSWORD_POSTGRES` | Coolify generated | Coolifyの自動生成パスワード。ローカルでは `.env` に設定 |
| `EXTERNAL_DATABASE_URL` | empty | 外部DBやCoolifyのDBリソースを使う場合の接続URL |
| `DATABASE_URL` | empty | `EXTERNAL_DATABASE_URL` の代替。直接実行時向け |
| `POSTGRES_HOST` | `127.0.0.1` | `DATABASE_URL` 未指定時のDBホスト |
| `POSTGRES_PORT` | `5432` | `DATABASE_URL` 未指定時のDBポート |
| `DISCORD_GUILD_ID` | empty | 開発用。指定するとslash commandを対象ギルドへ即時同期 |
| `JAMENDO_REFRESH_HOUR` | `4` | 毎日同期する時刻 |
| `REFRESH_TIMEZONE` | `Asia/Tokyo` | 同期時刻のタイムゾーン |
| `JAMENDO_LIMIT_PER_CATEGORY` | `200` | chill曲の取得上限。Jamendo API上限に合わせて最大200 |
| `SYNC_COMMANDS` | `true` | 起動時にslash commandを同期するか |

`.env.example`:

```env
DISCORD_TOKEN=
JAMENDO_CLIENT_ID=

# Local fallback. Coolify can generate SERVICE_PASSWORD_POSTGRES automatically.
SERVICE_PASSWORD_POSTGRES=change-me
# EXTERNAL_DATABASE_URL=postgresql://lofi:change-me@example.internal:5432/lofi

DISCORD_GUILD_ID=
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
- カテゴリ
- ボーカルなし条件で取得したことを示す内部フラグ

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
- `View Audit Log`
- `Send Messages`
- `Embed Links`

`View Audit Log` は、Discord上でBotをVCから手動切断した場合にユーザー意図の切断として扱うために使います。権限がない場合、Stay ONの予期しない切断は復帰対象として扱われます。確実にStayを止める場合は `/leave` または接続中の `/play` を使ってください。

開発中は `DISCORD_GUILD_ID` にテストサーバーIDを入れると、`/play` がすぐ反映されます。未指定の場合はグローバルコマンドとして同期されるため、Discord側の反映に時間がかかることがあります。

## Run Locally

`.env` を作成します。

```bash
cp .env.example .env
```

値を入れて起動します。

```bash
docker compose up --build
```

Botが起動したら、Discordで管理者がVCに入って `/play` を実行してください。メンバーにも操作を許可する場合は、管理者が `/member_commands` を実行します。

## Coolify Deployment

Coolifyでは `docker-compose.yml` を使うApplicationとして作成します。

設定する環境変数:

```env
DISCORD_TOKEN=...
JAMENDO_CLIENT_ID=...
```

`SERVICE_PASSWORD_POSTGRES` はCoolifyが自動生成します。BotとPostgresの両方で同じ値を使うため、通常は手入力不要です。自分で固定したい場合だけCoolify側で `SERVICE_PASSWORD_POSTGRES` を設定してください。

BotはPostgresコンテナのネットワーク名前空間を共有し、内部DBへは `127.0.0.1:5432` で接続します。Coolify上のCompose service名やnetwork aliasの名前解決に依存しません。

CoolifyのPostgresリソースなど外部DBを使う場合は、Coolify側で `EXTERNAL_DATABASE_URL` を設定してください。`EXTERNAL_DATABASE_URL` と `DATABASE_URL` が空の場合は、Botが `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` から接続URLを組み立てます。

必要なら開発/検証用に:

```env
DISCORD_GUILD_ID=...
```

BotはHTTPサーバーではないため、外部公開ポートやドメイン設定は不要です。

Composeには音声再生の安定性を優先したリソース制限を入れています。

| Service | Memory | CPU |
| --- | --- | --- |
| `bot` | 512MB | 1.0 |
| `postgres` | 256MB | 0.50 |

Postgresも小さめに調整しています。

- `shared_buffers=32MB`
- `work_mem=2MB`
- `maintenance_work_mem=16MB`
- `max_connections=10`

BotはDB接続を起動時にリトライするため、Coolify上でPostgresの起動が少し遅れてもそのまま待機します。

## Commands

Slash commands:

```text
/play
/volume percent:1..100
/stay
/leave
/member_commands
/voice_event_sounds
```

実行後に表示される操作パネル:

- 検索元: チル系のJamendo検索元リンク
- 再生中: 再生中の曲リンク
- ライセンス: 曲のライセンスURL（ある場合）
- `一時停止`: 再生を一時停止
- `次の曲へ`: 次の曲へ

`/play` `/volume` `/stay` `/leave` は既定では管理者のみ実行できます。管理者が `/member_commands` をONにすると、メンバーもこれらのコマンドを実行できます。`/member_commands` 自体は管理者のみ実行できます。`/voice_event_sounds` とパネルの入退室音ボタンは誰でも実行でき、入退室音のON/OFFを切り替えます。既定はOFFです。パネルがチャットの上に流れた時は、未接続の状態で `/play` を実行すると現在のチャンネルへ新しいパネルを投稿し、以後の曲情報更新先もその新しいパネルになります。接続中の `/play` と `/leave` はStayをOFFにして保存済みVCもクリアするため、次回起動時に自動復帰しません。`/stay` はStayのON/OFFを切り替えます。StayをOFFにした時、VCが空なら自動退出します。カテゴリはchill固定です。既存環境に `DEFAULT_CATEGORY` が残っていても無視されます。

VC接続時はDiscordのスピーカーミュート（`self_deaf`）を必ず有効にします。Botは他ユーザーの音声を受信しないため、VC内の人数が増えても受信処理の負荷を抑えられます。

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
- 音源URLは長期固定とは限らないため、毎日同期してメタデータを更新します。

## License and Attribution

Jamendo上の各曲は曲ごとにCreative Commonsライセンスが異なります。Botは操作パネルの再生中欄にJamendo共有URL、ライセンス欄にライセンスURLを表示します。

このBot自体はJamendoの音源ファイルを再配布しません。
