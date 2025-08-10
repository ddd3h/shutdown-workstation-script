
# SSH Shutdown Bot (Modern UI)

[Rich](https://github.com/Textualize/rich) を利用した、モダンなターミナルUIを備えた多段ホップSSHシャットダウン自動化ツールです。

## 特徴

* **多段ホップSSH**: ゲートサーバー（例: `triton`）に接続し、そこから各ワークステーションと配下ノードへジャンプして安全にシャットダウン。
* **安全な停止シーケンス**: 各ノードの停止を確認してから親ワークステーションを停止。
* **YAMLによる設定管理**: 外部YAMLファイルからすべての設定を読み込み可能。
* **モダンUI機能**:

  * 全体進行度を示す **プログレスバー**
  * 停止待機中の **スピナー** + ステータスメッセージ
  * **カラー付きログ**（任意で無効化可）
  * 実行前にターゲットを一覧表示する **テーブル**
* **ドライランモード** (`--dry-run`): 実行せずコマンド内容だけを確認。
* **環境変数でのパスワード指定**。
* **自動ログ保存**: 実行時の標準出力/標準エラーを `./logs/shutdown_YYYYmmdd_HHMMSS.log` に保存。
* **単一バイナリ化**: PyInstallerでRichを含めて配布可能。

## インストール

### 必要環境

* Python 3.8以上
* 必要なパッケージ:

  ```bash
  pip install paramiko cryptography pyyaml rich
  ```


## 設定ファイル

例: `config.yaml`

```yaml
power_off_cmd: "shutdown -h now"
node_shutdown_timeout: 600
poll_interval: 5

gateway:
  host: triton
  user: myuser
  pkey_path: "~/.ssh/id_ed25519"
  port: 22
  needs_sudo_password: false

fleets:
  - name: orion
    user: workstation_user
    password: "env:ORION_PW"
    nodes: ["orion01", "orion02", "orion03"]
    port: 22
    needs_sudo_password: true

  - name: spica
    user: spica_user
    password: null
    nodes: []
    port: 22
    needs_sudo_password: true
```


## 使い方

```bash
python shutdown_bot_modern.py --config ./config.yaml
```

### オプション

| オプション                | 説明                   |
| -------------------- | -------------------- |
| `--dry-run`          | 実際には実行せず、予定のコマンドだけ表示 |
| `--node-timeout 秒数`  | ノード停止確認のタイムアウトを上書き   |
| `--poll-interval 秒数` | 到達性チェックの間隔を上書き       |
| `--non-strict`       | ノード停止未確認でも親を停止する     |
| `--no-rich`          | Rich UIを無効化（プレーン出力）  |
| `--no-color-log`     | ログファイルにカラーコードを出力しない  |


## 実行例

シャットダウン手順を事前確認:

```bash
python shutdown_bot_modern.py -c config.yaml --dry-run
```

Rich UI付きで実行:

```bash
python shutdown_bot_modern.py -c config.yaml
```

プレーン出力モード:

```bash
python shutdown_bot_modern.py -c config.yaml --no-rich
```


## 単一バイナリ化

実行例：

```bash
pyinstaller --onefile \
  --name shutdown-bot \
  --collect-all paramiko \
  --collect-all cryptography \
  --collect-all rich \
  shutdown_bot_modern.py
```

生成されたバイナリは `dist/shutdown-bot` に出力されます。


## スクリプトを使用してバイナリ化する場合

#### 1. Modern版（`shutdown_bot_modern.py`）をバイナリ化する場合

```bash
./build_binary.sh
```

* 引数を省略すると、スクリプト内のデフォルト（`shutdown_bot_modern.py`）をビルドします。
* 成功すると `dist/shutdown-bot` が生成されます。

#### 2. 別のスクリプトを指定してビルドする場合

```bash
./build_binary.sh shutdown_bot_configured.py
```

* 引数にファイル名を渡せば、そのスクリプトをビルドします。

### 注意事項

* 実行前に必要なパッケージをインストールしてください：

  ```bash
  pip install pyinstaller paramiko cryptography pyyaml rich
  ```
* macOS / Linuxではスクリプトに実行権限が必要です：

  ```bash
  chmod +x build_binary.sh
  ```
* 出力されたバイナリは、依存ライブラリを含む**単一実行ファイル**です。