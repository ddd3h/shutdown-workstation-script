#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

"""
SSH Shutdown Bot (config-driven, modern UI)
==========================================
- YAML config, multi-hop SSH (Paramiko)
- Wait-for-node-down protection
- Auto logging (Tee to ./logs/)
- Optional modern TUI with Rich: progress bars, tables, status spinners
"""

# ---- ログ保存 (実行ごとにファイル作成) ----
import sys as _sys, os as _os
from datetime import datetime as _dt
try:
    _log_dir = _os.path.join(_os.path.dirname(__file__) if "__file__" in globals() else ".", "logs")
    _os.makedirs(_log_dir, exist_ok=True)
except Exception:
    _log_dir = "."
_ts = _dt.now().strftime("%Y%m%d_%H%M%S")
_log_path = _os.path.join(_log_dir, f"shutdown_{_ts}.log")
_log_fh = open(_log_path, "a", encoding="utf-8")
class _Tee:
    def __init__(self, *streams): self.streams = streams
    def write(self, data):
        for s in self.streams:
            try:
                s.write(data); s.flush()
            except Exception:
                pass
    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass
_sys.stdout = _Tee(_sys.stdout, _log_fh)
_sys.stderr = _Tee(_sys.stderr, _log_fh)
print(f"[LOG] 出力を保存します: {_log_path}")

import argparse
import getpass
import socket
import time
from dataclasses import dataclass
from typing import List, Optional, Dict

import os
import paramiko
try:
    import yaml  # PyYAML
except Exception as e:
    print("[注意] PyYAML が見つかりません。`pip install pyyaml` を実行してください。", file=_sys.stderr)
    raise

# Rich は任意（未インストールならプレーン出力）
_HAS_RICH = True
try:
    from rich.console import Console
    from rich.table import Table
    from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn, TimeElapsedColumn, SpinnerColumn
    from rich.traceback import install as rich_traceback_install
    rich_traceback_install(show_locals=False)
except Exception:
    _HAS_RICH = False
    Console = None  # type: ignore

# =========================
# モデル
# =========================
@dataclass
class Gateway:
    host: str
    user: str
    pkey_path: str = "~/.ssh/id_ed25519"
    port: int = 22
    needs_sudo_password: bool = False
    sudo_user: Optional[str] = None

@dataclass
class Fleet:
    name: str
    user: str
    password: Optional[str]  # None -> prompt, "env:FOO" -> 環境変数参照, 文字列 -> そのまま
    nodes: List[str]
    port: int = 22
    needs_sudo_password: bool = True

# 実行する停止コマンド（環境に合わせて変更可／configでも上書き可）
POWER_OFF_CMD = "shutdown -h now"

# 親を止める前に子ノードのダウンを確認するためのデフォルト値（configでも上書き可）
DEFAULT_NODE_SHUTDOWN_TIMEOUT = 600   # 秒
DEFAULT_POLL_INTERVAL = 5             # 秒

# =========================
# SSHユーティリティ
# =========================
class SSH:
    def __init__(self, client: paramiko.SSHClient, transport: paramiko.Transport):
        self.client = client
        self.transport = transport
    def close(self):
        try:
            self.client.close()
        except Exception:
            pass

def load_pkey(path: str) -> paramiko.PKey:
    from os.path import expanduser
    p = expanduser(path)
    try:
        return paramiko.Ed25519Key.from_private_key_file(p)
    except paramiko.PasswordRequiredException:
        pw = getpass.getpass("秘密鍵のパスフレーズ: ")
        try:
            return paramiko.Ed25519Key.from_private_key_file(p, password=pw)
        except Exception:
            return paramiko.RSAKey.from_private_key_file(p, password=pw)
    except Exception:
        try:
            return paramiko.RSAKey.from_private_key_file(p)
        except Exception as e:
            raise e

def connect_host(host: str, user: str, port: int = 22, *,
                 pkey: Optional[paramiko.PKey] = None,
                 password: Optional[str] = None,
                 sock=None) -> SSH:
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(
        hostname=host,
        port=port,
        username=user,
        pkey=pkey,
        password=password,
        sock=sock,
        allow_agent=True,
        look_for_keys=True,
        timeout=20,
    )
    return SSH(cli, cli.get_transport())

