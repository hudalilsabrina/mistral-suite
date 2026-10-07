"""Mistral engine - buat akun Mistral + panen API key (mstrl_).

Chain (pure HTTP, tanpa browser) — semua terbukti:
  1. buat inbox tempik (tempik, bukan tempmail.lol)
  2. Ory register: GET /self-service/registration/api -> POST ui.action
     -> session_token (ory_st_...)
  3. verify: GET /self-service/verification/api -> POST (method=code)
     -> kode dikirim ke email
  4. baca kode dari inbox + ambil FLOW ID dari link email
     (PENTING: Ory mengikat kode ke flow di link email, bukan flow API)
  5. POST /self-service/verification?flow=<flow_link> {code} -> state=passed_challenge
  6. login browser flow -> cookie ory_session_* -> GET /api/users/me (csrftoken)
     -> POST /api/billing/api-keys -> key mstrl_...

Model free tier: ministral-8b-latest, open-mistral-nemo, mistral-tiny.
Sumber mail: https://github.com/hirotomasato/tempik
"""
import json
import random
import re
import string
import subprocess
import time
import urllib.parse
import urllib.request
import http.cookiejar as hcj
from typing import Any, Dict, Optional, Tuple

from rich.console import Console

from .tempmail import TempikClient
from .inboxstore import save as save_inbox

C = Console()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")

AUTH = "https://auth.mistral.ai"
CONSOLE = "https://console.mistral.ai"
API = "https://api.mistral.ai/v1"
FREE_MODELS = ["ministral-8b-latest", "open-mistral-nemo", "mistral-tiny"]


def _http(url, method="GET", data=None, headers=None, timeout=30):
    h = ["-H", f"User-Agent: {UA}", "-H", "Accept: application/json"]
    if headers:
        for k, v in headers.items():
            h += ["-H", f"{k}: {v}"]
    args = ["curl", "-s", "--max-time", str(timeout), "-w", "\n%{http_code}"] + h
    if method == "POST":
        args += ["-X", "POST"]
    if data is not None:
        args += ["--data", urllib.parse.urlencode(data) if isinstance(data, dict) else data]
    args.append(url)
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout + 15)
    out = r.stdout.rsplit("\n", 1)
    code = int(out[-1]) if out[-1].isdigit() else 0
    return code, (out[0] if len(out) > 1 else r.stdout)


def _rand_password(n: int = 12) -> str:
    core = "".join(random.choices(string.ascii_letters + string.digits, k=n))
    return f"Mx#frm{core}!7"


def ory_register(email: str, pw: str) -> Optional[str]:
    s, body = _http(f"{AUTH}/self-service/registration/api")
    if s != 200:
        return None
    d = json.loads(body)
    csrf = [n["attributes"].get("value", "") for n in d["ui"]["nodes"]
            if n["attributes"].get("name") == "csrf_token"][0]
    s, body = _http(d["ui"]["action"], "POST",
                    {"csrf_token": csrf, "traits.email": email, "password": pw,
                     "method": "password", "traits.name.first": "Quart",
                     "traits.name.last": "Farm"})
    if s != 200:
        return None
    return json.loads(body).get("session_token")


def trigger_verify(st: str, email: str) -> Optional[str]:
    s, body = _http(f"{AUTH}/self-service/verification/api",
                    headers={"X-Session-Token": st})
    if s != 200:
        return None
    d = json.loads(body)
    flow = d["id"]
    s, body = _http(d["ui"]["action"], "POST",
                    {"csrf_token": "", "email": email, "method": "code"},
                    {"X-Session-Token": st})
    if s != 200:
        return None
    return flow


