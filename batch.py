#!/usr/bin/env python3
"""Mistral batch runner - buat banyak akun + panen key, resume-safe.

Contoh:
  .venv/bin/python batch.py 10
  .venv/bin/python batch.py 50 --delay 15
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rich.console import Console
from src import mistral

C = Console()
ROOT = Path(__file__).resolve().parent
ACCOUNTS = ROOT / "accounts.txt"


def keyed_count():
    try:
        return sum(1 for l in ACCOUNTS.read_text().splitlines() if l.strip() and "mstrl_" in l)
    except FileNotFoundError:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("n", type=int)
    ap.add_argument("--delay", type=int, default=10)
    a = ap.parse_args()

    start = keyed_count()
    C.print(f"[cyan]Mulai: {start} key tersimpan. Target: +{a.n}[/]")
    ok = 0
    t0 = time.time()
    for i in range(1, a.n + 1):
        C.print(f"[cyan]=== Akun {i}/{a.n} ===[/]")
        r = mistral.harvest_mistral()
        if r.get("ok"):
            ok += 1
            C.print(f"[green]  OK {r['email']} | key {r.get('apikey','')[:16]}...[/]")
        else:
            C.print(f"[yellow]  gagal: {r.get('error')}[/]")
        if i < a.n:
            time.sleep(a.delay)
    C.print(f"\n[bold]Selesai: {ok}/{a.n} sukses dalam {round(time.time()-t0)}s "
            f"(total key: {keyed_count()})[/]")


if __name__ == "__main__":
    main()
