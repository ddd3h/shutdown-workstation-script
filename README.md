
# SSH多段ホップ停止ボット

このツールは、**triton**（ゲートサーバー）にSSHで接続し、そこから各workstation（例: orion, virgo, spicaなど）とその配下ノードを順にシャットダウンし、最後にtritonを停止します。  
設定は外部のYAMLファイルに切り出して管理でき、PyInstallerで単一バイナリにビルド可能です。

## 特徴
- **多段ホップSSH**（Paramiko + direct-tcpip）
- tritonは鍵認証、下流はパスワード認証（sudo対応）
- ノード停止後、**SSH到達性の消失を確認**してから親停止
- `--dry-run` で安全に動作確認
- 実行ログを `./logs/` に自動保存（標準出力/標準エラーをTee）
- 設定をYAMLファイルに分離（パスワードは環境変数や起動時入力可）
- PyInstallerで単一バイナリ化可能

## 必要要件
- Python 3.9+
- pipインストール:  
  ```bash
  pip install paramiko cryptography pyyaml
  ```

## セットアップ

1. `config.example.yaml` をコピーして `config.yaml` にリネーム
2. 実環境に合わせて編集

   * `gateway`: tritonの接続情報（ホスト名、ユーザー、鍵パス等）
   * `fleets`: 各workstationの接続情報とノード一覧

     * ノードを持たない場合は `nodes: []`
   * `password`:

     * `null` → 実行時プロンプト入力
     * `"env:VAR"` → 環境変数参照（推奨）
     * `"文字列"` → 平文（非推奨）
   * `power_off_cmd` や `node_shutdown_timeout` は環境に合わせ調整可

## 実行方法

```bash
# ドライラン（実行しない）
python shutdown_bot_configured.py --config ./config.yaml --dry-run

# 本番（確認プロンプトあり）
python shutdown_bot_configured.py --config ./config.yaml

# 設定値を一時上書き
python shutdown_bot_configured.py -c ./config.yaml --node-timeout 900 --poll-interval 10

# 子ノードが落ち切らなくても親を停止（保護解除）
python shutdown_bot_configured.py -c ./config.yaml --non-strict
```

## バイナリ化

事前にPyInstallerをインストール：

```bash
pip install pyinstaller
```

ビルド:

```bash
chmod +x build_binary.sh
./build_binary.sh shutdown_bot_configured.py
```

生成物:

```
dist/shutdown-bot
```

実行例:

```bash
./dist/shutdown-bot --config ./config.yaml
```

## ログ

* 実行ごとに `./logs/shutdown_YYYYmmdd_HHMMSS.log` を作成
* 画面に出た標準出力・標準エラーは全てログにも記録されます

## 注意

* 親サーバー停止後は配下ノードにアクセスできなくなります
* 必ず **ノード → 親 → 最後にtriton** の順で停止されます
* 本番前に `--dry-run` や限定的なテストで動作確認してください