def open_direct_tcpip_channel(transport: paramiko.Transport, dest_host: str, dest_port: int) -> socket.socket:
    return transport.open_channel(
        kind="direct-tcpip",
        dest_addr=(dest_host, dest_port),
        src_addr=("127.0.0.1", 0),
    )

def is_ssh_reachable_via_transport(transport: paramiko.Transport, host: str, port: int, *, timeout: float = 5.0) -> bool:
    try:
        ch = transport.open_channel(
            kind="direct-tcpip",
            dest_addr=(host, port),
            src_addr=("127.0.0.1", 0),
            timeout=timeout,
        )
        try:
            ch.close()
        except Exception:
            pass
        return True
    except Exception:
        return False

def wait_for_host_down_via_transport(transport: paramiko.Transport, host: str, port: int, *,
                                     timeout_sec: int, poll_interval: int,
                                     console: Optional[Console] = None) -> bool:
    deadline = time.time() + timeout_sec
    interval = max(1, poll_interval)
    if console:
        status = console.status(f"[bold]Waiting for {host} to go down[/bold] (timeout {timeout_sec}s)", spinner="dots")
        status.start()
    else:
        print(f"    ・・ {host} の停止を待機中（最大 {timeout_sec}s）…")
    try:
        while time.time() < deadline:
            if not is_ssh_reachable_via_transport(transport, host, port):
                if console: console.log(f"[green]OK[/green] {host} is unreachable (assumed powered off)")
                else: print(f"    OK: {host} は到達不能（停止済みと判断）")
                return True
            time.sleep(interval)
        if console:
            console.log(f"[yellow]Timeout[/yellow]: {host} still reachable") 
        else:
            print(f"    タイムアウト: {host} はまだ到達可能です")
        return False
    finally:
        if console:
            status.stop()

def run_remote_command(client: paramiko.SSHClient, command: str, *,
                       sudo: bool = False,
                       sudo_password: Optional[str] = None,
                       timeout: int = 30,
                       console: Optional[Console] = None) -> int:
    if sudo:
        command = f"sudo -S -p '' {command}"
    if console:
        console.log(f"$ {command}")
    stdin, stdout, stderr = client.exec_command(command, get_pty=True, timeout=timeout)
    if sudo and sudo_password is not None:
        stdin.write(sudo_password + "\n")
        stdin.flush()
    exit_status = stdout.channel.recv_exit_status()
    out = stdout.read().decode(errors="ignore")
    err = stderr.read().decode(errors="ignore")
    if out:
        (console.log(out.strip()) if console else print(f"[STDOUT] {out.strip()}"))
    if err:
        (console.log(f"[red]{err.strip()}[/red]") if console else print(f"[STDERR] {err.strip()}"))
    return exit_status

def shutdown_host(tag: str, client: paramiko.SSHClient, *,
                  needs_sudo_password: bool,
                  sudo_password: Optional[str],
                  dry_run: bool,
                  console: Optional[Console] = None) -> None:
    global POWER_OFF_CMD
    cmd = POWER_OFF_CMD
    (console.log(f"→ {tag}: {cmd}") if console else print(f"→ {tag}: {cmd}"))
    if dry_run:
        (console.log(f"DRY-RUN: 実行しません: {tag}") if console else print(f"DRY-RUN: 実行しません: {tag}"))
        return
    code = run_remote_command(client, cmd, sudo=needs_sudo_password, sudo_password=sudo_password, console=console)
    if code != 0:
        (console.log(f"[yellow]警告[/yellow]: {tag} のshutdownコマンドが終了コード {code} を返しました") if console else print(f"警告: {tag} のshutdownコマンドが終了コード {code} を返しました"))

# =========================
# 設定ロード
# =========================
def _resolve_password(value: Optional[str], prompt_label: str) -> Optional[str]:
    if value is None:
        return getpass.getpass(prompt_label)
    if isinstance(value, str) and value.startswith("env:"):
        env_key = value.split(":", 1)[1]
        v = os.environ.get(env_key)
        if v is None:
            raise RuntimeError(f"環境変数 {env_key} が未設定です（{prompt_label}）")
        return v
    return value

