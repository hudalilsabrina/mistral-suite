#!/usr/bin/env python3
"""Mistral Suite - CLI: factory akun Mistral + panen API key (mstrl_).

Command:
  harvest [n]   Buat n akun (default 1) + panen API key
  test          Uji semua API key tersimpan (chat ke model free tier)
  report        Ringkasan akun
  sync          Inject API key ke 9router
  probe         Cek apakah API Mistral hidup
"""
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rich.console import Console
from rich.table import Table
from rich import box

from src import mistral

C = Console()
ROOT = Path(__file__).resolve().parent
ACCOUNTS = ROOT / "accounts.txt"


def _load_accounts():
    if not ACCOUNTS.exists():
        return []
    out = []
    for line in ACCOUNTS.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split(":")
        if len(parts) >= 3:
            out.append({"email": parts[0], "password": parts[1], "apikey": parts[2],
                        "status": parts[3] if len(parts) > 3 else ""})
    return out


def cmd_harvest(n):
    ok = 0
    for i in range(1, n + 1):
        C.print(f"[cyan]=== Akun {i}/{n} ===[/]")
        r = mistral.harvest_mistral()
        if r.get("ok"):
            ok += 1
        else:
            C.print(f"[yellow]  gagal: {r.get('error')}[/]")
    C.print(f"\n[bold]Selesai: {ok}/{n} sukses[/]")


def cmd_test():
    accts = _load_accounts()
    if not accts:
        C.print("[yellow]Belum ada akun.[/]")
        return
    C.print(f"[cyan]Uji {len(accts)} API key...[/]")
    t = Table(box=box.ROUNDED, title="Test API key")
    t.add_column("Email", style="cyan")
    t.add_column("Status")
    t.add_column("Model", style="green")
    t.add_column("Balasan", style="dim")
    for a in accts:
        try:
            d = mistral.api_chat(a["apikey"])
            msg = d.get("choices", [{}])[0].get("message", {}).get("content", "")
            t.add_row(a["email"][:26], "[green]OK[/]", d.get("model", "-"), msg[:24])
        except Exception as e:
            t.add_row(a["email"][:26], "[red]FAIL[/]", "-", str(e)[:40])
    C.print(t)


def cmd_report():
    accts = _load_accounts()
    C.print(f"[bold]Total akun: {len(accts)}[/]")
    if not accts:
        return
    t = Table(box=box.ROUNDED)
    t.add_column("#", justify="right")
    t.add_column("Email", style="cyan")
    t.add_column("API key")
    t.add_column("Status", style="green")
    for i, a in enumerate(accts, 1):
        t.add_row(str(i), a["email"], a["apikey"][:18] + "...", a.get("status", "-"))
    C.print(t)


def cmd_probe():
    try:
        req = urllib.request.Request("https://api.mistral.ai/v1/models")
        with urllib.request.urlopen(req, timeout=20) as r:
            C.print(f"[green]API hidup — status {r.status}[/]")
    except urllib.error.HTTPError as e:
        C.print(f"[yellow]API merespon {e.code} (hidup)[/]")
    except Exception as e:
        C.print(f"[red]API bermasalah: {e}[/]")


def cmd_retry_mint():
    """Coba mint ulang key untuk akun yang sudah terverifikasi tapi belum punya key."""
    accts = _load_accounts()
    pending = [a for a in accts if not a["apikey"] or a.get("status") == "VERIFIED_NOKEY"]
    if not pending:
        C.print("[green]Tidak ada akun pending.[/]")
        return
    C.print(f"[cyan]Retry mint {len(pending)} akun...[/]")
    ok = 0
    for i, a in enumerate(pending, 1):
        C.print(f"[cyan]=== {i}/{len(pending)}: {a['email']} ===[/]")
        key, info = mistral.mint_key(a["email"], a["password"], "farm")
        if key:
            ok += 1
            C.print(f"[green]  KEY: {key[:16]}...[/]")
            _update_account(a["email"], key, "KEYED")
        else:
            C.print(f"[yellow]  gagal: {info[:100]}[/]")
        time.sleep(8)
    C.print(f"\n[bold]Berhasil mint: {ok}/{len(pending)}[/]")


def _update_account(email, key, status):
    """Update baris akun (ganti key + status)."""
    lines = ACCOUNTS.read_text().splitlines()
    out = []
    for l in lines:
        parts = l.split(":")
        if parts and parts[0] == email:
            out.append(f"{parts[0]}:{parts[1]}:{key}:{status}")
        else:
            out.append(l)
    ACCOUNTS.write_text("\n".join(out) + "\n")


def cmd_sync():
    from src import router9
    accts = _load_accounts()
    if not accts:
        C.print("[yellow]Belum ada akun.[/]")
        return
    accounts = [{"email": a["email"], "key": a["apikey"]} for a in accts]
    C.print(f"[cyan]Sync {len(accounts)} key ke 9router (node mstrlfarm)...[/]")
    r = router9.ingest_gateway(name="mstrlfarm", prefix="mstrlfarm",
                               base_url=mistral.API, accounts=accounts)
    if r.get("ok"):
        C.print(f"[bold]{r['added']}/{r['total']} ditambahkan, "
                f"{r['valid']} valid (node {r['node']})[/]")
    else:
        C.print(f"[red]gagal: {r.get('error')}[/]")


def main():
    ap = argparse.ArgumentParser(prog="mistral", description="Mistral Suite")
    sub = ap.add_subparsers(dest="cmd")
    h = sub.add_parser("harvest"); h.add_argument("n", nargs="?", type=int, default=1)
    sub.add_parser("test")
    sub.add_parser("report")
    sub.add_parser("sync")
    sub.add_parser("probe")
    sub.add_parser("retry-mint")
    a = ap.parse_args()
    if a.cmd == "harvest":
        cmd_harvest(a.n)
    elif a.cmd == "test":
        cmd_test()
    elif a.cmd == "report":
        cmd_report()
    elif a.cmd == "sync":
        cmd_sync()
    elif a.cmd == "probe":
        cmd_probe()
    elif a.cmd == "retry-mint":
        cmd_retry_mint()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
