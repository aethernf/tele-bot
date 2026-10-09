#!/usr/bin/env python3
"""
Aethernf Key Bot — kelola customer & key lisensi via Telegram.
Perintah (khusus admin):
  /create <hari> [max_device] [tipe]  - bikin key baru, mis: /create 30  -> 30 hari, 1 device, VIP
                                 /create 30 1 SKIN -> 30 hari, 1 device, khusus skin
                                 /create 30 1 VVIP -> 30 hari, 1 device, full akses
  /extend <key> <hari>         - tambah masa aktif, mis: /extend AETH-XXXX 30
  /upgrade <key>               - naikkan tipe key (SKIN -> VIP)
  /settype <key> <tipe>        - ubah tipe bebas: VVIP / VIP / SKIN
  /setexpiry <key> <tgl> [jam]  - set expired presisi detik, mis: /setexpiry AETH-XXXX 2026-12-31 15:30:00
  /hwid <key>                  - lihat HWID terdaftar
  /hwidreset <key>             - hapus semua HWID (buyer ganti HP)
  /hwidrm <key> <nomor>        - hapus satu HWID
  /revoke <key>               - blokir key
  /delete <key>               - hapus key permanen
  /info <key>                 - detail key
  /list                       - daftar key (tampil tipe)
  /online                     - user yang sedang online

Tipe lisensi (3 role):
  VVIP = ALL ACCESS (semua fitur termasuk AIMBOT BYPASS)
  VIP  = semua fitur KECUALI AIMBOT BYPASS
  SKIN = hanya skin/mod doang

Env:
  AETH_BOT_TOKEN  token dari @BotFather
  AETH_ADMIN_ID   Telegram user ID numerik admin (dari @userinfobot)
  AETH_REPO_DIR   folder clone repo worker (default /root/aethernf-worker)

Jalankan:  python3 bot.py   (atau via systemd, lihat aethbot.service)
"""
import os
import re
import random
import string
import subprocess
from datetime import date, datetime, timedelta
import time

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.environ.get("AETH_BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("AETH_ADMIN_ID", "0") or 0)
REPO_DIR = os.environ.get("AETH_REPO_DIR", "/root/aethernf-worker")
KEYLIST = os.path.join(REPO_DIR, "keylist.lua")
CF_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
CF_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
CF_KV_NAMESPACE_ID = os.environ.get("CLOUDFLARE_KV_NAMESPACE_ID", "")

VALID_TYPES = ("VVIP", "VIP", "SKIN")

# ---------- helpers ----------
# (sisanya sama seperti bot.py asli, hanya VALID_TYPES yang dipakai)

def is_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id == ADMIN_ID

def git(*args):
    r = subprocess.run(["git", "-C", REPO_DIR, *args],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return r.stdout.strip()

def git_pull():
    st = subprocess.run(["git", "-C", REPO_DIR, "status", "--porcelain"],
                        capture_output=True, text=True, timeout=60)
    if st.returncode == 0 and st.stdout.strip():
        git("stash", "push", "--quiet", "-m", "aethbot-autostash")
    git("pull", "--rebase", "--quiet")

def git_push(msg: str):
    git("add", "keylist.lua")
    git("commit", "--quiet", "-m", msg)
    git("push", "--quiet")

def read_keylist() -> str:
    with open(KEYLIST, encoding="utf-8") as f:
        return f.read()

def write_keylist(content: str):
    with open(KEYLIST, "w", encoding="utf-8") as f:
        f.write(content)

def parse_entry(content: str, key: str):
    m = re.search(r'\["' + re.escape(key) + r'"\]\s*=\s*\{([^}]+)\}', content, re.S)
    if not m:
        return None
    body = m.group(1)
    out = {}
    for fm in re.finditer(r'(\w+)\s*=\s*(?:"([^"]*)"|(\S+?))\s*[,}\n]', body):
        out[fm.group(1)] = fm.group(2) if fm.group(2) is not None else fm.group(3)
    return out

def next_slot(content: str) -> str:
    slots = [int(s) for s in re.findall(r'SLOT\s*=\s*"(\d+)"', content)]
    return str(max(slots, default=0) + 1)

def gen_key() -> str:
    alpha = string.ascii_uppercase + string.digits
    return "AETH-" + "-".join("".join(random.choice(alpha) for _ in range(4)) for _ in range(3))

def now_plus_ts(days: int) -> int:
    return int(time.time()) + days * 86400

def fmt_ts(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(ts)

def parse_expiry(ent: dict) -> int:
    raw = str(ent.get("expiry", "") or "")
    if re.fullmatch(r"\d{10}", raw):
        return int(raw)
    try:
        dt = datetime.strptime(raw[:10], "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        return int(dt.timestamp())
    except ValueError:
        return 0

def key_status(ent: dict) -> str:
    if ent.get("valid") != "true":
        return "DIBLOKIR"
    if parse_expiry(ent) < time.time():
        return "EXPIRED"
    return "AKTIF"

# ---------- Cloudflare KV ----------
def _cf_ok() -> bool:
    return bool(CF_API_TOKEN and CF_ACCOUNT_ID and CF_KV_NAMESPACE_ID)

def _cf_kv_url(key: str) -> str:
    from urllib.parse import quote
    return (f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}"
            f"/storage/kv/namespaces/{CF_KV_NAMESPACE_ID}/values/{quote(key, safe='')}")

def hwid_list(key: str) -> list:
    import json, urllib.request, urllib.error
    if not _cf_ok():
        raise RuntimeError("Set CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_KV_NAMESPACE_ID dulu.")
    req = urllib.request.Request(_cf_kv_url(key), headers={"Authorization": f"Bearer {CF_API_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
            return data if isinstance(data, list) else []
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise RuntimeError(f"Cloudflare API: HTTP {e.code}")

def hwid_write(key: str, hwids: list):
    import json, urllib.request
    if not _cf_ok():
        raise RuntimeError("Set CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_KV_NAMESPACE_ID dulu.")
    body = json.dumps(hwids).encode()
    req = urllib.request.Request(_cf_kv_url(key), data=body, method="PUT",
                                 headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20):
        pass

def hwid_clear(key: str):
    import urllib.request, urllib.error
    if not _cf_ok():
        raise RuntimeError("Set CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_KV_NAMESPACE_ID dulu.")
    req = urllib.request.Request(_cf_kv_url(key), headers={"Authorization": f"Bearer {CF_API_TOKEN}"}, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=20):
            pass
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise RuntimeError(f"Cloudflare API: HTTP {e.code}")

def kv_list(prefix: str) -> list:
    import json, urllib.request
    from urllib.parse import urlencode
    if not _cf_ok():
        raise RuntimeError("Set CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_KV_NAMESPACE_ID dulu.")
    base = (f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}"
            f"/storage/kv/namespaces/{CF_KV_NAMESPACE_ID}/keys")
    out = []
    cursor = None
    while True:
        qs = urlencode({"prefix": prefix, **({"cursor": cursor} if cursor else {})})
        req = urllib.request.Request(base + "?" + qs, headers={"Authorization": f"Bearer {CF_API_TOKEN}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
        if not data.get("success"):
            raise RuntimeError(f"Cloudflare API: {data.get('errors')}")
        out.extend(k["name"] for k in data["result"])
        cursor = data["result_info"].get("cursor")
        if not cursor:
            break
    return out

def kv_get(key: str):
    import json, urllib.request, urllib.error
    from urllib.parse import quote
    if not _cf_ok():
        raise RuntimeError("Set CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_KV_NAMESPACE_ID dulu.")
    url = (f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}"
           f"/storage/kv/namespaces/{CF_KV_NAMESPACE_ID}/values/{quote(key, safe='')}")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {CF_API_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise RuntimeError(f"Cloudflare API: HTTP {e.code}")
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw

def entry_text(key: str, days: int, max_devices: int, key_type: str = "VIP") -> str:
    return (
        f'    ["{key}"] = {{\n'
        f'        type = "{key_type}",\n'
        f'        expiry = {now_plus_ts(days)},\n'
        f'        valid = true,\n'
        f'        max_devices = {max_devices},\n'
        f'        SLOT = "{next_slot(read_keylist())}"\n'
        f'    }},\n'
    )

# ---------- commands ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await update.message.reply_text(
        "Aethernf Key Bot aktif.\n\n"
        "/create <hari> [max_device] [tipe] - bikin key baru\n"
        "/extend <key> <hari> - tambah masa aktif\n"
        "/upgrade <key> - naikkan SKIN jadi VIP\n"
        "/settype <key> <tipe> - ubah tipe (VVIP/VIP/SKIN)\n"
        "/setexpiry <key> <tgl> [jam] - set expired\n"
        "/hwid <key> - lihat HWID\n"
        "/hwidreset <key> - reset HWID\n"
        "/hwidrm <key> <nomor> - hapus satu HWID\n"
        "/revoke <key> - blokir key\n"
        "/delete <key> - hapus key permanen\n"
        "/info <key> - detail key\n"
        "/list - daftar key\n"
        "/online - user yang sedang online"
    )

async def create(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Pakai: /create <hari> [max_device] [tipe]\nContoh: /create 30\n/create 30 1 SKIN\n/create 30 1 VVIP")
        return
    days = int(ctx.args[0])
    max_devices = int(ctx.args[1]) if len(ctx.args) > 1 and ctx.args[1].isdigit() else 1
    key_type = (ctx.args[2].upper() if len(ctx.args) > 2 else "VIP")
    if key_type not in VALID_TYPES:
        await update.message.reply_text(f"Tipe harus {' / '.join(VALID_TYPES)}.")
        return
    if days < 1 or days > 3650:
        await update.message.reply_text("Durasi 1-3650 hari.")
        return
    await update.message.reply_text("Bikin key...")
    try:
        git_pull()
        content = read_keylist()
        key = gen_key()
        while parse_entry(content, key):
            key = gen_key()
        idx = content.rstrip().rfind("}")
        head = content[:idx].rstrip()
        if head.endswith("}"):
            head += ","
        content = head + "\n" + entry_text(key, days, max_devices, key_type) + content[idx:]
        write_keylist(content)
        git_push(f"create key {key} ({days} hari, {key_type})")
    except Exception as e:
        await update.message.reply_text(f"Gagal: {e}")
        return
    exp_ts = now_plus_ts(days)
    await update.message.reply_text(
        f"Key dibuat:\n\n`{key}`\nTipe: {key_type}\nDurasi: {days} hari\n"
        f"Expired: {fmt_ts(exp_ts)}\nMax device: {max_devices}\n\n"
        f"Kirim key ini ke buyer. Aktif ~1 menit lagi.",
        parse_mode="Markdown",
    )

async def revoke(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not ctx.args:
        await update.message.reply_text("Pakai: /revoke <key>")
        return
    key = ctx.args[0].strip().upper()
    try:
        git_pull()
        content = read_keylist()
        if not parse_entry(content, key):
            await update.message.reply_text("Key tidak ketemu.")
            return
        content = re.sub(r'(\["' + re.escape(key) + r'"\]\s*=\s*\{[^}]*?)valid\s*=\s*true',
            r'\1valid = false', content, count=1, flags=re.S)
        write_keylist(content)
        git_push(f"revoke key {key}")
    except Exception as e:
        await update.message.reply_text(f"Gagal: {e}")
        return
    await update.message.reply_text(f"Key `{key}` diblokir.", parse_mode="Markdown")

async def delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not ctx.args:
        await update.message.reply_text("Pakai: /delete <key>")
        return
    key = ctx.args[0].strip().upper()
    try:
        git_pull()
        content = read_keylist()
        if not parse_entry(content, key):
            await update.message.reply_text("Key tidak ketemu.")
            return
        new_content = re.sub(r'\s*\["' + re.escape(key) + r'"\]\s*=\s*\{[^}]+\},\n?',
            '\n', content, count=1, flags=re.S)
        write_keylist(new_content)
        try:
            hwid_clear(key)
        except Exception:
            pass
        git_push(f"delete key {key}")
    except Exception as e:
        await update.message.reply_text(f"Gagal: {e}")
        return
    await update.message.reply_text(f"Key `{key}` dihapus permanen.", parse_mode="Markdown")

async def extend(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if len(ctx.args) < 2 or not ctx.args[1].lstrip("-").isdigit():
        await update.message.reply_text("Pakai: /extend <key> <hari>\nContoh: /extend AETH-XXXX 30")
        return
    key = ctx.args[0].strip().upper()
    days = int(ctx.args[1])
    try:
        git_pull()
        content = read_keylist()
        ent = parse_entry(content, key)
        if not ent:
            await update.message.reply_text("Key tidak ketemu.")
            return
        base_ts = parse_expiry(ent)
        now_ts = int(time.time())
        if base_ts < now_ts:
            base_ts = now_ts
        new_ts = base_ts + days * 86400
        content = re.sub(r'(\["' + re.escape(key) + r'"\]\s*=\s*\{[^}]*?)expiry\s*=\s*(?:"[^"]+"|\d+)',
            r'\1expiry = ' + str(new_ts), content, count=1, flags=re.S)
        write_keylist(content)
        git_push(f"extend key {key} +{days} hari")
    except Exception as e:
        await update.message.reply_text(f"Gagal: {e}")
        return
    await update.message.reply_text(f"Key `{key}` diperpanjang {days} hari.\nExpired baru: {fmt_ts(new_ts)}", parse_mode="Markdown")

def _set_key_type(key: str, new_type: str) -> str:
    git_pull()
    content = read_keylist()
    ent = parse_entry(content, key)
    if not ent:
        raise ValueError("Key tidak ketemu.")
    cur = (ent.get("type") or "VIP").upper()
    if cur == new_type:
        raise ValueError(f"Key `{key}` sudah {new_type}.")
    content = re.sub(r'(\["' + re.escape(key) + r'"\]\s*=\s*\{[^}]*?)type\s*=\s*"[^"]+"',
        r'\1type = "' + new_type + '"', content, count=1, flags=re.S)
    write_keylist(content)
    git_push(f"settype key {key} {cur}->{new_type}")
    return cur

async def upgrade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not ctx.args:
        await update.message.reply_text("Pakai: /upgrade <key>")
        return
    key = ctx.args[0].strip().upper()
    try:
        cur = _set_key_type(key, "VIP")
    except Exception as e:
        await update.message.reply_text(f"Gagal: {e}")
        return
    await update.message.reply_text(f"Key `{key}` naik tingkat: {cur} → VIP.\nBerlaku ~1 menit lagi.", parse_mode="Markdown")

async def settype(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if len(ctx.args) < 2:
        await update.message.reply_text(f"Pakai: /settype <key> <{'|'.join(VALID_TYPES)}>")
        return
    key = ctx.args[0].strip().upper()
    new_type = ctx.args[1].strip().upper()
    if new_type not in VALID_TYPES:
        await update.message.reply_text(f"Tipe harus {' / '.join(VALID_TYPES)}.")
        return
    try:
        cur = _set_key_type(key, new_type)
    except Exception as e:
        await update.message.reply_text(f"Gagal: {e}")
        return
    await update.message.reply_text(f"Key `{key}`: {cur} → {new_type}.\nBerlaku ~1 menit lagi.", parse_mode="Markdown")

async def setexpiry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if len(ctx.args) < 2:
        await update.message.reply_text("Pakai: /setexpiry <key> <YYYY-MM-DD> [HH:MM:SS]\nContoh: /setexpiry AETH-XXXX 2026-12-31")
        return
    key = ctx.args[0].strip().upper()
    try:
        dstr = ctx.args[1].strip()
        tstr = ctx.args[2].strip() if len(ctx.args) > 2 else "23:59:59"
        new_ts = int(datetime.strptime(f"{dstr} {tstr}", "%Y-%m-%d %H:%M:%S").timestamp())
    except ValueError:
        await update.message.reply_text("Format salah. Pakai YYYY-MM-DD [HH:MM:SS]")
        return
    try:
        git_pull()
        content = read_keylist()
        ent = parse_entry(content, key)
        if not ent:
            await update.message.reply_text("Key tidak ketemu.")
            return
        old_exp = fmt_ts(parse_expiry(ent))
        content = re.sub(r'(\["' + re.escape(key) + r'"\]\s*=\s*\{[^}]*?)expiry\s*=\s*(?:"[^"]+"|\d+)',
            r'\1expiry = ' + str(new_ts), content, count=1, flags=re.S)
        write_keylist(content)
        git_push(f"setexpiry key {key} {fmt_ts(new_ts)}")
    except Exception as e:
        await update.message.reply_text(f"Gagal: {e}")
        return
    await update.message.reply_text(f"Key `{key}`:\n{old_exp} → {fmt_ts(new_ts)}.", parse_mode="Markdown")

async def hwid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not ctx.args:
        await update.message.reply_text("Pakai: /hwid <key>")
        return
    key = ctx.args[0].strip().upper()
    try:
        hwids = hwid_list(key)
    except Exception as e:
        await update.message.reply_text(f"Gagal: {e}")
        return
    if not hwids:
        await update.message.reply_text(f"Key `{key}`: belum ada device terdaftar.", parse_mode="Markdown")
        return
    rows = [f"{i+1}. `{h}`" for i, h in enumerate(hwids)]
    await update.message.reply_text(f"Key `{key}` — {len(hwids)} device:\n\n" + "\n".join(rows), parse_mode="Markdown")

async def hwidreset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not ctx.args:
        await update.message.reply_text("Pakai: /hwidreset <key>")
        return
    key = ctx.args[0].strip().upper()
    try:
        n = len(hwid_list(key))
        hwid_clear(key)
    except Exception as e:
        await update.message.reply_text(f"Gagal: {e}")
        return
    await update.message.reply_text(f"Key `{key}`: {n} HWID dihapus.", parse_mode="Markdown")

async def hwidrm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if len(ctx.args) < 2 or not ctx.args[1].isdigit():
        await update.message.reply_text("Pakai: /hwidrm <key> <nomor>")
        return
    key = ctx.args[0].strip().upper()
    idx = int(ctx.args[1]) - 1
    try:
        hwids = hwid_list(key)
        if idx < 0 or idx >= len(hwids):
            await update.message.reply_text("Nomor tidak ada.")
            return
        removed = hwids.pop(idx)
        hwid_write(key, hwids)
    except Exception as e:
        await update.message.reply_text(f"Gagal: {e}")
        return
    await update.message.reply_text(f"HWID `{removed}` dihapus.", parse_mode="Markdown")

async def info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not ctx.args:
        await update.message.reply_text("Pakai: /info <key>")
        return
    key = ctx.args[0].strip().upper()
    try:
        git_pull()
        ent = parse_entry(read_keylist(), key)
    except Exception as e:
        await update.message.reply_text(f"Gagal: {e}")
        return
    if not ent:
        await update.message.reply_text("Key tidak ketemu.")
        return
    st = key_status(ent)
    icon = {"AKTIF": "✅", "EXPIRED": "⚠️", "DIBLOKIR": "❌"}.get(st, "")
    await update.message.reply_text(
        f"`{key}`\nType: {ent.get('type', '-')}\nStatus: {st} {icon}\n"
        f"Valid: {ent.get('valid', '-')}\nExpiry: {fmt_ts(parse_expiry(ent))}\n"
        f"Max device: {ent.get('max_devices', '-')}\nSLOT: {ent.get('SLOT', '-')}",
        parse_mode="Markdown",
    )

async def list_keys(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    try:
        git_pull()
        content = read_keylist()
    except Exception as e:
        await update.message.reply_text(f"Gagal: {e}")
        return
    rows = []
    for m in re.finditer(r'\["([^"]+)"\]\s*=\s*\{([^}]+)\}', content, re.S):
        key, body = m.group(1), m.group(2)
        expm = re.search(r'expiry\s*=\s*(?:"([^"]+)"|(\d+))', body)
        raw_exp = expm.group(1) or expm.group(2) if expm else ""
        exp_s = fmt_ts(parse_expiry({"expiry": raw_exp}))
        expired = parse_expiry({"expiry": raw_exp}) < time.time() if raw_exp else False
        typem = re.search(r'type\s*=\s*"([^"]+)"', body)
        ktype = typem.group(1) if typem else "?"
        if "valid = true" not in body:
            icon = "❌"
        elif expired:
            icon = "⚠️"
        else:
            icon = "✅"
        rows.append(f"{icon} `{key}` [{ktype}] → {exp_s}")
    await update.message.reply_text(f"Total {len(rows)} key:\n\n" + "\n".join(rows[:40]), parse_mode="Markdown")

async def online(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await update.message.reply_text("Cek user online...")
    try:
        keys = kv_list("SEEN_")
    except Exception as e:
        await update.message.reply_text(f"Gagal: {e}")
        return
    now_ms = int(time.time() * 1000)
    limit_ms = 10 * 60 * 1000
    online_rows = []
    total_dev = 0
    for sk in keys:
        key = sk[5:]
        try:
            seen = kv_get(sk)
        except Exception:
            continue
        if not isinstance(seen, dict):
            continue
        fresh = [h for h, ts in seen.items() if isinstance(ts, (int, float)) and (now_ms - ts) < limit_ms]
        if fresh:
            total_dev += len(fresh)
            try:
                ent = parse_entry(read_keylist(), key)
                ktype = (ent.get("type") or "?") if ent else "?"
            except Exception:
                ktype = "?"
            online_rows.append(f"🟢 `{key}` ({ktype}) — {len(fresh)} device")
    if not online_rows:
        await update.message.reply_text("Tidak ada user online dalam 10 menit terakhir.")
        return
    await update.message.reply_text(f"**Online: {total_dev} device / {len(online_rows)} key**\n\n" + "\n".join(online_rows[:30]), parse_mode="Markdown")

def main():
    if not BOT_TOKEN or not ADMIN_ID:
        raise SystemExit("Set AETH_BOT_TOKEN dan AETH_ADMIN_ID dulu.")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("create", create))
    app.add_handler(CommandHandler("revoke", revoke))
    app.add_handler(CommandHandler("delete", delete))
    app.add_handler(CommandHandler("extend", extend))
    app.add_handler(CommandHandler("upgrade", upgrade))
    app.add_handler(CommandHandler("settype", settype))
    app.add_handler(CommandHandler("setexpiry", setexpiry))
    app.add_handler(CommandHandler("hwid", hwid))
    app.add_handler(CommandHandler("hwidreset", hwidreset))
    app.add_handler(CommandHandler("hwidrm", hwidrm))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("list", list_keys))
    app.add_handler(CommandHandler("online", online))
    print("Aethernf Key Bot jalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