def load_config(path: str):
    global POWER_OFF_CMD, DEFAULT_NODE_SHUTDOWN_TIMEOUT, DEFAULT_POLL_INTERVAL
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    # poweroff cmd / wait パラメータ
    POWER_OFF_CMD = cfg.get("power_off_cmd", POWER_OFF_CMD)
    DEFAULT_NODE_SHUTDOWN_TIMEOUT = int(cfg.get("node_shutdown_timeout", DEFAULT_NODE_SHUTDOWN_TIMEOUT))
    DEFAULT_POLL_INTERVAL = int(cfg.get("poll_interval", DEFAULT_POLL_INTERVAL))

    gw_raw = cfg.get("gateway") or {}
    gw = Gateway(
        host=gw_raw["host"],
        user=gw_raw["user"],
        pkey_path=gw_raw.get("pkey_path", "~/.ssh/id_ed25519"),
        port=int(gw_raw.get("port", 22)),
        needs_sudo_password=bool(gw_raw.get("needs_sudo_password", False)),
        sudo_user=gw_raw.get("sudo_user"),
    )
    fleets: List[Fleet] = []
    for it in (cfg.get("fleets") or []):
        fleets.append(Fleet(
            name=it["name"],
            user=it["user"],
            password=it.get("password"),
            nodes=it.get("nodes", []),
            port=int(it.get("port", 22)),
            needs_sudo_password=bool(it.get("needs_sudo_password", True)),
        ))
    return gw, fleets