def poll_inbox(tc: TempikClient, email: str, timeout: int = 180) -> Tuple[Optional[str], Optional[str]]:
    """Return (code, flow_from_link). Flow dari link email WAJIB dipakai."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            for m in tc.get_messages(email) or []:
                raw = (m.get("body") or "") + (m.get("html") or "") + (m.get("subject") or "")
                mm = re.search(r"verification\?code=(\d{6})&flow=([\w-]+)", raw)
                if mm:
                    return mm.group(1), mm.group(2)
                fm = re.search(r"flow=([\w-]{8,})", raw)
                codes = re.findall(r"\b(\d{6})\b", raw)
                if codes:
                    return codes[0], (fm.group(1) if fm else None)
        except Exception:
            pass
        time.sleep(6)
    return None, None


def submit_verify(st: str, flow: str, code: str) -> str:
    action = f"{AUTH}/self-service/verification?flow={flow}"
    s, body = _http(action, "POST", {"csrf_token": "", "code": code, "method": "code"},
                    {"X-Session-Token": st,
                     "Content-Type": "application/x-www-form-urlencoded"})
    try:
        return json.loads(body).get("state")
    except Exception:
        return f"HTTP{s}"


def mint_key(email: str, password: str, key_name: str = "farm",
             max_retry: int = 4) -> Tuple[Optional[str], str]:
    """Login browser flow -> csrftoken -> mint key. Retry otomatis saat 429."""
    import time as _t
    last = ""
    for attempt in range(1, max_retry + 1):
        key, info = _mint_key_once(email, password, key_name)
        if key:
            return key, info
        last = info
        if "429" in str(info):
            wait = 20 * attempt
            if attempt < max_retry:
                _t.sleep(wait)
            continue
        break
    return None, last


def _mint_key_once(email: str, password: str, key_name: str = "farm") -> Tuple[Optional[str], str]:
    """Satu percobaan login + mint. Return (key, info)."""
    cj = hcj.CookieJar()

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), NoRedirect)
    op.addheaders = [("User-Agent", UA), ("Accept", "application/json")]

    r = op.open(urllib.request.Request(
        f"{AUTH}/self-service/login/browser?return_to=https%3A%2F%2Fconsole.mistral.ai%2F",
        headers={"Cookie": ""}), timeout=30)
    flow = json.loads(r.read().decode())
    csrf1 = [n["attributes"].get("value", "") for n in flow["ui"]["nodes"]
             if n["attributes"].get("name") == "csrf_token"][0]

    def post(url, data):
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(url, data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Referer": "https://v2.auth.mistral.ai/login"})
        try:
            resp = op.open(req, timeout=30)
            return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, raw[:200]

    s, j2 = post(flow["ui"]["action"], {"csrf_token": csrf1, "identifier": email,
                                         "method": "identifier_first"})
    if s == 429:
        return None, "429 (login step1)"
    if s not in (200, 400):
        return None, f"login step1 HTTP {s}"
    csrf2 = [n["attributes"].get("value", "") for n in j2["ui"]["nodes"]
             if n["attributes"].get("name") == "csrf_token"][0]
    s, j3 = post(j2["ui"]["action"], {"csrf_token": csrf2, "identifier": email,
                                       "password": password, "method": "password"})
    if s == 429:
        return None, "429 (login password)"
    if s != 200:
        return None, f"login password HTTP {s}"

    sess = [c for c in cj if c.name.startswith("ory_session_")]
    if not sess:
        return None, "no ory_session cookie"
    SESS = f"{sess[0].name}={sess[0].value}"

    r = subprocess.run(["curl", "-s", "-i", "--max-time", "20", "--compressed",
        "-H", f"User-Agent: {UA}", "-H", f"Cookie: {SESS}",
        f"{CONSOLE}/api/users/me"], capture_output=True, text=True, timeout=30)
    m = re.search(r"[sS]et-[cC]ookie: csrftoken=([^;]+)", r.stdout)
    if not m:
        return None, "no csrftoken"
    csrf = m.group(1)

    r = subprocess.run(["curl", "-s", "--max-time", "25", "--compressed", "-X", "POST",
        "-H", f"User-Agent: {UA}", "-H", f"Cookie: {SESS}; csrftoken={csrf}",
        "-H", "Content-Type: application/json", "-H", f"X-CSRF-Token: {csrf}",
        "--data", json.dumps({"name": key_name, "expires_at": None}),
        f"{CONSOLE}/api/billing/api-keys"], capture_output=True, text=True, timeout=40)
    try:
        j = json.loads(r.stdout)
        return j.get("key"), SESS
    except Exception:
        return None, f"mint: {r.stdout[:150]}"


def harvest_mistral(verbose: bool = True) -> Dict[str, Any]:
    """Buat 1 akun Mistral + panen API key."""
    out: Dict[str, Any] = {"site": "mistral", "ok": False}
    tc = TempikClient()
    email = tc.create_inbox()
    save_inbox("mistral", email, tc.session_id, "")
    pw = _rand_password()
    out.update(email=email, password=pw)
    if verbose:
        C.print(f"[cyan]mistral[/] inbox: {email}")

    st = ory_register(email, pw)
    if not st:
        out["error"] = "register-failed"
        return out
    out["session_token"] = st
    if verbose:
        C.print("[green]  registered[/]")

    flow_api = trigger_verify(st, email)
    if not flow_api:
        out["error"] = "verify-trigger-failed"
        return out

    code, flow_link = poll_inbox(tc, email, 180)
    out["code"] = code
    if not code:
        out["error"] = "no-code"
        return out
    if verbose:
        C.print(f"[dim]  code: {code} (flow link: {flow_link})[/]")

    state = submit_verify(st, flow_link or flow_api, code)
    out["verify_state"] = state
    if state != "passed_challenge":
        out["error"] = f"verify-{state}"
        return out
    if verbose:
        C.print("[green]  email verified[/]")

    key, info = mint_key(email, pw, "farm")
    if key:
        out["ok"] = True
        out["apikey"] = key
        if verbose:
            C.print(f"[green]  API key: {key[:16]}...{key[-6:]}[/]")
        _append_account(email, pw, key, "KEYED")
    else:
        out["error"] = f"mint-failed: {info[:120]}"
        # simpan walau gagal mint -> bisa di-retry (email sudah terverifikasi)
        _append_account(email, pw, "", "VERIFIED_NOKEY")
        if verbose:
            C.print(f"[yellow]  mint gagal: {info[:120]} (disimpan utk retry)[/]")
    return out


def _append_account(email: str, password: str, apikey: str, status: str = ""):
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "accounts.txt"
    with open(p, "a") as f:
        f.write(f"{email}:{password}:{apikey}:{status}\n")


def api_chat(apikey: str, model: str = "ministral-8b-latest",
             prompt: str = "Say OK", timeout: int = 40) -> Dict[str, Any]:
    """Chat ke Mistral API (untuk test key)."""
    body = json.dumps({"model": model, "max_tokens": 20,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(f"{API}/chat/completions", data=body, method="POST",
        headers={"Authorization": f"Bearer {apikey}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())