# =========================
# メイン
# =========================
def main():
    ap = argparse.ArgumentParser(description="多段ホップでノード→親→…→tritonを順停止（YAML設定版, Rich対応）")
    ap.add_argument("--config", "-c", required=True, help="設定ファイル（YAML）へのパス")
    ap.add_argument("--dry-run", action="store_true", help="コマンドを表示するだけで実行しない")
    ap.add_argument("--node-timeout", type=int, default=None, help="各ノードの停止待ちタイムアウト(秒)（設定の上書き）")
    ap.add_argument("--poll-interval", type=int, default=None, help="到達性チェックの間隔(秒)（設定の上書き）")
    ap.add_argument("--non-strict", action="store_true", help="ノードの完全停止が確認できなくても親を停止する")
    ap.add_argument("--no-rich", action="store_true", help="Rich UI を無効化（プレーン出力）")
    ap.add_argument("--no-color-log", action="store_true", help="ログファイルにカラーコードを出さない")
    args = ap.parse_args()

    # Rich setup
    console: Optional[Console] = None
    use_rich = _HAS_RICH and (not args.no_rich)
    if use_rich:
        console = Console(stderr=True, no_color=args.no_color_log)

    gw, fleets = load_config(args.config)
    node_timeout = DEFAULT_NODE_SHUTDOWN_TIMEOUT if args.node_timeout is None else int(args.node_timeout)
    poll_interval = DEFAULT_POLL_INTERVAL if args.poll_interval is None else int(args.poll_interval)

    # パスワード収集
    fleet_pw_map: Dict[str, str] = {}
    for f in fleets:
        fleet_pw_map[f.name] = _resolve_password(f.password, f"[{f.name}] のログイン/ sudo 用パスワード: ")

    gw_sudo_pw: Optional[str] = None
    if gw.needs_sudo_password:
        gw_sudo_pw = getpass.getpass("[triton] のsudoパスワード: ")

    # 対象一覧を表示（Rich Table）
    if console:
        table = Table(title="Targets", show_lines=False)
        table.add_column("Workstation", style="bold")
        table.add_column("User")
        table.add_column("Nodes") 
        for f in fleets:
            nodes_s = ",".join(f.nodes) if f.nodes else "(単体)"
            table.add_row(f.name, f.user, nodes_s)
        console.print(table)
    else:
        print("\n=== 対象一覧 ===")
        for f in fleets:
            nodes_s = ",".join(f.nodes) if f.nodes else "(単体)"
            print(f"- {f.name}: nodes={nodes_s} (user={f.user})")
        print("最後に triton を停止します。\n")

    if not args.dry_run:
        confirm = input("本当にシャットダウンしますか？ (YESと入力): ")
        if confirm.strip() != "YES":
            print("中止しました。")
            return

    # 1) tritonへ鍵で接続
    if console: console.log("[bold]Connecting to triton…[/bold]")
    else: print("\n[1] triton に接続中…")
    pkey = load_pkey(gw.pkey_path)
    gw_conn = connect_host(gw.host, gw.user, gw.port, pkey=pkey)
    if console: console.log("[green]Connected[/green]: triton OK")
    else: print("接続: triton OK")

    # プログレスバー準備
    total_steps = 1  # 最後の triton 停止
    for f in fleets:
        total_steps += len(f.nodes) + 1  # 各ノード + 親
    progress_ctx = None
    if console:
        progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=False,
        )
        progress_ctx = progress
        task_id = progress.add_task("Shutting down fleets", total=total_steps)
    else:
        progress = None
        task_id = None

    def step_advance(n=1):
        if progress_ctx is not None and task_id is not None:
            progress_ctx.update(task_id, advance=n)

    try:
        if progress_ctx: progress_ctx.start()
        # 2) 各workstationを順に処理
        for f in fleets:
            pw = fleet_pw_map[f.name]
            if console: console.log(f"[bold]Hop to {f.name}[/bold]")
            else: print(f"\n[2] {f.name} にジャンプ…")
            sock_ws = open_direct_tcpip_channel(gw_conn.transport, f.name, f.port)
            ws = connect_host(f.name, f.user, f.port, password=pw, sock=sock_ws)
            if console: console.log(f"[green]Connected[/green]: {f.name} OK")
            else: print(f"接続: {f.name} OK")
            try:
                parent_skip = False
                for node in f.nodes:
                    if console: console.log(f"→ {f.name} 経由で [bold]{node}[/bold] へ…")
                    else: print(f"  -> {f.name} 経由で {node} にジャンプ…")
                    sock_node = open_direct_tcpip_channel(ws.transport, node, f.port)
                    node_cli = connect_host(node, f.user, f.port, password=pw, sock=sock_node)
                    try:
                        shutdown_host(node, node_cli.client,
                                      needs_sudo_password=f.needs_sudo_password,
                                      sudo_password=pw,
                                      dry_run=args.dry_run,
                                      console=console)
                    finally:
                        node_cli.close()
                        if not args.dry_run:
                            ok = wait_for_host_down_via_transport(ws.transport, node, f.port,
                                                                  timeout_sec=node_timeout,
                                                                  poll_interval=poll_interval,
                                                                  console=console)
                            if not ok and not args.non_strict:
                                msg = f"[保護] {node} の完全停止が確認できないため、{f.name} の停止をスキップします。--non-strict 指定で無視可。"
                                (console.log(f"[yellow]{msg}[/yellow]") if console else print(msg))
                                parent_skip = True
                        step_advance(1)
                        time.sleep(0.2)

                # 親workstationを停止
                if parent_skip:
                    (console.log(f"[yellow][保護] {f.name} の停止はスキップされました（子ノード未停止の可能性）。[/yellow]") if console else print(f"[保護] {f.name} の停止はスキップされました（子ノード未停止の可能性）。"))
                else:
                    shutdown_host(f.name, ws.client,
                                  needs_sudo_password=f.needs_sudo_password,
                                  sudo_password=pw,
                                  dry_run=args.dry_run,
                                  console=console)
                step_advance(1)
            finally:
                ws.close()
                time.sleep(0.2)

        # 3) 最後に triton を停止
        if console: console.log("[bold]Shutting down triton…[/bold]")
        else: print("\n[3] triton を停止…")
        shutdown_host("triton", gw_conn.client,
                      needs_sudo_password=gw.needs_sudo_password,
                      sudo_password=gw_sudo_pw,
                      dry_run=args.dry_run,
                      console=console)
        step_advance(1)

    finally:
        if progress_ctx: progress_ctx.stop()
        gw_conn.close()
        (console.log("[green]完了。[/green]") if console else print("完了。"))

if __name__ == "__main__":
    main()
