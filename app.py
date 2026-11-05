#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mhnet CopyScripts - Organizador de Scripts e Copypastas (Interface Moderna)
"""

import json
import os
import sys
import time
import shutil
import uuid
import webbrowser
import datetime
import math
import re
import zlib
import struct
import base64
import threading
import subprocess
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser, font as tkfont

# APP_NAME é o nome da pasta de dados (mantido para não perder os dados já salvos)
APP_NAME = "copyscripts"
APP_DISPLAY_NAME = "Mhnet CopyScripts"
APP_VERSION = "2.2"     # AUMENTE este número a cada versão nova (2.1 -> 2.2 -> 2.3 ...)

# ---------------- atualização automática ----------------
# Coloque aqui "seu-usuario/nome-do-repositorio" do GitHub (ex.: "joaosilva/mhnet-copyscripts").
# Vazio = atualização automática desligada.
UPDATE_REPO = "joaopdalves/mhnet-copyscripts"
UPDATE_ASSET = "MhnetCopyScripts.exe"   # nome do .exe publicado no GitHub (o workflow usa o mesmo)
UPDATE_CHECK_TIMEOUT = 4                # segundos esperando a internet antes de desistir

def get_app_data_dir():
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, "backups"), exist_ok=True)
    return path

DATA_DIR = get_app_data_dir()
DATA_FILE = os.path.join(DATA_DIR, "data.json")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")

def updates_enabled():
    """Só o .exe (não o `python app.py`) no Windows, e só se o repositório estiver configurado."""
    return bool(UPDATE_REPO.strip()) and getattr(sys, "frozen", False) and sys.platform.startswith("win")


def _version_tuple(v):
    """'2.10' -> (2, 10). Zeros no fim não contam: '2.0' == '2.0.0'."""
    parts = [int(n) for n in re.findall(r"\d+", str(v))]
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _http_open(url, timeout):
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": f"MhnetCopyScripts/{APP_VERSION}",
        "Cache-Control": "no-cache",
    })
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_update_info():
    """Lê o latest.json da última versão publicada. Devolve os dados dela se for MAIS NOVA que esta;
    senão None. (Usa o link de download direto, que não tem o limite de consultas da API do GitHub.)"""
    repo = UPDATE_REPO.strip()
    url = f"https://github.com/{repo}/releases/latest/download/latest.json"
    with _http_open(url, UPDATE_CHECK_TIMEOUT) as r:
        info = json.loads(r.read(65536).decode("utf-8"))
    ver = str(info.get("version", "")).strip()
    if not ver or _version_tuple(ver) <= _version_tuple(APP_VERSION):
        return None
    info["version"] = ver
    info["file"] = info.get("file") or UPDATE_ASSET
    return info


def download_update(info, progress):
    """Baixa o .exe novo ao lado do atual (arquivo .download) e confere tamanho e SHA-256."""
    import hashlib
    exe = os.path.abspath(sys.executable)
    tmp = exe + ".download"
    url = f"https://github.com/{UPDATE_REPO.strip()}/releases/download/v{info['version']}/{info['file']}"
    expected = int(info.get("size") or 0)
    h = hashlib.sha256()
    got = 0
    try:
        with _http_open(url, 30) as r, open(tmp, "wb") as f:
            total = expected or int(r.headers.get("Content-Length") or 0)
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                progress(got, total)
        if got < 1024:
            raise ValueError("arquivo baixado vazio")
        if expected and got != expected:
            raise ValueError(f"tamanho errado ({got} de {expected} bytes)")
        sha = str(info.get("sha256") or "").lower()
        if sha and h.hexdigest() != sha:
            raise ValueError("arquivo corrompido (SHA-256 não confere)")
        with open(tmp, "rb") as f:
            if f.read(2) != b"MZ":
                raise ValueError("o arquivo baixado não é um .exe")
        return tmp
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def install_update(new_file):
    """Troca o .exe. O Windows não deixa sobrescrever um .exe aberto, mas deixa RENOMEAR:
    o atual vira '.old' e o novo assume o nome dele (o atalho da área de trabalho continua valendo)."""
    exe = os.path.abspath(sys.executable)
    old = exe + ".old"
    if os.path.exists(old):
        try:
            os.remove(old)
        except OSError:
            old = f"{exe}.{int(time.time())}.old"
    os.replace(exe, old)
    try:
        os.replace(new_file, exe)
    except Exception:
        os.replace(old, exe)                     # deu errado: volta o .exe antigo
        raise
    return exe


def relaunch(exe):
    """Abre o .exe novo como um programa independente (fora da pasta temporária deste)."""
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    for k in ("_MEIPASS2", "_PYI_APPLICATION_HOME_DIR", "_PYI_ARCHIVE_FILE",
              "_PYI_PARENT_PROCESS_LEVEL", "_PYI_SPLASH_IPC", "TCL_LIBRARY", "TK_LIBRARY"):
        env.pop(k, None)
    flags = 0x00000008 | 0x00000200            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([exe], env=env, cwd=os.path.dirname(exe), creationflags=flags, close_fds=True)


def cleanup_old_versions():
    """Apaga o .exe antigo (.old) e downloads pela metade. O antigo pode ainda estar fechando: tenta por ~30s."""
    exe = os.path.abspath(sys.executable)
    folder, base = os.path.dirname(exe), os.path.basename(exe)
    for _ in range(15):
        left = 0
        try:
            names = os.listdir(folder)
        except OSError:
            return
        for name in names:
            if name.startswith(base + ".") and (name.endswith(".old") or name.endswith(".download")):
                try:
                    os.remove(os.path.join(folder, name))
                except OSError:
                    left += 1
        if not left:
            return
        time.sleep(2)


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def image_path(name):
    """Procura a imagem na pasta 'imagens' e, se não achar, ao lado do app.py."""
    for rel in (os.path.join("imagens", name), name):
        path = resource_path(rel)
        if os.path.exists(path):
            return path
    return resource_path(os.path.join("imagens", name))

ICON_ICO = image_path("mhnet_icon.ico")
ICON_PNG = image_path("mhnet_icon.png")
LOGO_LIGHT = image_path("mhnet_logo.png")
LOGO_DARK = image_path("mhnet_logo_dark.png")

PALETTES = {
    "light": {
        # Escala de camadas (espelha o modo escuro): página/fundo -> superfícies brancas
        # (barra superior, cards, menus) -> botões e linhas de script num tom levemente mais fundo.
        "bg": "#E4E9F3",              # fundo da página, barra de título e diálogos
        "bg_alt": "#FFFFFF",          # barra superior e barra de status (superfície elevada)
        "titlebar_bg": "#E4E9F3",
        "titlebar_hover": "#D3DAE7",
        "card_bg": "#FFFFFF",         # cards das categorias e menus
        "text": "#0F172A",
        "text_dim": "#526078",        # um pouco mais escuro para manter leitura sobre os novos tons
        "accent": "#6366F1",
        "accent_hover": "#4F46E5",
        "accent_text": "#FFFFFF",
        "brand": "#3A33FF",
        "brand_hover": "#2F29D9",
        "brand_text": "#FFFFFF",
        "border": "#C3CCDC",
        "danger": "#EF4444",
        "success": "#10B981",
        "input_bg": "#DAE1EE",        # botões, busca, campo de contrato e linhas de script
        "field_bg": "#FFFFFF",        # campos de texto dentro dos diálogos (sobre o fundo da página)
        "strip_bg": "#FFFFFF",
        "shadow": "#C3CCDC",
        "highlight": "#FDE047",
        "highlight_fg": "#0F172A",
        "select_bg": "#818CF8",       # seleção de texto (igual em todo o app)
        "select_fg": "#0F172A",
        "scroll_track": "#D3DAE7",
        "scroll_thumb": "#94A3B8",
        "scroll_thumb_hover": "#6366F1"
    },
    "dark": {
        "bg": "#0F172A",
        "bg_alt": "#1E293B",
        "titlebar_bg": "#0F172A",
        "titlebar_hover": "#1E293B",
        "card_bg": "#1E293B",
        "text": "#F8FAFC",
        "text_dim": "#94A3B8",
        "accent": "#818CF8",
        "accent_hover": "#6366F1",
        "accent_text": "#0F172A",
        "brand": "#FFFFFF",
        "brand_hover": "#E2E8F0",
        "brand_text": "#3A33FF",
        "border": "#334155",
        "danger": "#F87171",
        "success": "#34D399",
        "input_bg": "#334155",
        "field_bg": "#334155",        # igual ao input_bg: o modo escuro não muda
        "strip_bg": "#1E293B",
        "shadow": "#020617",
        "highlight": "#EAB308",
        "highlight_fg": "#0F172A",
        "select_bg": "#818CF8",
        "select_fg": "#0F172A",
        "scroll_track": "#1E293B",
        "scroll_thumb": "#64748B",
        "scroll_thumb_hover": "#818CF8"
    },
}

# Tamanho aceito para um contrato copiado (mesmo critério do app Atendimento MHNET)
CONTRATO_MIN_DIGITOS = 1
CUSTOM_TITLEBAR = True   # Windows 10: desenha a própria barra de título (a nativa só aceita preto/branco)
CLIP_PREVIEW_MAX = 10   # máx. de caracteres do texto copiado exibido na barra de atalhos
CONTRATO_MAX_DIGITOS = 12

# Atalhos que abrem páginas do sistema da Mhnet usando o número do contrato
CONTRACT_LINKS = [
    ("AutoISP",    lambda c: f"https://autoisp.mhnet.com.br/contracted_services/{c}"),
    ("Extrato",    lambda c: f"https://erp.mhnet.com.br/authentication_contracts/get_authentication_informations/0/{c}/"),
    ("Dashboard",  lambda c: f"https://erp.mhnet.com.br/contract_occurrences/details/{c}?redirectTo=billingMaintenance"),
    ("Financeiro", lambda c: f"https://erp.mhnet.com.br/service_people_consults/edit/{c}"),
]

FONT_FAMILY = "Segoe UI" if sys.platform.startswith("win") else "Helvetica"
EMOJI_FONT_FAMILY = FONT_FAMILY

if sys.platform.startswith("win"):
    _FONT_CANDIDATES = ["Segoe UI Variable Text", "Inter", "Segoe UI", "Calibri", "Tahoma"]
    _EMOJI_CANDIDATES = ["Segoe UI Emoji", "Segoe UI Symbol"]
elif sys.platform == "darwin":
    _FONT_CANDIDATES = ["SF Pro Text", "Helvetica Neue", "Helvetica"]
    _EMOJI_CANDIDATES = ["Apple Color Emoji"]
else:
    _FONT_CANDIDATES = ["Inter", "Ubuntu", "Noto Sans", "DejaVu Sans", "Liberation Sans", "Helvetica"]
    _EMOJI_CANDIDATES = ["Noto Color Emoji", "Noto Emoji", "DejaVu Sans"]

_EMOJI_RANGES = (
    (0x2190, 0x21FF), (0x2300, 0x23FF), (0x25A0, 0x27BF),
    (0x2B00, 0x2BFF), (0x1F000, 0x1FAFF), (0xFE0F, 0xFE0F),
)

def _has_emoji(text):
    if not text:
        return False
    for ch in text:
        cp = ord(ch)
        for lo, hi in _EMOJI_RANGES:
            if lo <= cp <= hi:
                return True
    return False

def pick_font(text, size, *style):
    family = EMOJI_FONT_FAMILY if _has_emoji(text) else FONT_FAMILY
    return (family, size) + style

def _init_fonts(root):
    global FONT_FAMILY, EMOJI_FONT_FAMILY
    try:
        available = set(tkfont.families(root))
    except Exception:
        return
    for name in _FONT_CANDIDATES:
        if name in available:
            FONT_FAMILY = name
            break
    for name in _EMOJI_CANDIDATES:
        if name in available:
            EMOJI_FONT_FAMILY = name
            break
    else:
        EMOJI_FONT_FAMILY = FONT_FAMILY

# ======================================================================
#  ÍCONES SVG (estilo Lucide, viewBox 24x24, só traço)
#  Renderizados em Python puro (sem Pillow/cairo) para PNG com transparência,
#  então ficam suavizados e funcionam igual dentro do .exe do PyInstaller.
# ======================================================================
def _svg(inner):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round">' + inner + '</svg>')

SVG_ICONS = {
    "pencil": _svg('<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>'),
    "trash": _svg('<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/>'),
    "sun": _svg('<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>'),
    "moon": _svg('<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>'),
    "search": _svg('<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>'),
    "plus": _svg('<path d="M5 12h14"/><path d="M12 5v14"/>'),
    "download": _svg('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>'),
    "upload": _svg('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>'),
    "folder": _svg('<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>'),
    "chevron-up": _svg('<path d="m18 15-6-6-6 6"/>'),
    "chevron-down": _svg('<path d="m6 9 6 6 6-6"/>'),
    "minus": _svg('<path d="M5 12h14"/>'),
    "x": _svg('<path d="M18 6 6 18"/><path d="m6 6 12 12"/>'),
    "maximize": _svg('<polyline points="5 5 19 5 19 19 5 19 5 5"/>'),
    "restore": _svg('<polyline points="5 9 15 9 15 19 5 19 5 9"/><polyline points="9 9 9 5 19 5 19 15 15 15"/>'),
    "copy": _svg('<path d="M10 8h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H10a2 2 0 0 1-2-2V10a2 2 0 0 1 2-2z"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>'),
    "paste": _svg('<path d="M9 2h6a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>'),
    "scissors": _svg('<circle cx="6" cy="6" r="3"/><path d="M8.12 8.12 12 12"/><path d="M20 4 8.12 15.88"/><circle cx="6" cy="18" r="3"/><path d="M14.8 14.8 20 20"/>'),
    "select-all": _svg('<path d="M5 3a2 2 0 0 0-2 2"/><path d="M19 3a2 2 0 0 1 2 2"/><path d="M21 19a2 2 0 0 1-2 2"/><path d="M5 21a2 2 0 0 1-2-2"/><path d="M9 3h1"/><path d="M9 21h1"/><path d="M14 3h1"/><path d="M14 21h1"/><path d="M3 9v1"/><path d="M21 9v1"/><path d="M3 14v1"/><path d="M21 14v1"/>'),
    "alert": _svg('<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>'),
    "info": _svg('<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>'),
    "check-circle": _svg('<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>'),
    "x-circle": _svg('<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>'),
    "grip": _svg('<circle cx="9" cy="12" r="1"/><circle cx="9" cy="5" r="1"/><circle cx="9" cy="19" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="15" cy="5" r="1"/><circle cx="15" cy="19" r="1"/>'),
}

_NUM_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


def _arc_points(x1, y1, rx, ry, phi_deg, fa, fs, x2, y2):
    """Converte um arco SVG (comando A) em pontos de uma polilinha."""
    if (x1, y1) == (x2, y2):
        return []
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [(x2, y2)]
    phi = math.radians(phi_deg)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = (x1p ** 2) / (rx ** 2) + (y1p ** 2) / (ry ** 2)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if fa == fs:
        co = -co
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx = cp * cxp - sp * cyp + (x1 + x2) / 2
    cy = sp * cxp + cp * cyp + (y1 + y2) / 2
    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
    vx, vy = (-x1p - cxp) / rx, (-y1p - cyp) / ry
    th1 = math.atan2(uy, ux)
    dth = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
    if not fs and dth > 0:
        dth -= 2 * math.pi
    elif fs and dth < 0:
        dth += 2 * math.pi
    n = max(4, int(abs(dth) / math.radians(8)) + 1)
    pts = []
    for k in range(1, n + 1):
        t = th1 + dth * k / n
        px, py = rx * math.cos(t), ry * math.sin(t)
        pts.append((cp * px - sp * py + cx, sp * px + cp * py + cy))
    pts[-1] = (x2, y2)
    return pts


def _path_to_polylines(d):
    """Lê o atributo 'd' de um <path> (M L H V C S Q A Z, absolutos e relativos)."""
    i, n = 0, len(d)

    def skip():
        nonlocal i
        while i < n and d[i] in " ,\t\r\n":
            i += 1

    def num():
        nonlocal i
        skip()
        m = _NUM_RE.match(d, i)
        i = m.end()
        return float(m.group())

    def flag():
        nonlocal i
        skip()
        v = d[i] == "1"
        i += 1
        return v

    polys, cur = [], None
    x = y = sx = sy = 0.0
    ctrl = None
    cmd = None

    def begin():
        nonlocal cur
        if cur is None:
            cur = [(x, y)]
            polys.append(cur)

    while True:
        skip()
        if i >= n:
            break
        if d[i].isalpha():
            cmd = d[i]
            i += 1
            if cmd in "Zz":
                if cur:
                    cur.append((sx, sy))
                x, y = sx, sy
                cur, ctrl = None, None
                continue
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if c == "M":
            x, y = num() + ox, num() + oy
            sx, sy = x, y
            cur = [(x, y)]
            polys.append(cur)
            cmd = "l" if rel else "L"
            ctrl = None
        elif c == "L":
            nx, ny = num() + ox, num() + oy
            begin(); cur.append((nx, ny)); x, y = nx, ny; ctrl = None
        elif c == "H":
            nx = num() + ox
            begin(); cur.append((nx, y)); x = nx; ctrl = None
        elif c == "V":
            ny = num() + oy
            begin(); cur.append((x, ny)); y = ny; ctrl = None
        elif c in ("C", "S"):
            if c == "C":
                x1, y1 = num() + ox, num() + oy
            else:
                x1, y1 = (2 * x - ctrl[0], 2 * y - ctrl[1]) if ctrl else (x, y)
            x2, y2 = num() + ox, num() + oy
            nx, ny = num() + ox, num() + oy
            begin()
            for k in range(1, 15):
                t = k / 14
                u = 1 - t
                cur.append((u**3 * x + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * nx,
                            u**3 * y + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * ny))
            x, y, ctrl = nx, ny, (x2, y2)
        elif c == "Q":
            x1, y1 = num() + ox, num() + oy
            nx, ny = num() + ox, num() + oy
            begin()
            for k in range(1, 11):
                t = k / 10
                u = 1 - t
                cur.append((u * u * x + 2 * u * t * x1 + t * t * nx,
                            u * u * y + 2 * u * t * y1 + t * t * ny))
            x, y, ctrl = nx, ny, None
        elif c == "A":
            rx, ry, rot = num(), num(), num()
            fa, fs = flag(), flag()
            nx, ny = num() + ox, num() + oy
            begin()
            cur.extend(_arc_points(x, y, rx, ry, rot, fa, fs, nx, ny))
            x, y, ctrl = nx, ny, None
        else:
            break  # comando não suportado
    return [p for p in polys if len(p) > 1]


def _svg_to_polylines(svg_text):
    """Converte o SVG inteiro em uma lista de polilinhas (coordenadas do viewBox)."""
    root = ET.fromstring(svg_text)
    out = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        a = el.attrib
        if tag == "path":
            out += _path_to_polylines(a["d"])
        elif tag == "line":
            out.append([(float(a["x1"]), float(a["y1"])), (float(a["x2"]), float(a["y2"]))])
        elif tag in ("polyline", "polygon"):
            v = [float(s) for s in _NUM_RE.findall(a["points"])]
            pts = list(zip(v[0::2], v[1::2]))
            if tag == "polygon":
                pts.append(pts[0])
            out.append(pts)
        elif tag == "circle":
            cx, cy, r = float(a["cx"]), float(a["cy"]), float(a["r"])
            out.append([(cx + r * math.cos(2 * math.pi * k / 48),
                         cy + r * math.sin(2 * math.pi * k / 48)) for k in range(49)])
    return out


def _png_bytes(w, h, rows):
    """Monta um PNG RGBA a partir de linhas de bytes (sem bibliotecas externas)."""
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))


def _photo_from_rows(w, h, rows):
    data = base64.b64encode(_png_bytes(w, h, rows))
    return tk.PhotoImage(master=tk._default_root, data=data, format="png")


def _rgb(color):
    if isinstance(color, str) and color.startswith("#") and len(color) == 7:
        return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b = tk._default_root.winfo_rgb(color)
    return (r >> 8, g >> 8, b >> 8)


_MASK_CACHE = {}
_ICON_CACHE = {}
_MASK_DISK = {"loaded": False, "dirty": False, "path": None, "sig": None}
_MASK_ALGO_VERSION = 2


def _mask_disk_sig():
    if _MASK_DISK["sig"] is None:
        _MASK_DISK["sig"] = "%d-%08x" % (_MASK_ALGO_VERSION,
                                         zlib.crc32(repr(sorted(SVG_ICONS.items())).encode("utf-8")) & 0xFFFFFFFF)
    return _MASK_DISK["sig"]


def _load_mask_disk_cache():
    """Carrega as máscaras de ícone já calculadas (evita recalcular tudo a cada abertura do app)."""
    if _MASK_DISK["loaded"]:
        return
    _MASK_DISK["loaded"] = True
    try:
        _MASK_DISK["path"] = os.path.join(DATA_DIR, "icon_cache.json")
        with open(_MASK_DISK["path"], "r", encoding="utf-8") as f:
            blob = json.load(f)
        if blob.get("sig") != _mask_disk_sig():
            return
        for k, v in blob.get("masks", {}).items():
            name, size, stroke = k.split("|")
            size = int(size)
            raw = base64.b64decode(v)
            if len(raw) == size * size:
                _MASK_CACHE[(name, size, float(stroke))] = raw
    except Exception:
        pass


def flush_mask_disk_cache():
    """Grava no disco as máscaras novas (se houver). Nunca atrapalha o app se falhar."""
    if not _MASK_DISK["dirty"]:
        return
    try:
        masks = {"%s|%d|%r" % (n, sz, float(st)): base64.b64encode(m).decode("ascii")
                 for (n, sz, st), m in _MASK_CACHE.items()}
        tmp = _MASK_DISK["path"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"sig": _mask_disk_sig(), "masks": masks}, f)
        os.replace(tmp, _MASK_DISK["path"])
        _MASK_DISK["dirty"] = False
    except Exception:
        pass


def _icon_alpha(name, size, stroke):
    """Máscara de cobertura do ícone (size*size bytes, 0..255), com suavização por supersampling 4x."""
    _load_mask_disk_cache()
    key = (name, size, float(stroke))
    mask = _MASK_CACHE.get(key)
    if mask is not None:
        return mask
    SS = 4
    N = size * SS
    scale = N / 24.0
    r = stroke * scale / 2
    r2 = r * r
    hi = [bytearray(N) for _ in range(N)]
    for pl in _svg_to_polylines(SVG_ICONS[name]):
        for (ax, ay), (bx, by) in zip(pl, pl[1:]):
            ax, ay, bx, by = ax * scale, ay * scale, bx * scale, by * scale
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            x0, x1 = max(0, int(min(ax, bx) - r)), min(N - 1, int(max(ax, bx) + r) + 1)
            y0, y1 = max(0, int(min(ay, by) - r)), min(N - 1, int(max(ay, by) + r) + 1)
            for py in range(y0, y1 + 1):
                row, cy = hi[py], py + 0.5
                for px in range(x0, x1 + 1):
                    cx = px + 0.5
                    t = ((cx - ax) * dx + (cy - ay) * dy) / L2 if L2 else 0.0
                    t = 0.0 if t < 0 else 1.0 if t > 1 else t
                    ex, ey = ax + t * dx - cx, ay + t * dy - cy
                    if ex * ex + ey * ey <= r2:
                        row[px] = 1
    out = bytearray(size * size)
    full = SS * SS
    for fy in range(size):
        sums = [0] * size
        for k in range(SS):
            line = hi[fy * SS + k]
            for fx in range(size):
                sums[fx] += sum(line[fx * SS:fx * SS + SS])
        base = fy * size
        for fx in range(size):
            out[base + fx] = int(sums[fx] / full * 255 + 0.5)
    mask = bytes(out)
    _MASK_CACHE[key] = mask
    _MASK_DISK["dirty"] = True
    return mask


def get_icon(name, size, color, stroke=2.0, pad_l=0, pad_r=0):
    """Devolve um PhotoImage (PNG com transparência) do ícone SVG na cor pedida.
    pad_l / pad_r acrescentam margem transparente à esquerda / direita do ícone."""
    key = (name, size, color, stroke, pad_l, pad_r)
    img = _ICON_CACHE.get(key)
    if img is None:
        r, g, b = _rgb(color)
        left, right = bytes(4 * pad_l), bytes(4 * pad_r)
        alpha = _icon_alpha(name, size, stroke)
        rr, gg, bb = bytes((r,)) * size, bytes((g,)) * size, bytes((b,)) * size
        rows = []
        for y in range(size):
            row = bytearray(4 * size)
            row[0::4] = rr
            row[1::4] = gg
            row[2::4] = bb
            row[3::4] = alpha[y * size:(y + 1) * size]
            rows.append(left + bytes(row) + right)
        img = _photo_from_rows(size + pad_l + pad_r, size, rows)
        _ICON_CACHE[key] = img
    return img


_PILL_CACHE = {}


def pill_image(w, h, color):
    """Cápsula totalmente arredondada (bordas suavizadas) para a barra de rolagem."""
    h = max(h, w)
    key = (w, h, color)
    img = _PILL_CACHE.get(key)
    if img is None:
        if len(_PILL_CACHE) > 60:      # a barra guarda a própria referência das imagens em uso
            _PILL_CACHE.clear()
        r = w / 2.0
        R, G, B = _rgb(color)

        def make_row(cy):
            ay = min(max(cy, r), h - r)
            out = bytearray()
            for px in range(w):
                d = math.hypot(px + 0.5 - r, cy - ay)
                a = max(0.0, min(1.0, r - d + 0.5))
                out += bytes((R, G, B, int(a * 255 + 0.5)))
            return bytes(out)

        rows, mid = [], None
        for py in range(h):
            cy = py + 0.5
            if r <= cy <= h - r:
                mid = mid or make_row(cy)
                rows.append(mid)
            else:
                rows.append(make_row(cy))
        img = _photo_from_rows(w, h, rows)
        _PILL_CACHE[key] = img
    return img


_SWATCH_CACHE = {}


def swatch_image(color, ring_color=None, size=36):
    """Bolinha de cor com bordas suavizadas (antialiasing). Com ring_color, desenha o anel de seleção.
    Fundo transparente, então funciona sobre qualquer tema. Substitui o oval do Canvas do Tk, que é serrilhado."""
    key = (color, ring_color, size)
    img = _SWATCH_CACHE.get(key)
    if img is not None:
        return img
    c = size / 2.0
    r_fill = size * 0.305                     # raio da bolinha
    r_in, r_out = size * 0.40, size * 0.485   # anel de seleção (com folga em relação à bolinha)
    fr, fg, fb = _rgb(color)
    rr, rg, rb = _rgb(ring_color) if ring_color else (0, 0, 0)
    SS = 4                                    # supersampling 4x4 por pixel: borda bem lisa
    rows = []
    for py in range(size):
        row = bytearray(4 * size)
        for px in range(size):
            a_fill = a_ring = 0
            total = SS * SS
            dc = math.hypot(px + 0.5 - c, py + 0.5 - c)       # distância do centro do pixel
            if dc + 0.71 <= r_fill:
                a_fill = total                                 # pixel inteiro dentro da bolinha
            elif dc - 0.71 > r_out or (dc - 0.71 > r_fill and dc + 0.71 < (r_in if ring_color else 1e9)):
                pass                                           # fora de tudo / na folga entre bolinha e anel
            elif ring_color and dc - 0.71 >= r_in and dc + 0.71 <= r_out:
                a_ring = total                                 # pixel inteiro dentro do anel
            else:
                for sy in range(SS):
                    dy = py + (sy + 0.5) / SS - c
                    for sx in range(SS):
                        dx = px + (sx + 0.5) / SS - c
                        d = math.hypot(dx, dy)
                        if d <= r_fill:
                            a_fill += 1
                        elif ring_color and r_in <= d <= r_out:
                            a_ring += 1
            if a_fill or a_ring:
                s = a_fill + a_ring
                i = 4 * px
                row[i] = int((fr * a_fill + rr * a_ring) / s + 0.5)
                row[i + 1] = int((fg * a_fill + rg * a_ring) / s + 0.5)
                row[i + 2] = int((fb * a_fill + rb * a_ring) / s + 0.5)
                row[i + 3] = int(s / total * 255 + 0.5)
        rows.append(bytes(row))
    img = _photo_from_rows(size, size, rows)
    _SWATCH_CACHE[key] = img
    return img


class HighlightLabel(tk.Text):
    """Widget de texto leve para destacar pesquisas."""
    def __init__(self, parent, text="", bg=None, fg=None, font=None, height=1, **kwargs):
        kwargs.setdefault("cursor", "hand2")
        super().__init__(parent, height=height, width=self._fit_width(text), wrap="none",
                         bd=0, highlightthickness=0, relief="flat", bg=bg, fg=fg, font=font,
                         exportselection=False, takefocus=0, insertwidth=0, **kwargs)
        if bg:
            # mesmo que algo crie uma seleção, ela fica invisível
            self.configure(selectbackground=bg, inactiveselectbackground=bg,
                           selectforeground=fg or "black")
        # tira os comportamentos padrão do widget de texto (selecionar arrastando,
        # duplo/triplo clique, foco, cursor). Os cliques do app continuam funcionando.
        self.bindtags((str(self), str(self.winfo_toplevel()), "all"))
        self.default_bg = bg
        self.default_fg = fg
        self.full_text = text
        self.insert("1.0", text)
        self.configure(state="disabled")

    @staticmethod
    def _fit_width(text):
        """Reserva só o espaço do texto (o padrão do Tk é 80 caracteres, o que empurrava botões pra fora)."""
        return max(1, len(text or "") + 1)

    def set_text(self, text, query="", highlight_bg="#FDE047", highlight_fg="#0F172A"):
        self.configure(state="normal", width=self._fit_width(text))
        self.delete("1.0", "end")
        self.full_text = text
        self.insert("1.0", text)

        self.tag_remove("highlight", "1.0", "end")

        if query and query in text.lower():
            self.tag_configure("highlight", background=highlight_bg, foreground=highlight_fg)
            lower_text = text.lower()
            q_len = len(query)
            start_idx = 0

            while True:
                idx = lower_text.find(query, start_idx)
                if idx == -1:
                    break
                pos_start = f"1.0 + {idx} chars"
                pos_end = f"1.0 + {idx + q_len} chars"
                self.tag_add("highlight", pos_start, pos_end)
                start_idx = idx + q_len

        self.configure(state="disabled")

    def set_colors(self, bg=None, fg=None):
        """Troca as cores do rótulo (usado ao mudar a cor de uma categoria)."""
        bg = bg or self.default_bg
        fg = fg or self.default_fg
        self.default_bg, self.default_fg = bg, fg
        self.configure(bg=bg, fg=fg, selectbackground=bg, inactiveselectbackground=bg,
                       selectforeground=fg or "black")

    def bind_events(self, click_cmd, menu_cmd):
        self.bind("<Button-1>", click_cmd)
        self.bind("<Button-3>", menu_cmd)
        self.bind("<Control-Button-1>", menu_cmd)

class RoundButton(tk.Canvas):
    def __init__(self, parent, text, command=None, bg="#6366F1", fg="white",
                 hover_bg=None, width=None, height=36, radius=12, font=None,
                 padx=16, icon=None, icon_size=16, icon_stroke=2.0, icon_dy=0, **kwargs):
        super().__init__(parent, highlightthickness=0, bd=0,
                         bg=kwargs.pop("parent_bg", parent["bg"]), **kwargs)
        self.command = command
        self.bg_color = bg
        self.hover_color = hover_bg or self._shade(bg, 0.9)
        self.fg = fg
        self.radius = radius
        self.font = font or (FONT_FAMILY, 10, "bold")
        self.text = text
        self.padx = padx
        self.icon = icon
        self.icon_size = icon_size
        self.icon_stroke = icon_stroke
        self.icon_dy = icon_dy   # ajuste fino vertical (px) para alinhar o ícone ao texto
        self.btn_height = height
        self.btn_width = width
        self.configure(cursor="hand2")
        self._draw(width, height)
        self.bind("<Enter>", lambda e: self._draw(self.btn_width, self.btn_height, hover=True))
        self.bind("<Leave>", lambda e: self._draw(self.btn_width, self.btn_height, hover=False))
        self.bind("<Button-1>", self._on_click)

    @staticmethod
    def _shade(hexcolor, factor):
        hexcolor = hexcolor.lstrip("#")
        r, g, b = (int(hexcolor[i:i + 2], 16) for i in (0, 2, 4))
        r, g, b = (max(0, min(255, int(c * factor))) for c in (r, g, b))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _rounded_rect(self, x1, y1, x2, y2, r, **kw):
        points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
                  x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.create_polygon(points, smooth=True, **kw)

    def _draw(self, width, height, hover=False, pressed=False):
        self.delete("all")
        font_obj = tkfont.Font(font=self.font)
        text_w = font_obj.measure(self.text) if self.text else 0
        icon_w = self.icon_size if self.icon else 0
        gap = 6 if (self.icon and self.text) else 0
        content_w = icon_w + gap + text_w
        needed = content_w + self.padx * 2
        w = max(width, needed) if width else needed
        h = height
        self.btn_width, self.btn_height = w, h
        self.config(width=w, height=h)
        color = self.hover_color if hover else self.bg_color
        inset = 1 if pressed else 0
        y_off = 1 if pressed else 0
        color = self._shade(color, 0.85) if pressed else color
        self._rounded_rect(1 + inset, 1 + inset + y_off, w - 1 - inset, h - 1 - inset + y_off,
                           max(2, self.radius - inset), fill=color, outline="")
        start_x = w / 2 - content_w / 2
        # O Tk centraliza a "caixa" da linha (ascent+descent), e as letras ficam mais baixas que o
        # centro do botão. Sobe o texto pela diferença entre a linha-base e o centro óptico das letras.
        size = font_obj.cget("size")
        px = -size if size < 0 else size * self.winfo_fpixels("1p")
        baseline_off = (font_obj.metrics("ascent") - font_obj.metrics("descent")) / 2
        text_dy = -round(max(0.0, min(4.0, baseline_off - 0.30 * px)))
        if self.icon:
            img = get_icon(self.icon, self.icon_size, self.fg, self.icon_stroke)
            self.create_image(start_x, h / 2 + y_off + self.icon_dy, image=img, anchor="w")
        if self.text:
            self.create_text(start_x + icon_w + gap, h / 2 + y_off + text_dy, text=self.text,
                             fill=self.fg, font=self.font, anchor="w")

    def set_bg(self, bg, hover_bg=None, canvas_bg=None):
        self.bg_color = bg
        self.hover_color = hover_bg or self._shade(bg, 0.9)
        if canvas_bg is not None:
            try:
                self.configure(bg=canvas_bg)
            except tk.TclError:
                pass
        self._draw(self.btn_width, self.btn_height)

    def _on_click(self, event):
        try:
            self._draw(self.btn_width, self.btn_height, hover=True, pressed=True)
        except tk.TclError:
            pass
        toplevel = self.winfo_toplevel()
        toplevel.after(80, self._release_and_fire)

    def _release_and_fire(self):
        try:
            self._draw(self.btn_width, self.btn_height, hover=True, pressed=False)
        except tk.TclError:
            pass
        if self.command:
            self.command()

class RoundScrollbar(tk.Canvas):
    """Barra de rolagem vertical personalizada: trilha e "polegar" em formato de cápsula,
    totalmente arredondados e suavizados. As cores vêm da paleta do tema."""

    TRACK_W = 10          # largura da trilha
    THUMB_W = 6           # largura do polegar em repouso
    THUMB_W_ACTIVE = 8    # largura com o mouse em cima / arrastando

    def __init__(self, parent, command=None, width=16, track_bg="#FFFFFF", track="#E9EEF5",
                 thumb="#94A3B8", thumb_hover="#6366F1", pad=3, min_thumb=36, **kwargs):
        super().__init__(parent, width=width, bg=track_bg, highlightthickness=0, bd=0, **kwargs)
        self.command = command
        self.track_color = track
        self.thumb_color = thumb
        self.thumb_hover = thumb_hover
        self.pad = pad
        self.min_thumb = min_thumb
        self._first, self._last = 0.0, 1.0
        self._hover = False
        self._dragging = False
        self._grab_offset = 0
        self._track_img = None   # referências para o Tk não descartar as imagens em uso
        self._thumb_img = None
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

    # --- API compatível com ttk.Scrollbar ---
    def set(self, first, last):
        self._first, self._last = float(first), float(last)
        self._draw()

    # --- geometria ---
    def _thumb_bounds(self):
        h = self.winfo_height()
        avail = max(1, h - 2 * self.pad)
        visible = self._last - self._first
        size = min(avail, max(self.min_thumb, visible * avail))
        span = avail - size
        y1 = self.pad + (self._first / (1 - visible) * span if visible < 1 else 0)
        return y1, y1 + size, avail, size

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if self._last - self._first >= 0.9999 or h < 2 * self.pad + self.min_thumb:
            return  # tudo cabe na tela: não mostra a barra
        cx = w / 2
        track_w = min(self.TRACK_W, max(2, w - 2))
        self._track_img = pill_image(track_w, h - 2 * self.pad, self.track_color)
        self.create_image(cx, self.pad, image=self._track_img, anchor="n")

        y1, y2, _, _ = self._thumb_bounds()
        active = self._hover or self._dragging
        thumb_w = self.THUMB_W_ACTIVE if active else self.THUMB_W
        color = self.thumb_hover if active else self.thumb_color
        self._thumb_img = pill_image(thumb_w, int(round(y2 - y1)), color)
        self.create_image(cx, int(round(y1)), image=self._thumb_img, anchor="n")

    # --- interação ---
    def _set_hover(self, value):
        self._hover = value
        self._draw()

    def _scroll_to_thumb_top(self, y_top):
        _, _, avail, size = self._thumb_bounds()
        span = avail - size
        if span <= 0:
            return
        visible = self._last - self._first
        frac = (y_top - self.pad) / span * (1 - visible)
        frac = max(0.0, min(1 - visible, frac))
        if self.command:
            self.command("moveto", frac)

    def _on_press(self, event):
        if self._last - self._first >= 0.9999:
            return
        y1, y2, _, size = self._thumb_bounds()
        if y1 <= event.y <= y2:
            self._grab_offset = event.y - y1
        else:  # clique na trilha: centraliza o polegar no ponto clicado
            self._grab_offset = size / 2
            self._scroll_to_thumb_top(event.y - self._grab_offset)
        self._dragging = True
        self._draw()

    def _on_drag(self, event):
        if self._dragging:
            self._scroll_to_thumb_top(event.y - self._grab_offset)

    def _on_release(self, event):
        self._dragging = False
        self._draw()

OFFSCREEN = -32000      # posição fora de qualquer monitor: a janela é montada ali e só depois vem para a tela


class Tooltip:
    _TRANSPARENT_KEY = "#123456"
    _FONT = (FONT_FAMILY, 10, "bold")

    def __init__(self, root):
        self.root = root
        self.win = None
        self._anim_job = None
        self._tail_dx = 0
        self._tail_up = False

    def hide(self):
        if self._anim_job is not None:
            try:
                self.root.after_cancel(self._anim_job)
            except Exception:
                pass
            self._anim_job = None
        if self.win is not None:
            try:
                self.win.destroy()
            except Exception:
                pass
            self.win = None

    def show(self, message, x, y, bg="#10B981", fg="white", ms=1200, page_bg="#F8FAFC", anchor=None):
        """Mostra o balão. Com `anchor` (um widget, ex.: o botão clicado), o balão fica centralizado
        em cima dele com a ponta apontando para o meio do botão; sem `anchor`, aponta para (x, y)."""
        self.hide()
        win = tk.Toplevel(self.root)
        self.win = win
        win.overrideredirect(True)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass

        use_transparency = sys.platform.startswith("win")
        win_bg = self._TRANSPARENT_KEY if use_transparency else page_bg
        win.configure(bg=win_bg)
        if use_transparency:
            try:
                win.attributes("-transparentcolor", self._TRANSPARENT_KEY)
            except Exception:
                win.configure(bg=page_bg)

        tkf = tkfont.Font(font=self._FONT)
        text_w = tkf.measure(message)
        pad_x, pad_y, tail_h = 16, 10, 8
        bubble_w = text_w + pad_x * 2
        bubble_h = tkf.metrics("linespace") + pad_y * 2
        bubble_w += bubble_w % 2          # medidas pares: o centro cai num pixel inteiro (sem meio-pixel
        bubble_h += bubble_h % 2          # de diferença entre as margens esquerda/direita e cima/baixo)
        total_w = bubble_w + 4
        total_h = bubble_h + tail_h + 4

        try:
            app_left = self.root.winfo_rootx()
            app_top = self.root.winfo_rooty()
            app_right = app_left + self.root.winfo_width()
            app_bottom = app_top + self.root.winfo_height()
        except Exception:
            app_left = app_top = app_right = app_bottom = None

        # ponto para onde a ponta do balão aponta
        above_y = below_y = y
        if anchor is not None:
            try:
                x = anchor.winfo_rootx() + anchor.winfo_width() / 2
                above_y = anchor.winfo_rooty() - 2                       # logo acima do botão
                below_y = anchor.winfo_rooty() + anchor.winfo_height() + 2
            except tk.TclError:
                pass
        else:
            below_y = y + 20

        top_bound = app_top if app_top is not None else 0
        tail_up = above_y - total_h < top_bound          # sem espaço em cima: abre embaixo
        win_y = int(below_y) if tail_up else int(above_y - total_h)
        win_x = int(round(x - total_w / 2))

        if app_left is not None and app_right is not None:
            win_x = max(app_left, min(win_x, app_right - total_w))
        if app_top is not None and app_bottom is not None:
            win_y = max(app_top, min(win_y, app_bottom - total_h))

        # se o balão encostou na borda do app, só a ponta se desloca: continua apontando para o botão
        self._tail_dx = (x - win_x) - total_w / 2
        self._tail_up = tail_up

        canvas = tk.Canvas(win, width=total_w, height=total_h, highlightthickness=0, bg=win_bg, bd=0)
        canvas.pack()
        self._canvas = canvas
        self._bubble_w, self._bubble_h, self._tail_h = bubble_w, bubble_h, tail_h
        self._bg, self._fg, self._message = bg, fg, message

        win.geometry(f"{total_w}x{total_h}+{OFFSCREEN}+{OFFSCREEN}")   # 1º quadro desenhado fora da tela
        self._draw_balloon(0.3)
        try:
            win.update_idletasks()
            win.geometry(f"+{win_x}+{win_y}")
        except tk.TclError:
            pass

        self._animate_in(0)
        self._anim_job = self.root.after(ms, self._animate_out)

    def _draw_balloon(self, scale):
        c = self._canvas
        try:
            c.delete("all")
        except tk.TclError:
            self.win = None
            return
        bw, bh, th = self._bubble_w, self._bubble_h, self._tail_h
        top = 2 + (th if self._tail_up else 0)
        cx, cy = 2 + bw / 2, top + bh / 2
        w, h = bw * scale, bh * scale
        x1, y1 = cx - w / 2, cy - h / 2
        x2, y2 = cx + w / 2, cy + h / 2
        r = min(12 * scale, h / 2, w / 2)
        if w < 2 or h < 2:
            return
        points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
                  x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        c.create_polygon(points, smooth=True, fill=self._bg, outline="")
        # ponta: no meio do balão, ou deslocada para continuar apontando para o botão
        half = 6 * scale
        lim = max(0.0, w / 2 - r - half)
        tx = cx + max(-lim, min(self._tail_dx * scale, lim))
        if self._tail_up:
            c.create_polygon(tx - half, y1 + 1, tx + half, y1 + 1, tx, y1 - th * scale,
                             fill=self._bg, outline="")
        else:
            c.create_polygon(tx - half, y2 - 1, tx + half, y2 - 1, tx, y2 + th * scale,
                             fill=self._bg, outline="")
        if scale > 0.6:
            # texto SEMPRE no centro exato do balão (horizontal e vertical)
            c.create_text(round(cx), round(cy), text=self._message, fill=self._fg, anchor="center",
                          justify="center", font=(FONT_FAMILY, max(8, int(10 * min(scale, 1))), "bold"))

    def _animate_in(self, step):
        keyframes = [0.3, 0.7, 1.05, 0.98, 1.0]
        if step >= len(keyframes) or self.win is None:
            return
        self._draw_balloon(keyframes[step])
        self._anim_job = self.root.after(20, lambda: self._animate_in(step + 1))

    def _animate_out(self, step=0):
        if self.win is None:
            return
        keyframes = [1.0, 0.8, 0.5, 0.2, 0.0]
        if step >= len(keyframes):
            self.hide()
            return
        self._draw_balloon(keyframes[step])
        self._anim_job = self.root.after(25, lambda: self._animate_out(step + 1))

def _hwnd_of(win):
    import ctypes
    return ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()


def apply_titlebar_theme(win, palette):
    """Windows: barra de título escura/clara conforme o tema e, no Windows 11, na cor do app.
    Devolve True se o Windows aceitou a cor (Win11), False se não aceitou (Win10) e None fora do Windows."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        from ctypes import wintypes
        win.update_idletasks()
        hwnd = _hwnd_of(win)
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                              wintypes.LPCVOID, wintypes.DWORD]

        def set_attr(attr, value):
            v = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))

        def colorref(hex_color):                       # COLORREF = 0x00BBGGRR
            r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
            return r | (g << 8) | (b << 16)

        dark = 1 if palette["bg"] == PALETTES["dark"]["bg"] else 0
        if set_attr(20, dark) != 0:                    # DWMWA_USE_IMMERSIVE_DARK_MODE
            set_attr(19, dark)                         # Windows 10 mais antigo
        ok = set_attr(35, colorref(palette["titlebar_bg"])) == 0   # DWMWA_CAPTION_COLOR (só Windows 11)
        set_attr(36, colorref(palette["text"]))        # DWMWA_TEXT_COLOR
        set_attr(34, colorref(palette["titlebar_bg"])) # DWMWA_BORDER_COLOR
        # força o Windows a redesenhar a moldura (senão a cor só muda ao reabrir a janela)
        user32 = ctypes.windll.user32
        SWP = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020   # NOSIZE|NOMOVE|NOZORDER|NOACTIVATE|FRAMECHANGED
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP)
        user32.SendMessageW(hwnd, 0x0086, 0, 0)        # WM_NCACTIVATE (inativa)
        user32.SendMessageW(hwnd, 0x0086, 1, 0)        # WM_NCACTIVATE (ativa)
        return ok
    except Exception as e:
        print(f"[{APP_NAME}] Falha ao aplicar tema na barra de título: {e}", file=sys.stderr)
        return None


def _win_cursor_pos():
    import ctypes
    from ctypes import wintypes
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _win_rect(hwnd):
    import ctypes
    from ctypes import wintypes
    r = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def _win_move(hwnd, x, y):
    import ctypes
    from ctypes import wintypes
    SWP = 0x0001 | 0x0004 | 0x0010            # NOSIZE | NOZORDER | NOACTIVATE
    f = ctypes.windll.user32.SetWindowPos
    f.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    f(wintypes.HWND(hwnd), None, int(x), int(y), 0, 0, SWP)


def _install_frameless_hook(win, hwnd):
    """Intercepta as mensagens de moldura do Windows para a área do app ocupar a janela até o topo.
    Isso elimina a linha branca de 1px que o Windows desenha acima da barra própria, e impede que ela
    volte ao focar/desfocar, minimizar/restaurar ou maximizar/restaurar a janela.
    Bordas esquerda/direita/inferior continuam nativas (redimensionar segue funcionando)."""
    import ctypes
    from ctypes import wintypes
    hook = getattr(win, "_frameless_hook", None)
    if hook is not None and hook[2] == hwnd:
        return                                   # já instalado nesta janela
    user32 = ctypes.windll.user32
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = [("rgrc", RECT * 3), ("lppos", ctypes.c_void_p)]

    set_long = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
    set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    set_long.restype = ctypes.c_void_p
    call_proc = user32.CallWindowProcW
    call_proc.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    call_proc.restype = LRESULT
    user32.IsZoomed.argtypes = [wintypes.HWND]

    WM_NCCALCSIZE, WM_NCPAINT, WM_NCACTIVATE, GWLP_WNDPROC = 0x0083, 0x0085, 0x0086, -4
    old_proc = {"ptr": None}
    def wnd_proc(h, msg, wparam, lparam):
        try:
            if msg == WM_NCCALCSIZE:
                if wparam:
                    top = ctypes.cast(lparam, ctypes.POINTER(NCCALCSIZE_PARAMS)).contents.rgrc[0].top
                    res = call_proc(old_proc["ptr"], h, msg, wparam, lparam)
                    if not user32.IsZoomed(h):          # maximizada: deixa o Windows ajustar (senão vaza da tela)
                        ctypes.cast(lparam, ctypes.POINTER(NCCALCSIZE_PARAMS)).contents.rgrc[0].top = top
                    return res
                top = ctypes.cast(lparam, ctypes.POINTER(RECT)).contents.top
                res = call_proc(old_proc["ptr"], h, msg, wparam, lparam)
                if not user32.IsZoomed(h):
                    ctypes.cast(lparam, ctypes.POINTER(RECT)).contents.top = top
                return res
            if msg == WM_NCPAINT:
                return 0                                 # ninguém desenha a moldura nativa por cima do app
            if msg == WM_NCACTIVATE:
                # lparam = -1: ativa/desativa sem redesenhar a moldura (é o que fazia a linha voltar)
                return call_proc(old_proc["ptr"], h, msg, wparam, -1)
        except Exception:
            pass
        return call_proc(old_proc["ptr"], h, msg, wparam, lparam)

    proc = WNDPROC(wnd_proc)
    old_proc["ptr"] = set_long(hwnd, GWLP_WNDPROC, ctypes.cast(proc, ctypes.c_void_p))
    win._frameless_hook = (proc, old_proc, hwnd)    # guarda a referência (senão o Python apaga o callback)


_FRAME_API = {}


def _frame_api():
    """Prepara uma única vez as chamadas do Windows usadas na checagem da moldura."""
    if not _FRAME_API:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        _FRAME_API["user32"] = user32
    return _FRAME_API["user32"]


def windows_border_color():
    """Cor da linha fina que o Windows 10 desenha nas bordas da janela.
    Se 'mostrar cor de destaque nas bordas' estiver ligado, é a cor de destaque; senão, o cinza padrão."""
    default = "#313131"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as k:
            if winreg.QueryValueEx(k, "ColorPrevalence")[0] == 1:
                abgr = winreg.QueryValueEx(k, "AccentColor")[0]
                r, g, b = abgr & 0xFF, (abgr >> 8) & 0xFF, (abgr >> 16) & 0xFF
                return "#%02x%02x%02x" % (r, g, b)
    except Exception:
        pass
    return default


def strip_native_caption(win):
    """Remove a barra de título nativa mantendo bordas redimensionáveis, botão na barra de tarefas,
    minimizar/maximizar. A barra visível passa a ser a do app. Pode ser chamada quantas vezes quiser:
    só mexe na janela se o Windows/Tk tiver recolocado a barra ou recriado a janela."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = _frame_api()
        hwnd = _hwnd_of(win)
        GWL_STYLE = -16
        WS_CAPTION, WS_SYSMENU, WS_THICKFRAME, WS_MINBOX, WS_MAXBOX = 0x00C00000, 0x80000, 0x40000, 0x20000, 0x10000
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        new = (style & ~WS_CAPTION) | WS_SYSMENU | WS_THICKFRAME | WS_MINBOX | WS_MAXBOX
        hook = getattr(win, "_frameless_hook", None)
        if new == style and hook is not None and hook[2] == hwnd:
            return                                   # caminho rápido: nada a fazer
        if new != style:
            user32.SetWindowLongW(hwnd, GWL_STYLE, new)
        hook = getattr(win, "_frameless_hook", None)
        need_hook = hook is None or hook[2] != hwnd
        if need_hook:
            try:
                _install_frameless_hook(win, hwnd)
            except Exception as e:
                print(f"[{APP_NAME}] Falha ao remover a linha branca da barra: {e}", file=sys.stderr)
            try:   # Windows 11: borda do DWM = "nenhuma" (no Windows 10 o atributo é ignorado)
                import ctypes as _c
                none = _c.c_uint(0xFFFFFFFE)
                _c.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 34, _c.byref(none), _c.sizeof(none))
            except Exception:
                pass
        if new != style or need_hook:
            SWP = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020   # NOSIZE|NOMOVE|NOZORDER|NOACTIVATE|FRAMECHANGED
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP)
    except Exception as e:
        print(f"[{APP_NAME}] Falha ao remover a barra de título nativa: {e}", file=sys.stderr)


# ----------------------------------------------------------------------
#  Botões da barra de título: glifos desenhados pixel a pixel (traço de 1px, mesmo peso e mesma cor),
#  como os do Windows. Os ícones SVG antialiased ficavam com pesos/brilhos diferentes entre si.
# ----------------------------------------------------------------------
_GLYPH_CACHE = {}
_GLYPH_SIZE = 16


def _glyph_pixels(kind):
    """Devolve {(x, y): cobertura 0..1} para o glifo, num quadrado de 16x16."""
    px = {}

    def hline(y, x0, x1):
        for x in range(x0, x1 + 1):
            px[(x, y)] = 1.0

    def vline(x, y0, y1):
        for y in range(y0, y1 + 1):
            px[(x, y)] = 1.0

    def box(x0, y0, x1, y1):
        hline(y0, x0, x1); hline(y1, x0, x1)
        vline(x0, y0, y1); vline(x1, y0, y1)

    if kind == "minus":
        hline(8, 3, 12)
    elif kind == "maximize":
        box(3, 3, 12, 12)
    elif kind == "restore":
        box(5, 3, 12, 10)                                  # quadrado de trás
        for y in range(5, 13):                             # apaga a parte coberta pelo da frente
            for x in range(3, 11):
                px.pop((x, y), None)
        box(3, 5, 10, 12)                                  # quadrado da frente
    elif kind == "x":
        SS, half = 6, 0.62                                 # supersampling; meia-espessura do traço
        for y in range(3, 13):
            for x in range(3, 13):
                hit = 0
                for sy in range(SS):
                    for sx in range(SS):
                        fx = x + (sx + 0.5) / SS
                        fy = y + (sy + 0.5) / SS
                        d1 = abs((fx - 3.5) - (fy - 3.5)) / 1.4142
                        d2 = abs((fx - 3.5) + (fy - 3.5) - 9.0) / 1.4142
                        if min(d1, d2) <= half:
                            hit += 1
                if hit:
                    px[(x, y)] = hit / (SS * SS)
    return px


def get_titlebar_glyph(kind, color):
    key = (kind, color)
    img = _GLYPH_CACHE.get(key)
    if img is None:
        r, g, b = _rgb(color)
        size = _GLYPH_SIZE
        cover = _glyph_pixels(kind)
        rows = []
        for y in range(size):
            row = bytearray(4 * size)
            for x in range(size):
                a = cover.get((x, y))
                if a:
                    i = 4 * x
                    row[i], row[i + 1], row[i + 2], row[i + 3] = r, g, b, int(a * 255 + 0.5)
            rows.append(bytes(row))
        img = _photo_from_rows(size, size, rows)
        _GLYPH_CACHE[key] = img
    return img


# ----------------------------------------------------------------------
#  Ícone da Mhnet na barra: redução com média de área (suave) em vez do "subsample" do Tk,
#  que só pega 1 pixel a cada N e deixava o ícone serrilhado e com cara de cortado.
# ----------------------------------------------------------------------
def _decode_png_rgba(path):
    """Decodifica PNG não entrelaçado (8 ou 16 bits; tons de cinza, RGB, paleta, com/sem alfa).
    Devolve (largura, altura, bytearray RGBA) ou levanta exceção se o formato não for suportado."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("não é PNG")
    pos, idat, plte, trns, hdr = 8, [], None, None, None
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if tag == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"PLTE":
            plte = body
        elif tag == b"tRNS":
            trns = body
        elif tag == b"IDAT":
            idat.append(body)
        elif tag == b"IEND":
            break
    w, h, depth, ctype, _, _, interlace = hdr
    if interlace or depth not in (8, 16) or ctype not in (0, 2, 3, 4, 6):
        raise ValueError("formato de PNG não suportado")
    if ctype == 3 and depth != 8:
        raise ValueError("paleta com profundidade != 8")
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    bpp = ch * (depth // 8)
    stride = w * bpp
    raw = zlib.decompress(b"".join(idat))
    out = bytearray(w * h * 4)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        if ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ft == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        prev = line
        step = depth // 8
        for x in range(w):
            o = (y * w + x) * 4
            q = x * bpp
            if ctype == 6:
                out[o:o + 4] = bytes((line[q], line[q + step], line[q + 2 * step], line[q + 3 * step]))
            elif ctype == 2:
                out[o:o + 4] = bytes((line[q], line[q + step], line[q + 2 * step], 255))
            elif ctype == 0:
                out[o:o + 4] = bytes((line[q], line[q], line[q], 255))
            elif ctype == 4:
                out[o:o + 4] = bytes((line[q], line[q], line[q], line[q + step]))
            else:  # paleta
                idx = line[q]
                a = trns[idx] if trns and idx < len(trns) else 255
                out[o:o + 4] = bytes((plte[idx * 3], plte[idx * 3 + 1], plte[idx * 3 + 2], a))
    return w, h, out


def _box_downscale(w, h, rgba, tw, th):
    """Redução por média de área (com alfa pré-multiplicado). Devolve linhas RGBA de tw x th."""
    rows = []
    for ty in range(th):
        y0, y1 = ty * h / th, (ty + 1) * h / th
        row = bytearray(4 * tw)
        for tx in range(tw):
            x0, x1 = tx * w / tw, (tx + 1) * w / tw
            sr = sg = sb = sa = wsum = 0.0
            for yy in range(int(y0), min(h, int(math.ceil(y1)))):
                wy = min(yy + 1, y1) - max(yy, y0)
                for xx in range(int(x0), min(w, int(math.ceil(x1)))):
                    wx = min(xx + 1, x1) - max(xx, x0)
                    wgt = wx * wy
                    o = (yy * w + xx) * 4
                    a = rgba[o + 3] / 255.0
                    sr += rgba[o] * a * wgt
                    sg += rgba[o + 1] * a * wgt
                    sb += rgba[o + 2] * a * wgt
                    sa += a * wgt
                    wsum += wgt
            if sa > 0 and wsum > 0:
                i = 4 * tx
                row[i] = min(255, int(sr / sa + 0.5))
                row[i + 1] = min(255, int(sg / sa + 0.5))
                row[i + 2] = min(255, int(sb / sa + 0.5))
                row[i + 3] = min(255, int(sa / wsum * 255 + 0.5))
        rows.append(bytes(row))
    return rows


def load_smooth_icon(path, target):
    """PhotoImage do PNG reduzido para target x target com boa qualidade (com cache em disco)."""
    try:
        st = os.stat(path)
        cache = os.path.join(DATA_DIR, "titlebar_icon_%d_%d_%d.png" % (target, st.st_size, int(st.st_mtime)))
        if os.path.exists(cache):
            return tk.PhotoImage(master=tk._default_root, file=cache)
        w, h, rgba = _decode_png_rgba(path)
        # mantém a proporção: encaixa no quadrado target x target (centralizado, sem cortar nada)
        if w >= h:
            tw, th = target, max(1, int(round(target * h / w)))
        else:
            tw, th = max(1, int(round(target * w / h))), target
        small = _box_downscale(w, h, rgba, tw, th)
        padl, padt = (target - tw) // 2, (target - th) // 2
        blank = bytes(4 * target)
        rows = [blank] * padt
        rows += [bytes(4 * padl) + r + bytes(4 * (target - tw - padl)) for r in small]
        rows += [blank] * (target - th - padt)
        png = _png_bytes(target, target, rows)
        try:
            with open(cache, "wb") as f:
                f.write(png)
        except Exception:
            pass
        return tk.PhotoImage(master=tk._default_root, data=base64.b64encode(png), format="png")
    except Exception as e:
        print(f"[{APP_NAME}] Falha ao reduzir o ícone da barra: {e}", file=sys.stderr)
        return None


class TitleButton(tk.Label):
    """Botão da barra de título (minimizar / maximizar / fechar) com ícone SVG e hover."""

    def __init__(self, parent, icon, command, bg, hover_bg, fg, hover_fg=None):
        self._bg, self._hover_bg, self._fg = bg, hover_bg, fg
        self._hover_fg = hover_fg or fg
        self._icon = icon
        self._command = command
        super().__init__(parent, image=get_titlebar_glyph(icon, fg), bg=bg, bd=0, width=46, height=34)
        self.bind("<Enter>", lambda e: self._paint(True))
        self.bind("<Leave>", lambda e: self._paint(False))
        self.bind("<ButtonRelease-1>", self._release)

    def _paint(self, hover):
        self.configure(bg=self._hover_bg if hover else self._bg,
                       image=get_titlebar_glyph(self._icon, self._hover_fg if hover else self._fg))

    def _release(self, event):
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self._command()

    def set_icon(self, icon):
        self._icon = icon
        self._paint(False)


class PopupMenu(tk.Toplevel):
    """Menu de contexto próprio (o nativo do Windows só alinha o conteúdo à esquerda).
    Cada item tem ícone + texto centralizados, hover colorido e fecha ao clicar fora, Esc ou perder o foco."""

    def __init__(self, root, palette, items, x, y):
        super().__init__(root)
        self.geometry(f"+{OFFSCREEN}+{OFFSCREEN}")       # monta fora da tela: aparece já desenhado
        self._root_win = root
        self._closed = False
        self._click_id = None
        self.overrideredirect(True)
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass
        p = palette
        self.configure(bg=p["border"])
        inner = tk.Frame(self, bg=p["card_bg"])
        inner.pack(padx=1, pady=1)                       # 1px de borda ao redor
        font = (FONT_FAMILY, 10)
        for label, icon, command in items:
            img = get_icon(icon, 14, p["text"])
            img_hi = get_icon(icon, 14, p["accent_text"])
            row = tk.Frame(inner, bg=p["card_bg"], cursor="hand2")
            row.pack(fill="x")
            box = tk.Frame(row, bg=p["card_bg"])
            box.pack(expand=True, padx=14, pady=6)                 # o bloco ícone+texto fica centralizado
            ic = tk.Label(box, image=img, bg=p["card_bg"], bd=0)
            ic.pack(side="left")
            tx = tk.Label(box, text=label, font=font, bg=p["card_bg"], fg=p["text"], bd=0)
            tx.pack(side="left", padx=(6, 0))                      # ícone bem perto do texto
            parts = (row, box, ic, tx)

            def hover(on, parts=parts, img=img, img_hi=img_hi):
                bg = p["accent"] if on else p["card_bg"]
                for w in parts:
                    w.configure(bg=bg)
                parts[2].configure(image=img_hi if on else img)
                parts[3].configure(fg=p["accent_text"] if on else p["text"])

            for w in parts:
                w.bind("<Enter>", lambda e, h=hover: h(True))
                w.bind("<Leave>", lambda e, h=hover: h(False))
                w.bind("<ButtonRelease-1>", lambda e, c=command, r=row: self._run(c, e, r))
        self.bind("<Escape>", lambda e: self.close())

        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.update()                                    # desenha tudo ainda fora da tela
        self.geometry(f"+{max(0, min(x, sw - w - 4))}+{max(0, min(y, sh - h - 4))}")
        self.lift()
        self.focus_force()
        # só depois do evento que abriu o menu, para ele não fechar na hora
        self.after(120, self._arm_close_handlers)

    def _arm_close_handlers(self):
        if self._closed:
            return
        self.bind("<FocusOut>", lambda e: self.after(60, self._close_if_unfocused))
        try:
            self._click_id = self._root_win.bind("<Button-1>", lambda e: self.close(), add="+")
        except tk.TclError:
            pass

    def _close_if_unfocused(self):
        try:
            if not self._closed and self.focus_displayof() is None:
                self.close()
        except tk.TclError:
            pass

    def _run(self, command, event, row):
        rx, ry = row.winfo_rootx(), row.winfo_rooty()
        if rx <= event.x_root < rx + row.winfo_width() and ry <= event.y_root < ry + row.winfo_height():
            self.close()
            command()

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._click_id is not None:
                self._root_win.unbind("<Button-1>", self._click_id)
        except tk.TclError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass


def attach_edit_menu(widget, palette):
    """Menu do botão direito (mesmo visual do Editar/Excluir) para campos de texto:
    Recortar, Copiar e Colar. Mostra só as opções que fazem sentido no momento.
    `palette` pode ser o dicionário de cores ou uma função que devolve o dicionário atual."""
    is_text = isinstance(widget, tk.Text)
    if not is_text:
        try:
            _p = palette() if callable(palette) else palette
            widget.configure(selectbackground=_p.get("select_bg", "#818CF8"),
                             selectforeground=_p.get("select_fg", "#0F172A"),
                             selectborderwidth=0)
        except tk.TclError:
            pass

    def has_sel():
        try:
            if is_text:
                return bool(widget.tag_ranges("sel"))
            return bool(widget.selection_present())
        except tk.TclError:
            return False

    def selected_text():
        try:
            if is_text:
                return widget.get("sel.first", "sel.last")
            a, b = widget.index("sel.first"), widget.index("sel.last")
            return widget.get()[a:b]
        except tk.TclError:
            return ""

    def clipboard_text():
        try:
            return widget.clipboard_get()
        except tk.TclError:
            return ""

    def copy():
        txt = selected_text()
        if txt:
            widget.clipboard_clear()
            widget.clipboard_append(txt)
        widget.focus_set()

    def cut():
        copy()
        try:
            widget.delete("sel.first", "sel.last")
        except tk.TclError:
            pass

    def paste():
        txt = clipboard_text()
        if not txt:
            return
        try:
            if has_sel():
                widget.delete("sel.first", "sel.last")
            widget.insert("insert", txt)
            if is_text:
                widget.see("insert")
            else:
                widget.xview_moveto(1.0) if widget.index("insert") >= len(widget.get()) else None
        except tk.TclError:
            pass
        widget.focus_set()

    def open_menu(event):
        try:
            widget.focus_set()
            if not has_sel():
                # sem seleção: o cursor de digitação vai para onde o usuário clicou (cola ali)
                if is_text:
                    widget.mark_set("insert", f"@{event.x},{event.y}")
                else:
                    widget.icursor(f"@{event.x}")
        except tk.TclError:
            pass
        items = []
        if has_sel():
            items += [("Recortar", "scissors", cut), ("Copiar", "copy", copy)]
        if clipboard_text():
            items.append(("Colar", "paste", paste))
        if not items:
            return "break"
        top = widget.winfo_toplevel()
        old = getattr(top, "_edit_menu", None)
        if old is not None:
            old.close()
        p = palette() if callable(palette) else palette
        top._edit_menu = PopupMenu(top, p, items, event.x_root, event.y_root)
        return "break"

    widget.bind("<Button-3>", open_menu)
    widget.bind("<Control-Button-1>", open_menu)


def tight_text_selection(widget, sel_bg, sel_fg):
    """Campo de texto (tk.Text): a seleção fica SÓ em cima das letras.
    O Tk pinta a quebra de linha selecionada até a borda do campo (parecia selecionar
    o vazio) e o Ctrl+A pegava a quebra de linha final, que ia junto na cópia.
    Aqui a seleção nativa fica invisível e uma marcação própria pinta só os caracteres;
    a seleção nunca passa do último caractere digitado."""
    bg, fg = widget.cget("bg"), widget.cget("fg")
    widget.configure(selectbackground=bg, inactiveselectbackground=bg, selectforeground=fg)
    widget.tag_configure("vsel", background=sel_bg, foreground=sel_fg)
    widget.tag_raise("vsel")
    state = {"job": None}

    def refresh():
        state["job"] = None
        try:
            ranges = widget.tag_ranges("sel")
            # não deixa a seleção incluir a quebra de linha final do widget
            if ranges and widget.compare(ranges[-1], ">", "end-1c"):
                widget.tag_remove("sel", "end-1c", "end")
                ranges = widget.tag_ranges("sel")
            widget.tag_remove("vsel", "1.0", "end")
            for i in range(0, len(ranges), 2):
                start, end = str(ranges[i]), str(ranges[i + 1])
                first = int(widget.index(start).split(".")[0])
                last = int(widget.index(end).split(".")[0])
                for ln in range(first, last + 1):
                    a = start if ln == first else f"{ln}.0"
                    b = end if ln == last else f"{ln}.end"      # sem a quebra de linha
                    if widget.compare(a, "<", b):
                        widget.tag_add("vsel", a, b)
        except tk.TclError:
            pass

    def schedule(_event=None):
        if state["job"] is None:
            try:
                state["job"] = widget.after_idle(refresh)
            except tk.TclError:
                pass

    def select_all(_event=None):
        widget.tag_remove("sel", "1.0", "end")
        widget.tag_add("sel", "1.0", "end-1c")
        widget.mark_set("insert", "end-1c")
        schedule()
        return "break"

    widget.bind("<<Selection>>", schedule, add="+")
    widget.bind("<B1-Motion>", schedule, add="+")
    widget.bind("<ButtonRelease-1>", schedule, add="+")
    widget.bind("<KeyRelease>", schedule, add="+")
    for seq in ("<Control-a>", "<Control-A>", "<<SelectAll>>"):
        widget.bind(seq, select_all)


_DIALOG_HOOKS = []      # mantém os callbacks vivos enquanto o Windows ainda pode chamá-los


def _install_dialog_frame_hook(hwnd):
    """Diálogo sem NENHUMA área de moldura nativa: a área do app ocupa a janela inteira.
    Sem isso, o Windows 10 desenha uma borda branca fina (estilo clássico) em volta do diálogo,
    e essa borda ainda 'comia' alguns pixels do conteúdo (cortava os botões de baixo)."""
    import ctypes
    from ctypes import wintypes
    if any(h[2] == hwnd for h in _DIALOG_HOOKS):
        return False
    user32 = ctypes.windll.user32
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    set_long = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
    set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    set_long.restype = ctypes.c_void_p
    call_proc = user32.CallWindowProcW
    call_proc.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    call_proc.restype = LRESULT
    WM_NCDESTROY, WM_NCCALCSIZE, WM_NCPAINT, WM_NCACTIVATE, GWLP_WNDPROC = 0x0082, 0x0083, 0x0085, 0x0086, -4
    old = {"ptr": None}
    entry = []

    def wnd_proc(h, msg, wparam, lparam):
        try:
            if msg == WM_NCCALCSIZE:
                return 0                       # área cliente = janela inteira (zero moldura)
            if msg == WM_NCPAINT:
                return 0                       # nada de moldura nativa desenhada
            if msg == WM_NCACTIVATE:
                return 1                       # ativa/desativa sem redesenhar moldura
            if msg == WM_NCDESTROY:
                res = call_proc(old["ptr"], h, msg, wparam, lparam)
                try:
                    _DIALOG_HOOKS.remove(entry[0])
                except (ValueError, IndexError):
                    pass
                return res
        except Exception:
            pass
        return call_proc(old["ptr"], h, msg, wparam, lparam)

    proc = WNDPROC(wnd_proc)
    old["ptr"] = set_long(hwnd, GWLP_WNDPROC, ctypes.cast(proc, ctypes.c_void_p))
    entry.append((proc, old, hwnd))
    _DIALOG_HOOKS.append(entry[0])
    return True


def strip_dialog_caption(win):
    """Remove barra nativa e TODA a moldura de um diálogo de tamanho fixo (a barra visível é a do app).
    Devolve True se precisou mudar algo (aí quem chamou aplica com SetWindowPos/FRAMECHANGED)."""
    changed = False
    try:
        user32 = _frame_api()
        hwnd = _hwnd_of(win)
        GWL_STYLE, GWL_EXSTYLE = -16, -20
        WS_CAPTION, WS_THICKFRAME, WS_MINBOX, WS_MAXBOX = 0x00C00000, 0x40000, 0x20000, 0x10000
        WS_BORDER, WS_DLGFRAME = 0x00800000, 0x00400000
        # bordas "3D"/de diálogo que o Windows desenha em branco no Windows 10
        EX_EDGES = 0x00000001 | 0x00000100 | 0x00000200 | 0x00020000   # DLGMODALFRAME|WINDOWEDGE|CLIENTEDGE|STATICEDGE
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        new = style & ~(WS_CAPTION | WS_BORDER | WS_DLGFRAME | WS_THICKFRAME | WS_MINBOX | WS_MAXBOX)
        if new != style:
            user32.SetWindowLongW(hwnd, GWL_STYLE, new)
            changed = True
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        new_ex = ex & ~EX_EDGES
        if new_ex != ex:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_ex)
            changed = True
        try:
            if _install_dialog_frame_hook(hwnd):
                changed = True
        except Exception as e:
            print(f"[{APP_NAME}] Falha ao remover a borda do diálogo: {e}", file=sys.stderr)
    except Exception as e:
        print(f"[{APP_NAME}] Falha ao remover a barra nativa do diálogo: {e}", file=sys.stderr)
    return changed


def _work_area_at(x, y, fallback):
    """Área útil (sem a barra de tarefas) do monitor que contém o ponto (x, y)."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

            user32 = ctypes.windll.user32
            user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
            user32.MonitorFromPoint.restype = wintypes.HANDLE
            mon = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2)   # MONITOR_DEFAULTTONEAREST
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if mon and user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
                r = mi.rcWork
                return r.left, r.top, r.right, r.bottom
        except Exception:
            pass
    return fallback


class BaseDialog(tk.Toplevel):
    """Diálogos do app.
    Anti-piscada: o diálogo nasce FORA da tela, recebe moldura, tamanho final e é totalmente
    desenhado lá; só então é movido para o centro. Mover uma janela pronta não exige redesenho.
    (Antes usava transparência 0 -> 1, mas no Windows voltar a opacidade total descarta a imagem
    da janela e ela aparece em branco/preto por um instante.)"""
    TITLEBAR_H = 34

    def __init__(self, parent, title, palette):
        super().__init__(parent)
        self.palette = palette
        self.result = None
        self._dlg_title = title
        self._size = None
        self._shown = False
        self._show_job = None
        self.geometry(f"+{OFFSCREEN}+{OFFSCREEN}")     # nasce fora da tela
        self.title(title)
        self.configure(bg=palette["bg"])
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.bind("<Escape>", lambda e: self.on_cancel())
        native_ok = apply_titlebar_theme(self, palette)
        # Windows 10 não aceita cor na barra nativa: o diálogo desenha a própria barra, na cor do painel
        self._custom = bool(CUSTOM_TITLEBAR and native_ok is False)
        if self._custom:
            self.configure(highlightthickness=1, highlightbackground=palette["border"],
                           highlightcolor=palette["border"])
            self._build_titlebar()
            self.bind("<Map>", self._on_map)
            self.after(10, self._apply_custom_frame)

    # ---------- barra própria ----------
    def _build_titlebar(self):
        p = self.palette
        bg = p["titlebar_bg"]
        bar = tk.Frame(self, bg=bg, height=self.TITLEBAR_H)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        drag = [bar]
        try:
            if os.path.exists(ICON_PNG):
                self._tb_icon = load_smooth_icon(ICON_PNG, 16)
                if self._tb_icon is not None:
                    lbl = tk.Label(bar, image=self._tb_icon, bg=bg, bd=0)
                    lbl.pack(side="left", padx=(10, 8))
                    drag.append(lbl)
        except Exception:
            pass
        title = tk.Label(bar, text=self._dlg_title, bg=bg, fg=p["text"], font=(FONT_FAMILY, 9))
        title.pack(side="left")
        drag.append(title)
        TitleButton(bar, "x", self.on_cancel, bg, "#E81123", p["text"], hover_fg="#FFFFFF").pack(side="right")
        self._tb_drag = None
        for w in drag:
            w.bind("<ButtonPress-1>", self._tb_press)
            w.bind("<B1-Motion>", self._tb_motion)
            w.bind("<ButtonRelease-1>", lambda e: setattr(self, "_tb_drag", None))

    def _tb_press(self, event):
        try:
            cx, cy = _win_cursor_pos()
            l, t, r, b = _win_rect(_hwnd_of(self))
            self._tb_drag = (cx, cy, l, t)
        except Exception:
            self._tb_drag = None

    def _tb_motion(self, event):
        if not self._tb_drag:
            return
        try:
            cx, cy = _win_cursor_pos()
            x0, y0, l, t = self._tb_drag
            _win_move(_hwnd_of(self), l + cx - x0, t + cy - y0)
        except Exception:
            pass

    def _apply_custom_frame(self, tries=0):
        """Tira a moldura nativa, ajusta o tamanho exato e só então mostra o diálogo."""
        try:
            self.update_idletasks()
            user32 = _frame_api()
            if not user32.GetParent(self.winfo_id()) and tries < 60:
                # a janela de moldura do Windows ainda não existe: tenta de novo em instantes
                self.after(15, lambda: self._apply_custom_frame(tries + 1))
                return
            changed = strip_dialog_caption(self)
            # só mexe na moldura/tamanho na primeira vez ou se o Windows recolocou a barra nativa;
            # refazer isso com a janela já visível era o que causava a segunda piscada
            if self._size is not None and (changed or not self._shown):
                import ctypes
                from ctypes import wintypes
                w, h, x, y = self._size
                if not self._shown:
                    x = y = OFFSCREEN                   # ainda está sendo montado fora da tela
                SWP = 0x0004 | 0x0010 | 0x0020               # NOZORDER | NOACTIVATE | FRAMECHANGED
                f = user32.SetWindowPos
                f.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT]
                f(wintypes.HWND(_hwnd_of(self)), None, x, y, w, h, SWP)
        except tk.TclError:
            return
        except Exception as e:
            print(f"[{APP_NAME}] Falha ao ajustar o diálogo: {e}", file=sys.stderr)
        self._schedule_show()

    def _schedule_show(self, delay=20):
        """Dá um instante para o Windows aplicar a moldura/tamanho antes de trazer o diálogo."""
        if self._shown or self._show_job is not None:
            return
        self._show_job = self.after(delay, self._show)

    def _show(self):
        """Traz o diálogo para a tela (uma única vez), já com moldura, conteúdo, tamanho e posição finais."""
        if self._shown:
            return
        self._show_job = None
        try:
            # processa redimensionamento e pintura de tudo ENQUANTO ainda está fora da tela
            self.update()
            # calcula o centro AGORA, com o tamanho real (moldura incluída) e a posição atual do app
            ow, oh = self._outer_size()
            x, y = self._centered_pos(ow, oh)
            if self._size is not None:
                self._size = (self._size[0], self._size[1], x, y)
            self._shown = True
            if sys.platform.startswith("win"):
                _win_move(_hwnd_of(self), x, y)        # só move: nada é redesenhado
            else:
                self.geometry(f"+{x}+{y}")
            self.lift()
            self.focus_force()
            if getattr(self, "_initial_focus", None) is not None:
                self._initial_focus.focus_set()
        except tk.TclError:
            pass
        except Exception as e:
            print(f"[{APP_NAME}] Falha ao mostrar o diálogo: {e}", file=sys.stderr)
            try:
                self.geometry(f"+{self._size[2]}+{self._size[3]}" if self._size else "+100+100")
            except Exception:
                pass

    def _on_map(self, event):
        if event.widget is self:
            # o Tk pode recolocar o estilo ao mostrar a janela: confere de novo
            self.after_idle(self._apply_custom_frame)

    def on_cancel(self):
        self.result = None
        self.destroy()

    def _anchor_rect(self):
        """Retângulo (x, y, w, h) da janela que abriu o diálogo (o corpo do app).
        Se ela não estiver visível (minimizada etc.), usa a tela."""
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        try:
            par = self.master.winfo_toplevel() if self.master is not None else None
            if par is not None and par.winfo_viewable() and par.state() not in ("iconic", "withdrawn"):
                x, y = par.winfo_rootx(), par.winfo_rooty()
                w, h = par.winfo_width(), par.winfo_height()
                if w > 1 and h > 1 and x > OFFSCREEN // 2 and y > OFFSCREEN // 2:
                    return x, y, w, h
        except tk.TclError:
            pass
        return 0, 0, sw, sh

    def _centered_pos(self, w, h):
        """Posição para o diálogo (w x h, tamanho externo) ficar no centro exato do app,
        sem sair do monitor onde o app está."""
        ax, ay, aw, ah = self._anchor_rect()
        x = ax + (aw - w) // 2
        y = ay + (ah - h) // 2
        cx, cy = ax + aw // 2, ay + ah // 2
        l, t, r, b = _work_area_at(cx, cy, (0, 0, self.winfo_screenwidth(), self.winfo_screenheight()))
        x = max(l, min(x, r - w))
        y = max(t, min(y, b - h))
        return x, y

    def _outer_size(self):
        """Tamanho real da janela do diálogo, contando a moldura do Windows."""
        if sys.platform.startswith("win"):
            try:
                l, t, r, b = _win_rect(_hwnd_of(self))
                if r - l > 1 and b - t > 1:
                    return r - l, b - t
            except Exception:
                pass
        if self._size is not None:
            return self._size[0], self._size[1]
        return self.winfo_width(), self.winfo_height()

    def center(self, w, h):
        self.update_idletasks()
        if getattr(self, "_custom", False):
            h += self.TITLEBAR_H                       # a barra própria faz parte da altura da janela
        x, y = self._centered_pos(w, h)
        self._size = (w, h, x, y)
        if self._shown:
            self.geometry(f"{w}x{h}+{x}+{y}")
            return
        self.geometry(f"{w}x{h}+{OFFSCREEN}+{OFFSCREEN}")   # tamanho final, ainda fora da tela
        if not getattr(self, "_custom", False):
            # barra nativa (Win 11 / outros sistemas): traz assim que terminar de desenhar
            self._schedule_show()
        self.after(700, self._show)                    # garantia: nunca fica fora da tela

    def center_to_content(self, w):
        """Centraliza com a altura que o conteúdo realmente precisa."""
        self.update_idletasks()
        h = self.winfo_reqheight() + 4                # folga: nada encosta/corta na borda de baixo
        if getattr(self, "_custom", False):
            h -= self.TITLEBAR_H                       # center() soma a barra de novo
        self.center(w, h)

# Cores dos blocos, em ordem no círculo cromático (cada uma a ~20°–55° da vizinha,
# todas com saturação/luminosidade parecidas para o texto branco ler bem em qualquer uma).
# Linha 1 = tons quentes, linha 2 = tons frios.
CATEGORY_COLORS = [
    "#DC2626",   # vermelho   (0°)
    "#EA580C",   # laranja    (21°)
    "#CA8A04",   # dourado    (45°)
    "#65A30D",   # lima       (85°)
    "#16A34A",   # verde      (142°)
    "#0891B2",   # ciano      (192°)
    "#2563EB",   # azul       (221°)
    "#7C3AED",   # violeta    (262°)
    "#C026D3",   # magenta    (292°)
    "#DB2777",   # rosa       (330°)
]

class CategoryDialog(BaseDialog):
    def __init__(self, parent, palette, name="", color=None):
        super().__init__(parent, "Categoria", palette)
        self.color = color or CATEGORY_COLORS[0]
        pad = {"padx": 20, "pady": 8}

        tk.Label(self, text="Nome da categoria", bg=palette["bg"], fg=palette["text"],
                 font=(FONT_FAMILY, 11, "bold")).pack(anchor="w", **pad)
        self.name_var = tk.StringVar(value=name)
        field = tk.Frame(self, bg=palette["field_bg"])        # moldura do campo: dá respiro ao texto
        field.pack(fill="x", padx=20)
        entry = tk.Entry(field, textvariable=self.name_var, font=(FONT_FAMILY, 11),
                         bg=palette["field_bg"], fg=palette["text"], relief="flat", bd=0,
                         highlightthickness=0, insertbackground=palette["text"])
        entry.pack(fill="x", padx=10, ipady=8)
        field.bind("<Button-1>", lambda e: entry.focus_set())
        self._initial_focus = entry
        attach_edit_menu(entry, palette)

        tk.Label(self, text="Cor do bloco", bg=palette["bg"], fg=palette["text"],
                 font=(FONT_FAMILY, 11, "bold")).pack(anchor="w", **pad)

        self._palette = palette
        self._swatches = []
        swatch_frame = tk.Frame(self, bg=palette["bg"])
        swatch_frame.pack(padx=20, pady=(0, 5))
        for i, c in enumerate(CATEGORY_COLORS):
            b = tk.Label(swatch_frame, bg=palette["bg"], bd=0, highlightthickness=0, cursor="hand2",
                         image=swatch_image(c))
            b.grid(row=i // 5, column=i % 5, padx=3, pady=3)
            b.bind("<Button-1>", lambda e, c=c: self.pick_color(c))
            self._swatches.append((c, b))
        self._redraw_swatches()

        btn_row = tk.Frame(self, bg=palette["bg"])
        btn_row.pack(pady=20)
        RoundButton(btn_row, "Cancelar", command=self.on_cancel,
                    bg=palette["border"], fg=palette["text"]).pack(side="left", padx=6)
        RoundButton(btn_row, "Salvar", command=self.on_save,
                    bg=palette["accent"], fg=palette["accent_text"]).pack(side="left", padx=6)

        self.center(360, 360)

    def _redraw_swatches(self):
        """Desenha as cores; a escolhida ganha um anel (borda) ao redor para ficar bem visível."""
        p = self._palette
        for c, lbl in self._swatches:
            selected = c.lower() == str(self.color).lower()
            lbl.configure(image=swatch_image(c, p["text"] if selected else None))

    def pick_color(self, c):
        self.color = c
        self._redraw_swatches()

    def on_save(self):
        name = self.name_var.get().strip()
        if not name:
            show_message(self, self.palette, "Aviso", "Digite um nome para a categoria.", kind="warning")
            return
        self.result = {"name": name, "color": self.color}
        self.destroy()

class ItemDialog(BaseDialog):
    def __init__(self, parent, palette, name="", content=""):
        super().__init__(parent, "Script", palette)
        pad = {"padx": 20, "pady": 6}

        tk.Label(self, text="Nome do script", bg=palette["bg"], fg=palette["text"],
                 font=(FONT_FAMILY, 11, "bold")).pack(anchor="w", **pad)
        self.name_var = tk.StringVar(value=name)
        field = tk.Frame(self, bg=palette["field_bg"])        # moldura do campo: dá respiro ao texto
        field.pack(fill="x", padx=20)
        entry = tk.Entry(field, textvariable=self.name_var, font=(FONT_FAMILY, 11),
                         bg=palette["field_bg"], fg=palette["text"], relief="flat", bd=0,
                         highlightthickness=0, insertbackground=palette["text"])
        entry.pack(fill="x", padx=10, ipady=8)
        field.bind("<Button-1>", lambda e: entry.focus_set())
        self._initial_focus = entry
        attach_edit_menu(entry, palette)

        tk.Label(self, text="Texto do script", bg=palette["bg"], fg=palette["text"],
                 font=(FONT_FAMILY, 11, "bold")).pack(anchor="w", **pad)

        text_frame = tk.Frame(self, bg=palette["field_bg"])
        text_frame.pack(fill="both", expand=True, padx=20)
        self.text_widget = tk.Text(text_frame, height=8, width=44, wrap="word",
                                   bg=palette["field_bg"], fg=palette["text"],
                                   font=(FONT_FAMILY, 10), relief="flat",
                                   insertbackground=palette["text"])
        self.text_widget.pack(fill="both", expand=True, padx=8, pady=8)
        self.text_widget.insert("1.0", content)
        tight_text_selection(self.text_widget, palette.get("select_bg", "#818CF8"),
                             palette.get("select_fg", "#0F172A"))
        attach_edit_menu(self.text_widget, palette)

        btn_row = tk.Frame(self, bg=palette["bg"])
        btn_row.pack(pady=16)
        RoundButton(btn_row, "Cancelar", command=self.on_cancel,
                    bg=palette["border"], fg=palette["text"]).pack(side="left", padx=6)
        RoundButton(btn_row, "Salvar", command=self.on_save,
                    bg=palette["accent"], fg=palette["accent_text"]).pack(side="left", padx=6)

        self.center(440, 420)

    def on_save(self):
        name = self.name_var.get().strip()
        content = self.text_widget.get("1.0", "end").rstrip("\n")
        if not name or not content.strip():
            show_message(self, self.palette, "Aviso", "Preencha o nome e o conteúdo do script.", kind="warning")
            return
        self.result = {"name": name, "content": content}
        self.destroy()

def _mix(c1, c2, t):
    """Mistura duas cores hex (t = quanto de c2)."""
    a, b = _rgb(c1), _rgb(c2)
    return "#%02x%02x%02x" % tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


class MessageDialog(BaseDialog):
    """Painel de confirmação/aviso no visual do app (substitui as caixas padrão do Windows).
    kind: "danger" (excluir), "warning", "info", "success" ou "error"."""

    KINDS = {
        "danger": ("alert", "danger"),
        "warning": ("alert", "highlight"),
        "info": ("info", "accent"),
        "success": ("check-circle", "success"),
        "error": ("x-circle", "danger"),
    }

    def __init__(self, parent, palette, title, heading, message="", kind="info",
                 confirm_text="OK", cancel_text=None, confirm_icon=None):
        super().__init__(parent, title, palette)
        p = palette
        icon_name, color_key = self.KINDS.get(kind, self.KINDS["info"])
        color = p[color_key]
        if kind == "warning":
            color = "#F59E0B"
        self.result = False

        body = tk.Frame(self, bg=p["bg"])
        body.pack(fill="both", expand=True, padx=24, pady=(22, 0))

        # ícone num círculo suave na cor do tipo de aviso
        badge = 52
        cv = tk.Canvas(body, width=badge, height=badge, bg=p["bg"], highlightthickness=0, bd=0)
        cv.pack(side="left", anchor="n")
        circle = swatch_image(_mix(p["bg"], color, 0.18), size=int(round(badge / 0.61)))
        cv.create_image(badge / 2, badge / 2, image=circle)
        cv.create_image(badge / 2, badge / 2, image=get_icon(icon_name, 26, color, stroke=2.2))
        self._imgs = (circle,)

        texts = tk.Frame(body, bg=p["bg"])
        texts.pack(side="left", fill="both", expand=True, padx=(16, 0))
        tk.Label(texts, text=heading, bg=p["bg"], fg=p["text"], font=(FONT_FAMILY, 12, "bold"),
                 justify="left", anchor="w", wraplength=300).pack(anchor="w", pady=(4, 0))
        if message:
            tk.Label(texts, text=message, bg=p["bg"], fg=p["text_dim"], font=(FONT_FAMILY, 10),
                     justify="left", anchor="w", wraplength=300).pack(anchor="w", pady=(6, 0))

        btn_row = tk.Frame(self, bg=p["bg"])
        btn_row.pack(padx=24, pady=22)                 # sem fill: o Tk centraliza os botões no painel
        if kind in ("danger", "error"):
            ok_bg, ok_fg = "#DC2626", "#FFFFFF"          # vermelho firme: texto branco legível nos dois temas
        else:
            ok_bg, ok_fg = p["accent"], p["accent_text"]
        if cancel_text:
            RoundButton(btn_row, cancel_text, command=self.on_cancel,
                        bg=p["border"], fg=p["text"]).pack(side="left", padx=6)
        RoundButton(btn_row, confirm_text, command=self.on_confirm, bg=ok_bg, fg=ok_fg,
                    icon=confirm_icon, icon_size=15).pack(side="left", padx=6)

        self.bind("<Return>", lambda e: self.on_confirm())
        self.center_to_content(420)

    def on_confirm(self):
        self.result = True
        self.destroy()

    def on_cancel(self):
        self.result = False
        self.destroy()


def _run_message(parent, palette, **kw):
    dlg = MessageDialog(parent, palette, **kw)
    parent.wait_window(dlg)
    # se o aviso saiu de dentro de outro diálogo, devolve o "modal" para ele
    if isinstance(parent, BaseDialog):
        try:
            parent.grab_set()
            parent.focus_force()
        except tk.TclError:
            pass
    return dlg.result


def ask_confirm(parent, palette, title, heading, message="", confirm_text="Excluir",
                cancel_text="Cancelar", kind="danger", confirm_icon="trash"):
    return _run_message(parent, palette, title=title, heading=heading, message=message, kind=kind,
                        confirm_text=confirm_text, cancel_text=cancel_text, confirm_icon=confirm_icon)


def show_message(parent, palette, title, heading, message="", kind="info"):
    _run_message(parent, palette, title=title, heading=heading, message=message, kind=kind)


class CopyScriptsApp(tk.Tk):
    def __init__(self):
        super().__init__()
        # a janela nasce 100% transparente: assim não dá pra ver a barra nativa antiga nem a troca de barras
        try:
            self.attributes("-alpha", 0.0)
        except Exception:
            pass
        self._loading = None
        self._revealed = False
        self._filter_sig = {}
        self._search_job = None
        _init_fonts(self)
        self.title(APP_DISPLAY_NAME)
        self._load_brand_assets()
        self.geometry("1100x720")
        self.minsize(760, 420)

        self.dark_mode = False
        self.zoom = 1.0
        self.data = self.load_data()
        self._update_state = {"phase": "off"}
        self._update_ui = None
        if updates_enabled():
            self._update_state = {"phase": "checking"}
            threading.Thread(target=self._update_worker, daemon=True).start()
            threading.Thread(target=cleanup_old_versions, daemon=True).start()
        self.dark_mode = self.data.get("settings", {}).get("dark_mode", False)
        self.zoom = self.data.get("settings", {}).get("zoom", 1.0)
        self.search_query = ""

        self.tooltip = Tooltip(self)
        self.contract_var = tk.StringVar()
        self.contract_var.trace_add("write", lambda *a: self._only_digits_contract())

        self._drag = None
        self._drag_indicator = None
        self.item_rows_by_cat = {}
        self.cat_rows = []
        self.item_row_widgets = {}
        self.cat_frames = {}
        self.empty_label = None

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        # Windows 11 aceita a cor na barra nativa; no Windows 10 o app desenha a própria barra.
        native_ok = apply_titlebar_theme(self, self.palette)
        self._custom_titlebar = bool(CUSTOM_TITLEBAR and native_ok is False)
        self._is_zoomed = False
        self.build_ui()
        self.apply_shortcuts()
        self.render()
        if self._custom_titlebar:
            strip_native_caption(self)
            self.after(100, lambda: strip_native_caption(self))   # o Tk pode recolocar o estilo ao mostrar a janela
            self.bind("<Map>", lambda e: self.after_idle(lambda: strip_native_caption(self)) if e.widget is self else None)
            self.bind("<Configure>", lambda e: (self._sync_max_icon(), strip_native_caption(self)) if e.widget is self else None)
            self.after(1000, self._keep_frameless)
        else:
            self.after(100, lambda: apply_titlebar_theme(self, self.palette))
        self.bind("<FocusIn>", self._on_focus_in, add="+")
        self._show_loading()
        self.after(250, self._reveal_window)
        if self._update_state["phase"] != "off":
            self.after(100, self._watch_update)
        self.after(2500, flush_mask_disk_cache)      # grava ícones novos no disco (próxima abertura é bem mais rápida)

    def _keep_frameless(self):
        """Garante, para sempre, que a moldura nativa (e a linha branca dela) não volte."""
        try:
            strip_native_caption(self)
            self.after(1000, self._keep_frameless)
        except Exception:
            pass

    # ---------- abertura: janela só aparece pronta + bolinha de carregamento ----------
    def _show_loading(self):
        """Cobre a área do app com uma bolinha girando até tudo estar de fato na tela."""
        try:
            p = self.palette
            off = 34 if getattr(self, "_custom_titlebar", False) else 0
            ov = tk.Frame(self, bg=p["bg"])
            ov.place(x=0, y=off, relwidth=1, relheight=1, height=-off)
            size = 56
            cv = tk.Canvas(ov, width=size, height=size, bg=p["bg"], highlightthickness=0, bd=0)
            cv.place(relx=0.5, rely=0.5, anchor="center")
            cv.create_oval(6, 6, size - 6, size - 6, outline=p["bg_alt"], width=5)
            arc = cv.create_arc(6, 6, size - 6, size - 6, start=90, extent=100,
                                style="arc", outline=p["accent"], width=5)
            ov.lift()
            self._loading = {"frame": ov, "canvas": cv, "arc": arc, "angle": 90, "t0": time.time()}
            self._spin_loading()
            self.after(60, self._poll_ready)
        except Exception as e:
            print(f"[{APP_NAME}] Falha ao criar o indicador de carregamento: {e}", file=sys.stderr)
            self._loading = None

    def _spin_loading(self):
        ld = self._loading
        if not ld:
            return
        try:
            ld["angle"] = (ld["angle"] - 26) % 360
            ld["canvas"].itemconfigure(ld["arc"], start=ld["angle"])
            self.after(30, self._spin_loading)
        except tk.TclError:
            self._loading = None

    def _reveal_window(self):
        """Mostra a janela só depois de a barra nativa ter sido removida."""
        if self._revealed:
            return
        try:
            if getattr(self, "_custom_titlebar", False):
                strip_native_caption(self)
            self.update_idletasks()
            self.attributes("-alpha", 1.0)
        except Exception:
            pass
        self._revealed = True

    def _poll_ready(self):
        """Mantém a bolinha na tela até o conteúdo estar montado, medido e visível."""
        ld = self._loading
        if not ld:
            return
        try:
            self.update_idletasks()
            ready = (
                self._revealed
                and self.winfo_ismapped()
                and self.canvas.winfo_width() > 1
                and self.content.winfo_height() > 1
                and self.canvas.winfo_ismapped()
                and time.time() - ld["t0"] >= 0.35          # evita um "piscar" se carregar rápido demais
                and (self._update_state["phase"] != "checking" or time.time() - ld["t0"] >= 3.0)
            )
            if ready:
                ld["frame"].destroy()
                self._loading = None
            else:
                self.after(60, self._poll_ready)
        except tk.TclError:
            self._loading = None

    # ---------- atualização automática ----------
    def _update_worker(self):
        """Roda numa thread: só mexe no dicionário de estado (a tela é atualizada por _watch_update)."""
        st = self._update_state
        try:
            info = fetch_update_info()
        except Exception as e:
            print(f"[{APP_NAME}] Não deu para verificar atualizações: {e}", file=sys.stderr)
            info = None
        if not info:
            st["phase"] = "none"
            return
        st.update(version=info["version"], got=0, total=int(info.get("size") or 0))
        st["phase"] = "downloading"
        try:
            path = download_update(info, lambda g, t: st.update(got=g, total=t))
        except Exception as e:
            print(f"[{APP_NAME}] Falha ao baixar a atualização: {e}", file=sys.stderr)
            st["phase"] = "failed"
            return
        st["path"] = path
        st["phase"] = "ready"

    def _watch_update(self):
        st = self._update_state
        phase = st.get("phase")
        if phase == "checking":
            self.after(100, self._watch_update)
            return
        if phase in ("none", "off"):
            return
        if phase == "failed":
            self._hide_update_screen()                 # sem internet/erro: segue com a versão atual
            return
        self._show_update_screen(st.get("version", ""))
        if phase == "downloading":
            self._set_update_progress(st.get("got", 0), st.get("total", 0))
            self.after(80, self._watch_update)
        elif phase == "ready":
            self._set_update_progress(1, 1, "Reiniciando…")
            self.after(250, self._finish_update)

    def _finish_update(self):
        try:
            exe = install_update(self._update_state["path"])
            try:
                self.save_data()
                flush_mask_disk_cache()
            except Exception:
                pass
            relaunch(exe)
        except Exception as e:
            print(f"[{APP_NAME}] Falha ao instalar a atualização: {e}", file=sys.stderr)
            try:
                os.remove(self._update_state.get("path", ""))
            except OSError:
                pass
            self._hide_update_screen()
            return
        os._exit(0)                                    # fecha esta versão; a nova já está abrindo

    def _show_update_screen(self, version):
        if self._update_ui is not None:
            return
        ld = self._loading
        if ld:
            try:
                ld["frame"].destroy()
            except tk.TclError:
                pass
            self._loading = None
        p = self.palette
        off = 34 if getattr(self, "_custom_titlebar", False) else 0
        ov = tk.Frame(self, bg=p["bg"])
        ov.place(x=0, y=off, relwidth=1, relheight=1, height=-off)
        box = tk.Frame(ov, bg=p["bg"])
        box.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(box, text="Atualizando o app", bg=p["bg"], fg=p["text"],
                 font=(FONT_FAMILY, 15, "bold")).pack()
        tk.Label(box, text=f"Instalando a versão {version}. Seus scripts continuam salvos.",
                 bg=p["bg"], fg=p["text_dim"], font=(FONT_FAMILY, 10)).pack(pady=(4, 16))
        bar_w, bar_h = 300, 8
        bar = tk.Canvas(box, width=bar_w, height=bar_h, bg=p["bg"], highlightthickness=0, bd=0)
        bar.pack()
        bar.create_rectangle(0, 0, bar_w, bar_h, fill=p["bg_alt"], outline="")
        fill = bar.create_rectangle(0, 0, 0, bar_h, fill=p["accent"], outline="")
        pct = tk.Label(box, text="Baixando…", bg=p["bg"], fg=p["text_dim"], font=(FONT_FAMILY, 9))
        pct.pack(pady=(8, 0))
        ov.lift()
        self._update_ui = {"frame": ov, "bar": bar, "fill": fill, "w": bar_w, "h": bar_h, "pct": pct}

    def _set_update_progress(self, got, total, text=None):
        ui = self._update_ui
        if not ui:
            return
        try:
            frac = min(1.0, got / total) if total else 0.0
            ui["bar"].coords(ui["fill"], 0, 0, ui["w"] * frac, ui["h"])
            if text is None:
                text = (f"Baixando… {int(frac * 100)}%  ({got / 1048576:.1f} de {total / 1048576:.1f} MB)"
                        if total else f"Baixando… {got / 1048576:.1f} MB")
            ui["pct"].configure(text=text)
            ui["frame"].lift()
        except tk.TclError:
            pass

    def _hide_update_screen(self):
        ui, self._update_ui = self._update_ui, None
        if ui:
            try:
                ui["frame"].destroy()
            except tk.TclError:
                pass

    def load_data(self):
        """Quem já usa o app: carrega os scripts salvos (data.json) normalmente.
        Primeiro acesso (sem data.json): o app começa vazio, sem nenhum script."""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                # arquivo danificado: guarda uma cópia antes que algo sobrescreva os scripts da pessoa
                print(f"[Mhnet CopyScripts] Falha ao ler data.json: {e}", file=sys.stderr)
                try:
                    shutil.copy2(DATA_FILE, DATA_FILE + f".corrompido-{int(time.time())}")
                except Exception:
                    pass
        return {"categories": [], "recent": [], "settings": {"dark_mode": False, "zoom": 1.0}}

    def save_data(self, data=None):
        data = data if data is not None else self.data
        data.setdefault("settings", {})
        data["settings"]["dark_mode"] = self.dark_mode
        data["settings"]["zoom"] = self.zoom
        tmp_path = DATA_FILE + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            shutil.move(tmp_path, DATA_FILE)
        except Exception as e:
            messagebox.showerror("Erro ao salvar", str(e))

    def find_category(self, cat_id):
        return next((c for c in self.data.get("categories", []) if c["id"] == cat_id), None)

    def find_item(self, cat_id, item_id):
        cat = self.find_category(cat_id)
        if not cat:
            return None
        return next((it for it in cat["items"] if it["id"] == item_id), None)

    @property
    def palette(self):
        return PALETTES["dark"] if self.dark_mode else PALETTES["light"]

    def fs(self, base):
        return max(8, int(round(base * self.zoom)))

    def _apply_windows_icon(self):
        """Pede ao Windows o tamanho exato de ícone para a escala da tela (evita ícone borrado)."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            try:
                scale = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0
            except Exception:
                scale = 1.0
            scale = max(1.0, min(scale, 4.0))
            small, big = int(round(16 * scale)), int(round(32 * scale))
            self.update_idletasks()
            hwnd = user32.GetParent(self.winfo_id()) or self.winfo_id()
            LR_LOADFROMFILE, IMAGE_ICON, WM_SETICON = 0x10, 1, 0x80
            user32.LoadImageW.restype = ctypes.c_void_p
            self._hicons = []
            for kind, size in ((0, small), (1, big)):        # 0 = ICON_SMALL, 1 = ICON_BIG
                h = user32.LoadImageW(None, ICON_ICO, IMAGE_ICON, size, size, LR_LOADFROMFILE)
                if h:
                    self._hicons.append(h)
                    user32.SendMessageW(hwnd, WM_SETICON, kind, ctypes.c_void_p(h))
        except Exception as e:
            print(f"[{APP_NAME}] Falha ao aplicar ícone do Windows: {e}", file=sys.stderr)

    def _load_brand_assets(self):
        """Ícone da janela (e de todos os diálogos) + logos usadas no cabeçalho."""
        self._icon_img = None
        self._logo_light = self._logo_dark = None
        try:
            if sys.platform.startswith("win") and os.path.exists(ICON_ICO):
                self.iconbitmap(default=ICON_ICO)
            elif os.path.exists(ICON_PNG):
                self._icon_img = tk.PhotoImage(file=ICON_PNG)
                self.iconphoto(True, self._icon_img)
        except Exception as e:
            print(f"[{APP_NAME}] Falha ao definir o ícone: {e}", file=sys.stderr)
        if sys.platform.startswith("win"):
            self.after(50, self._apply_windows_icon)
        for attr, path in (("_logo_light", LOGO_LIGHT), ("_logo_dark", LOGO_DARK)):
            try:
                setattr(self, attr, tk.PhotoImage(file=path))
            except Exception as e:
                print(f"[{APP_NAME}] Falha ao carregar {path}: {e}", file=sys.stderr)

    # ---------- barra de título própria (Windows 10) ----------
    def _build_titlebar(self):
        p = self.palette
        bg = p["titlebar_bg"]
        bar = tk.Frame(self, bg=bg, height=34)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        self.titlebar = bar
        drag_widgets = [bar]
        try:
            if os.path.exists(ICON_PNG):
                try:
                    import ctypes
                    scale = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0
                except Exception:
                    scale = 1.0
                size = int(round(18 * max(1.0, min(scale, 3.0))))
                self._titlebar_icon = load_smooth_icon(ICON_PNG, size)
                if self._titlebar_icon is None:                       # plano B: método antigo
                    img = tk.PhotoImage(file=ICON_PNG)
                    k = max(1, int(round(img.width() / 16)))
                    self._titlebar_icon = img.subsample(k) if k > 1 else img
                lbl = tk.Label(bar, image=self._titlebar_icon, bg=bg, bd=0)
                lbl.pack(side="left", padx=(10, 8))
                drag_widgets.append(lbl)
        except Exception:
            pass
        title = tk.Label(bar, text=APP_DISPLAY_NAME, bg=bg, fg=p["text"], font=(FONT_FAMILY, 9))
        title.pack(side="left")
        drag_widgets.append(title)

        TitleButton(bar, "x", self.on_close, bg, "#E81123", p["text"], hover_fg="#FFFFFF").pack(side="right")
        self._is_zoomed = self.state() == "zoomed"
        self.max_btn = TitleButton(bar, "restore" if self._is_zoomed else "maximize",
                                   self._toggle_maximize, bg, p["titlebar_hover"], p["text"])
        self.max_btn.pack(side="right")
        TitleButton(bar, "minus", self.iconify, bg, p["titlebar_hover"], p["text"]).pack(side="right")

        self._tb_drag = None
        for w in drag_widgets:
            w.bind("<ButtonPress-1>", self._titlebar_press)
            w.bind("<B1-Motion>", self._titlebar_motion)
            w.bind("<ButtonRelease-1>", self._titlebar_release)
            w.bind("<Double-Button-1>", lambda e: self._toggle_maximize())

    def _titlebar_press(self, event):
        try:
            cx, cy = _win_cursor_pos()
            l, t, r, b = _win_rect(_hwnd_of(self))
            self._tb_drag = {"cx": cx, "cy": cy, "x": l, "y": t, "w": r - l}
        except Exception:
            self._tb_drag = None

    def _titlebar_motion(self, event):
        d = self._tb_drag
        if not d:
            return
        try:
            hwnd = _hwnd_of(self)
            cx, cy = _win_cursor_pos()
            if self.state() == "zoomed":
                if abs(cx - d["cx"]) + abs(cy - d["cy"]) < 4:
                    return
                # arrastar a janela maximizada: restaura e mantém a janela embaixo do cursor
                ratio = (d["cx"] - d["x"]) / max(1, d["w"])
                self.state("normal")
                self.update_idletasks()
                self._sync_max_icon()
                l, t, r, b = _win_rect(hwnd)
                d["x"] = cx - int((r - l) * ratio)
                d["y"] = cy - 16
                d["cx"], d["cy"] = cx, cy
            _win_move(hwnd, d["x"] + cx - d["cx"], d["y"] + cy - d["cy"])
        except Exception as ex:
            print(f"[{APP_NAME}] Falha ao mover a janela: {ex}", file=sys.stderr)

    def _titlebar_release(self, event):
        self._tb_drag = None

    def _toggle_maximize(self):
        self.state("normal" if self.state() == "zoomed" else "zoomed")
        self.after(80, self._sync_max_icon)

    def _place_top_border(self):
        """O Windows desenha uma linha de 1px nas laterais e embaixo da janela, mas não em cima
        (lá a área do app vai até a borda). Esta é a mesma linha, desenhada pelo app, no topo."""
        if not getattr(self, "_custom_titlebar", False):
            return
        try:
            line = getattr(self, "_top_border", None)
            if line is None or not line.winfo_exists():
                line = tk.Frame(self, bg=windows_border_color(), height=1, bd=0, highlightthickness=0)
                self._top_border = line
            if self.state() == "zoomed":
                line.place_forget()                 # maximizada o Windows não desenha bordas
            else:
                line.place(x=0, y=0, relwidth=1, height=1)
                line.lift()
        except tk.TclError:
            pass

    def _sync_max_icon(self):
        self._place_top_border()
        try:
            zoomed = self.state() == "zoomed"
            if zoomed != self._is_zoomed:
                self._is_zoomed = zoomed
                self.max_btn.set_icon("restore" if zoomed else "maximize")
        except Exception:
            pass

    def build_ui(self):
        p = self.palette
        self.configure(bg=p["bg"])
        if getattr(self, "_custom_titlebar", False):
            self._build_titlebar()

        self.topbar = tk.Frame(self, bg=p["bg_alt"], height=60)
        self.topbar.pack(fill="x", side="top")

        inner_top = tk.Frame(self.topbar, bg=p["bg_alt"])
        inner_top.pack(fill="x", padx=20, pady=12)

        logo_img = self._logo_dark if self.dark_mode else self._logo_light
        if logo_img is not None:
            title_icon = tk.Label(inner_top, image=logo_img, bg=p["bg_alt"], bd=0)
            title_icon.pack(side="left", padx=(0, 10))
        title_lbl = tk.Label(inner_top, text=APP_DISPLAY_NAME, bg=p["bg_alt"], fg=p["brand"],
                             font=(FONT_FAMILY, 15, "bold"))
        title_lbl.pack(side="left")

        right_row = tk.Frame(inner_top, bg=p["bg_alt"])
        right_row.pack(side="right")

        search_frame = tk.Frame(inner_top, bg=p["input_bg"])
        search_frame.pack(side="left", padx=24, fill="y")
        self.search_frame = search_frame

        tk.Label(search_frame, image=get_icon("search", 16, p["text_dim"]),
                 bg=p["input_bg"], bd=0).pack(side="left", padx=(10, 4))
        self.search_var = tk.StringVar(value=self.search_query)
        self.search_entry = tk.Entry(search_frame, textvariable=self.search_var, relief="flat",
                                     bg=p["input_bg"], fg=p["text"], width=26,
                                     font=(FONT_FAMILY, 10), insertbackground=p["text"])
        self.search_entry.pack(side="left", ipady=5, padx=(0, 10))
        self.search_var.trace_add("write", lambda *a: self.on_search_typing())
        attach_edit_menu(self.search_entry, lambda: self.palette)

        RoundButton(right_row, "Categoria", command=self.add_category, icon="plus", icon_size=14, icon_stroke=2.6,
                    bg=p["brand"], fg=p["brand_text"], hover_bg=p["brand_hover"], height=32).pack(side="right", padx=(8, 0))

        RoundButton(right_row, "Importar", command=self.import_data, icon="download", icon_size=16,
                    bg=p["input_bg"], fg=p["text"], height=32).pack(side="right", padx=4)

        RoundButton(right_row, "Exportar", command=self.export_data, icon="upload", icon_size=16,
                    bg=p["input_bg"], fg=p["text"], height=32).pack(side="right", padx=4)

        _theme_icon = "moon" if not self.dark_mode else "sun"
        RoundButton(right_row, "", command=self.toggle_dark_mode, icon=_theme_icon, icon_size=18,
                    bg=p["input_bg"], fg=p["text"], width=36, height=32, padx=6).pack(side="right", padx=4)

        # --- linha de atalhos: contrato + AutoISP / Extrato / Dashboard / Financeiro ---
        links_row = tk.Frame(self.topbar, bg=p["bg_alt"])
        links_row.pack(fill="x", padx=20, pady=(0, 12))

        tk.Label(links_row, text="Contrato", bg=p["bg_alt"], fg=p["text_dim"],
                 font=(FONT_FAMILY, 10, "bold")).pack(side="left", padx=(0, 8))
        contract_frame = tk.Frame(links_row, bg=p["input_bg"])
        contract_frame.pack(side="left", padx=(0, 12))
        self.contract_entry = tk.Entry(contract_frame, textvariable=self.contract_var, relief="flat",
                                       bg=p["input_bg"], fg=p["text"], width=16,
                                       font=(FONT_FAMILY, 10), insertbackground=p["text"])
        self.contract_entry.pack(ipady=5, padx=10)
        attach_edit_menu(self.contract_entry, lambda: self.palette)
        for name, url_fn in CONTRACT_LINKS:
            btn = RoundButton(links_row, name, bg=p["input_bg"], fg=p["text"], height=32)
            btn.command = lambda n=name, f=url_fn, b=btn: self.open_with_contract(n, f, b)
            btn.pack(side="left", padx=(0, 8))
        self.clip_label = tk.Label(links_row, text=self._clipboard_preview(),
                                   bg=p["bg_alt"], fg=p["text_dim"], font=(FONT_FAMILY, 9))
        self.clip_label.pack(side="left", padx=(4, 0))
        if not getattr(self, "_clip_polling", False):   # um único "vigia" da área de transferência
            self._clip_polling = True
            self.after(600, self._poll_clipboard)

        self.status = tk.Label(self, text="", bg=p["bg_alt"], fg=p["text_dim"], font=(FONT_FAMILY, 9), anchor="w", padx=12, pady=4)
        self.status.pack(fill="x", side="bottom")

        content_outer = tk.Frame(self, bg=p["bg"])
        content_outer.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(content_outer, bg=p["bg"], highlightthickness=0, width=1, height=1)
        self.vscroll = RoundScrollbar(content_outer, command=self.canvas.yview,
                                      track_bg=p["bg"], track=p["scroll_track"],
                                      thumb=p["scroll_thumb"],
                                      thumb_hover=p["scroll_thumb_hover"])
        self.canvas.configure(yscrollcommand=self.vscroll.set)
        self.vscroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.content = tk.Frame(self.canvas, bg=p["bg"])
        self.content_window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")

        self.content.bind("<Configure>", lambda e: self._update_scrollregion())
        self.canvas.bind("<Configure>", lambda e: (self.canvas.itemconfig(self.content_window, width=e.width),
                                                   self._update_scrollregion()))
        self.bind_mousewheel(self.canvas)

        self._topbar_rows = (inner_top, links_row)
        self.after_idle(self._update_minsize)
        self._place_top_border()

    def _update_minsize(self):
        """Tamanho mínimo da janela = o que a barra superior precisa para mostrar tudo
        (a busca pode encolher um pouco; a prévia do texto copiado pode ser cortada)."""
        try:
            self.update_idletasks()
            inner_top, links_row = self._topbar_rows
            search_slack = max(0, self.search_frame.winfo_reqwidth() - 170)
            need_top = inner_top.winfo_reqwidth() - search_slack
            need_links = links_row.winfo_reqwidth() - self.clip_label.winfo_reqwidth()
            min_w = max(760, need_top, need_links) + 40 + 24      # margens + barra de rolagem
            min_h = 420
            self.minsize(min_w, min_h)
            if not getattr(self, "_opened_compact", False):
                # ao abrir: sempre na largura mais compacta, centralizado na tela
                self._opened_compact = True
                sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
                h = max(min_h, min(720, sh - 100))
                x = max(0, (sw - min_w) // 2)
                y = max(0, (sh - h) // 2 - 20)
                self.geometry(f"{min_w}x{h}+{x}+{y}")
                return
            if self.winfo_width() < min_w and self.state() != "zoomed":
                self.geometry(f"{min_w}x{max(self.winfo_height(), min_h)}")
        except (tk.TclError, AttributeError):
            pass

    def _update_scrollregion(self):
        """Área de rolagem começa sempre no topo (0) e nunca é menor que a área visível:
        se o conteúdo cabe na tela, não há o que rolar (antes dava pra 'empurrar' tudo pra baixo)."""
        try:
            self.content.update_idletasks()
            content_h = self.content.winfo_reqheight()
            view_h = self.canvas.winfo_height()
            view_w = self.canvas.winfo_width()
            self.canvas.configure(scrollregion=(0, 0, view_w, max(content_h, view_h)))
            if content_h <= view_h:
                self.canvas.yview_moveto(0)
        except (tk.TclError, AttributeError):
            pass

    def _on_mousewheel(self, event):
        try:
            first, last = self.canvas.yview()
            if first <= 0.0 and last >= 1.0:
                return                                   # tudo já está visível: não rola
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except tk.TclError:
            pass

    def bind_mousewheel(self, widget):
        widget.bind_all("<MouseWheel>", self._on_mousewheel)

    def apply_shortcuts(self):
        self.bind("<Control-n>", lambda e: self.add_category())
        self.bind("<Control-f>", lambda e: self.search_entry.focus_set())
        self.bind("<Control-k>", lambda e: self.contract_entry.focus_set())
        self.bind("<Control-d>", lambda e: self.toggle_dark_mode())

    def _only_digits_contract(self):
        value = self.contract_var.get()
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits != value:
            self.contract_var.set(digits)

    def _clipboard_preview(self):
        """Texto do rótulo 'Texto copiado: ...' (uma linha, truncado)."""
        try:
            text = self.clipboard_get()
        except Exception:
            text = ""
        text = " ".join(text.split())
        if not text:
            return "Texto copiado: (nada copiado)"
        if len(text) > CLIP_PREVIEW_MAX:
            text = text[:CLIP_PREVIEW_MAX] + "…"
        return f"Texto copiado: {text}"

    def _refresh_clip_label(self):
        label = getattr(self, "clip_label", None)
        if label is not None:
            try:
                new_text = self._clipboard_preview()
                if label.cget("text") != new_text:
                    label.config(text=new_text)
            except tk.TclError:
                pass

    def _on_focus_in(self, event):
        if event.widget is not self:
            return
        if getattr(self, "_custom_titlebar", False):
            strip_native_caption(self)
        self._refresh_clip_label()

    def _poll_clipboard(self):
        """Atualiza o rótulo sempre que o conteúdo copiado mudar."""
        self._refresh_clip_label()
        # janela em segundo plano/minimizada: vigia mais devagar (ao voltar, o FocusIn atualiza na hora)
        try:
            idle = self.state() == "iconic" or self.focus_displayof() is None
        except Exception:
            idle = False
        self.after(2000 if idle else 600, self._poll_clipboard)

    def _contract_from_clipboard(self):
        """Lê a área de transferência (sem mexer no campo) e devolve o contrato, se for um."""
        try:
            text = self.clipboard_get().strip()
        except Exception:
            return None
        if text.isascii() and text.isdigit() and CONTRATO_MIN_DIGITOS <= len(text) <= CONTRATO_MAX_DIGITOS:
            return text
        return None

    def open_with_contract(self, name, url_fn, button=None):
        # 1) número digitado no campo; 2) se o campo estiver vazio, o contrato copiado (Ctrl+C)
        contrato = self.contract_var.get().strip() or self._contract_from_clipboard()
        x, y = self.winfo_pointerx(), self.winfo_pointery()
        if not contrato:
            self.contract_entry.focus_set()
            self.tooltip.show("Digite o contrato ou copie o número dele.", x, y,
                              bg=self.palette["danger"], page_bg=self.palette["bg"], anchor=button)
            return
        webbrowser.open(url_fn(contrato))
        self.tooltip.show(f"Abrindo {name} ({contrato})...", x, y,
                          bg=self.palette["success"], page_bg=self.palette["bg"], anchor=button)

    def toggle_dark_mode(self):
        self.dark_mode = not self.dark_mode
        self.save_data()
        self.rebuild_ui()
        if not getattr(self, "_custom_titlebar", False):
            apply_titlebar_theme(self, self.palette)

    def rebuild_ui(self):
        try:
            scroll_pos = self.canvas.yview()[0]
        except Exception:
            scroll_pos = 0.0
        for w in self.winfo_children():
            w.destroy()
        self.build_ui()
        self.apply_shortcuts()
        self.render()
        self.after_idle(lambda: self._restore_scroll(scroll_pos))

    def _restore_scroll(self, pos):
        try:
            self.canvas.yview_moveto(pos)
        except Exception:
            pass

    def on_search_typing(self):
        # espera uma pausa curta na digitação, em vez de refazer o filtro a cada tecla
        job = getattr(self, "_search_job", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._search_job = self.after(120, self._run_search)

    def _run_search(self):
        self._search_job = None
        self.search_query = self.search_var.get().strip().lower()
        self._apply_search_filter()

    def on_close(self):
        self.save_data()
        flush_mask_disk_cache()
        self.destroy()

    def export_data(self):
        filename = filedialog.asksaveasfilename(
            title="Exportar Dados do App",
            defaultextension=".json",
            filetypes=[("Arquivo JSON", "*.json")],
            initialfile=f"Mhnet_CopyScripts_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        if filename:
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
                show_message(self, self.palette, "Exportar", "Dados exportados com sucesso!",
                             os.path.basename(filename), kind="success")
            except Exception as e:
                show_message(self, self.palette, "Exportar", "Não foi possível exportar os dados.",
                             str(e), kind="error")

    def import_data(self):
        filename = filedialog.askopenfilename(
            title="Importar Dados para o App",
            filetypes=[("Arquivo JSON", "*.json")]
        )
        if filename:
            if ask_confirm(self, self.palette, "Importar", "Substituir os dados atuais?",
                           "A importação vai substituir todas as categorias e scripts atuais pelos do arquivo.",
                           confirm_text="Importar", kind="warning", confirm_icon="download"):
                try:
                    with open(filename, "r", encoding="utf-8") as f:
                        imported = json.load(f)
                    if isinstance(imported, dict) and "categories" in imported:
                        self.data = imported
                        self.save_data()
                        self.rebuild_ui()
                        show_message(self, self.palette, "Importar", "Dados importados com sucesso!",
                                     kind="success")
                    else:
                        show_message(self, self.palette, "Importar", "Arquivo inválido.",
                                     "Esse arquivo não é um backup do Mhnet CopyScripts.", kind="error")
                except Exception as e:
                    show_message(self, self.palette, "Importar", "Não foi possível ler o arquivo.",
                                 str(e), kind="error")

    def render(self, preserve_scroll=True):
        p = self.palette

        scroll_pos = None
        if preserve_scroll:
            try:
                scroll_pos = self.canvas.yview()[0]
            except Exception:
                scroll_pos = None

        self._cancel_drag()
        self._filter_sig = {}

        old_content = self.content
        self.content = tk.Frame(self.canvas, bg=p["bg"])
        self.item_rows_by_cat = {}
        self.cat_rows = []
        self.item_row_widgets = {}
        self.cat_frames = {}
        self.empty_label = None

        cats = self.data.get("categories", [])

        cat_header_row = tk.Frame(self.content, bg=p["bg"])
        cat_header_row.pack(anchor="w", padx=20, pady=(16, 8))
        cat_header_icon = tk.Label(cat_header_row, image=get_icon("folder", int(self.fs(13) * 1.5), p["text"]),
                                   bg=p["bg"], bd=0)
        cat_header_icon.pack(side="left")
        cat_header = tk.Label(cat_header_row, text=" Suas Categorias", bg=p["bg"], fg=p["text"],
                              font=(FONT_FAMILY, self.fs(13), "bold"))
        cat_header.pack(side="left")

        for cat in cats:
            frame = self.render_category(cat, p)
            frame.pack(fill="x", padx=20, pady=8)
            self.cat_rows.append((cat["id"], frame))

        self.canvas.itemconfig(self.content_window, window=self.content)
        self.content.bind("<Configure>", lambda e: self._update_scrollregion())
        if old_content is not None:
            old_content.destroy()

        self._update_status()
        self._apply_search_filter()

        if scroll_pos is not None:
            self.after_idle(lambda: self._restore_scroll(scroll_pos))

    def _apply_search_filter(self):
        p = self.palette
        query = self.search_query
        cats = self.data.get("categories", [])
        frames_by_id = dict(self.cat_rows)
        any_visible = False
        sigs_now = {}
        frame_vis = []

        for cat in cats:
            cat_id = cat["id"]
            frame = frames_by_id.get(cat_id)
            if frame is None:
                continue
            rows_by_id = dict(self.item_rows_by_cat.get(cat_id, []))

            if not query:
                visible_ids = {it["id"] for it in cat["items"]}
                cat_visible = True
            else:
                matched_ids = {it["id"] for it in cat["items"]
                                if query in it["name"].lower() or query in it["content"].lower()}
                if matched_ids:
                    visible_ids = matched_ids
                    cat_visible = True
                elif query in cat["name"].lower():
                    visible_ids = {it["id"] for it in cat["items"]}
                    cat_visible = True
                else:
                    visible_ids = set()
                    cat_visible = False

            sig = (query, cat_visible, tuple(it["id"] in visible_ids for it in cat["items"]))
            sigs_now[cat_id] = sig
            if self._filter_sig.get(cat_id) == sig:
                if cat_visible:
                    any_visible = True
                frame_vis.append((cat_id, cat_visible))
                continue                      # nada mudou nesta categoria: não mexe nos widgets

            for it in cat["items"]:
                item_id = it["id"]
                row = rows_by_id.get(item_id)
                if row is None:
                    continue
                is_visible = item_id in visible_ids

                widget_info = self.item_row_widgets.get(item_id)
                if widget_info:
                    widget_info["name_lbl"].set_text(
                        it["name"], query=query if is_visible else "",
                        highlight_bg=p["highlight"], highlight_fg=p["highlight_fg"]
                    )
                    widget_info["prev_lbl"].set_text(
                        self._preview_text(it["content"]), query=query if is_visible else "",
                        highlight_bg=p["highlight"], highlight_fg=p["highlight_fg"]
                    )

                try:
                    row.pack_forget()
                    if is_visible:
                        row.pack(fill="x", pady=3)
                except tk.TclError:
                    continue

            cat_info = self.cat_frames.get(cat_id)
            if cat_info and "name_lbl" in cat_info:
                if isinstance(cat_info["name_lbl"], HighlightLabel):
                    cat_info["name_lbl"].set_text(
                        cat["name"], query=query if cat_visible else "",
                        highlight_bg=p["highlight"], highlight_fg=p["highlight_fg"]
                    )

            if cat_visible:
                any_visible = True

            frame_vis.append((cat_id, cat_visible))

        fv = tuple(frame_vis)
        if self._filter_sig.get("__frames__") != fv:
            for cid, _vis in frame_vis:
                try:
                    frames_by_id[cid].pack_forget()
                except tk.TclError:
                    pass
            for cid, vis in frame_vis:
                if vis:
                    try:
                        frames_by_id[cid].pack(fill="x", padx=20, pady=8)
                    except tk.TclError:
                        pass
        sigs_now["__frames__"] = fv
        self._filter_sig = sigs_now
        empty_text = "Nenhum script encontrado." if query else "Nenhuma categoria cadastrada."
        if not any_visible:
            if self.empty_label is None:
                self.empty_label = tk.Label(self.content, text=empty_text, bg=p["bg"],
                                             fg=p["text_dim"], font=(FONT_FAMILY, self.fs(11)))
                self.empty_label.pack(pady=40)
            else:
                try:
                    self.empty_label.configure(text=empty_text)
                except tk.TclError:
                    self.empty_label = None
        elif self.empty_label is not None:
            try:
                self.empty_label.destroy()
            except tk.TclError:
                pass
            self.empty_label = None

        self.content.update_idletasks()
        self._update_scrollregion()

    def _update_status(self):
        cats = self.data.get("categories", [])
        n_cat = len(cats)
        n_items = sum(len(c["items"]) for c in cats)
        self.status.config(text=f"{n_cat} categorias • {n_items} scripts cadastrados")

    def render_category(self, cat, p):
        cat_id = cat["id"]
        outer = tk.Frame(self.content, bg=p["card_bg"], highlightbackground=p["border"], highlightthickness=1)

        header = tk.Frame(outer, bg=cat["color"])
        header.pack(fill="x")

        # SETAS PARA SUBIR E DESCER A CATEGORIA (Substituindo o Drag and Drop)
        move_frame = tk.Frame(header, bg=cat["color"])
        move_frame.pack(side="left", padx=(6, 2), pady=4)

        btn_up = RoundButton(move_frame, "", command=lambda: self.move_category(cat_id, -1),
                             bg=cat["color"], fg="white", width=24, height=22, parent_bg=cat["color"],
                             icon="chevron-up", icon_size=14, icon_stroke=2.6, padx=2)
        btn_up.pack(side="left", padx=1)

        btn_down = RoundButton(move_frame, "", command=lambda: self.move_category(cat_id, 1),
                               bg=cat["color"], fg="white", width=24, height=22, parent_bg=cat["color"],
                               icon="chevron-down", icon_size=14, icon_stroke=2.6, padx=2)
        btn_down.pack(side="left", padx=1)

        btns = tk.Frame(header, bg=cat["color"])
        btns.pack(side="right", padx=8)

        name_lbl = HighlightLabel(header, text=cat["name"], bg=cat["color"], fg="white",
                                   font=(FONT_FAMILY, self.fs(12), "bold"), cursor="")
        name_lbl.pack(side="left", pady=8, padx=(4, 0))
        name_lbl.set_text(cat["name"])

        btn_delete = RoundButton(btns, "", command=lambda: self.delete_category(cat_id),
                    bg=cat["color"], fg="white", width=28, height=26, parent_bg=cat["color"],
                    icon="trash", icon_size=16, padx=4)
        btn_delete.pack(side="right", padx=2)
        btn_edit = RoundButton(btns, "", command=lambda: self.edit_category(cat_id),
                    bg=cat["color"], fg="white", width=28, height=26, parent_bg=cat["color"],
                    icon="pencil", icon_size=16, padx=4)
        btn_edit.pack(side="right", padx=2)
        btn_add = RoundButton(btns, "script", command=lambda: self.add_item(cat_id),
                    bg=cat["color"], fg="white", height=26, parent_bg=cat["color"],
                    icon="plus", icon_size=13, icon_stroke=2.6)
        btn_add.pack(side="right", padx=2)

        body = tk.Frame(outer, bg=p["card_bg"])
        body.pack(fill="x", padx=10, pady=8)

        self.cat_frames[cat_id] = {
            "outer": outer, "header": header, "name_lbl": name_lbl,
            "btns_frame": btns, "body": body, "move_frame": move_frame,
            "buttons": [btn_delete, btn_edit, btn_add, btn_up, btn_down],
        }

        row_list = []
        self.item_rows_by_cat[cat_id] = row_list
        for item in cat["items"]:
            row = self.render_item_row(body, cat_id, item, p)
            row_list.append((item["id"], row))

        return outer

    def move_category(self, cat_id, direction):
        if self.search_query:
            return  # Não altera ordens enquanto filtra
        cats = self.data.get("categories", [])
        idx = next((i for i, c in enumerate(cats) if c["id"] == cat_id), None)
        if idx is None:
            return
        new_idx = idx + direction
        if 0 <= new_idx < len(cats):
            cats[idx], cats[new_idx] = cats[new_idx], cats[idx]
            self.save_data()
            self._repack_categories()

    def render_item_row(self, parent, cat_id, item, p):
        row = tk.Frame(parent, bg=p["input_bg"], highlightthickness=1, highlightbackground=p["input_bg"])
        row.pack(fill="x", pady=3)

        handle = tk.Label(row, image=get_icon("grip", self.fs(16), p["text_dim"]),
                          bg=p["input_bg"], bd=0, cursor="fleur", padx=4)
        handle.pack(side="left", padx=(6, 0))
        
        # MANIPULADOR DE ARRASTE DOS SCRIPTS
        handle.bind("<ButtonPress-1>", lambda e, cid=cat_id, iid=item["id"]: self.start_item_drag(cid, iid, e))

        main = tk.Frame(row, bg=p["input_bg"], cursor="hand2")
        main.pack(side="left", fill="both", expand=True)

        name_lbl = HighlightLabel(main, text=item["name"], bg=p["input_bg"], fg=p["text"],
                                  font=(FONT_FAMILY, self.fs(10), "bold"), height=1)
        name_lbl.pack(fill="x", padx=10, pady=(6, 1))

        prev_lbl = HighlightLabel(main, text=self._preview_text(item["content"]), bg=p["input_bg"],
                                  fg=p["text_dim"], font=(FONT_FAMILY, self.fs(9)), height=1)
        prev_lbl.pack(fill="x", padx=10, pady=(0, 6))

        item_id = item["id"]

        click_cmd = lambda e, cid=cat_id, iid=item_id: self.copy_item(cid, iid, e)
        menu_cmd = lambda e, cid=cat_id, iid=item_id: self._show_item_menu(cid, iid, e)

        row.bind("<Button-1>", click_cmd)
        row.bind("<Button-3>", menu_cmd)
        row.bind("<Control-Button-1>", menu_cmd)

        main.bind("<Button-1>", click_cmd)
        main.bind("<Button-3>", menu_cmd)
        main.bind("<Control-Button-1>", menu_cmd)

        name_lbl.bind_events(click_cmd, menu_cmd)
        prev_lbl.bind_events(click_cmd, menu_cmd)

        self.item_row_widgets[item_id] = {"row": row, "name_lbl": name_lbl, "prev_lbl": prev_lbl, "normal": p["input_bg"]}
        return row

    def _show_item_menu(self, cat_id, item_id, event):
        old = getattr(self, "_item_menu", None)
        if old is not None:
            old.close()
        self._item_menu = PopupMenu(
            self, self.palette,
            [("Editar", "pencil", lambda: self.edit_item(cat_id, item_id)),
             ("Excluir", "trash", lambda: self.delete_item(cat_id, item_id))],
            event.x_root, event.y_root)

    @staticmethod
    def _preview_text(content):
        preview = content.replace("\n", " ").strip()
        if len(preview) > 120:
            preview = preview[:120] + "..."
        return preview

    def copy_item(self, cat_id, item_id, event=None):
        item = self.find_item(cat_id, item_id)
        if item is None:
            return
        self.clipboard_clear()
        self.clipboard_append(item["content"])
        self.update_idletasks()

        x = event.x_root + 10 if event else self.winfo_pointerx()
        y = event.y_root + 10 if event else self.winfo_pointery()
        self.tooltip.show("Copiado!", x, y, bg=self.palette["success"], page_bg=self.palette["bg"])
        self._flash_item(item_id)

    def _flash_item(self, item_id):
        info = getattr(self, "item_row_widgets", {}).get(item_id)
        if not info:
            return
        row = info["row"]

        def _restore():
            try:
                row.configure(highlightbackground=info["normal"])
            except tk.TclError:
                pass

        try:
            row.configure(highlightbackground=self.palette["success"])
            self.after(300, _restore)
        except tk.TclError:
            pass

    def add_category(self):
        dlg = CategoryDialog(self, self.palette)
        self.wait_window(dlg)
        if not dlg.result:
            return
        new_cat = {"id": str(uuid.uuid4()), "name": dlg.result["name"],
                   "color": dlg.result["color"], "items": []}
        self.data.setdefault("categories", []).append(new_cat)
        self.save_data()
        p = self.palette
        frame = self.render_category(new_cat, p)
        frame.pack(fill="x", padx=20, pady=8)
        self.cat_rows.append((new_cat["id"], frame))
        self._update_status()
        self._apply_search_filter()

    def edit_category(self, cat_id):
        cat = self.find_category(cat_id)
        if not cat:
            return
        dlg = CategoryDialog(self, self.palette, name=cat["name"], color=cat["color"])
        self.wait_window(dlg)
        if not dlg.result:
            return
        cat["name"] = dlg.result["name"]
        cat["color"] = dlg.result["color"]
        self.save_data()
        info = self.cat_frames.get(cat_id)
        if info:
            new_color = cat["color"]
            try:
                info["header"].configure(bg=new_color)
                info["name_lbl"].set_colors(bg=new_color)
                info["name_lbl"].set_text(cat["name"])
                info["btns_frame"].configure(bg=new_color)
                if info.get("move_frame") is not None:
                    info["move_frame"].configure(bg=new_color)
                for btn in info["buttons"]:
                    btn.set_bg(new_color, canvas_bg=new_color)
            except tk.TclError:
                pass
        self._apply_search_filter()

    def delete_category(self, cat_id):
        cat = self.find_category(cat_id)
        if not cat:
            return
        n = len(cat.get("items", []))
        detail = (f"Os {n} scripts dentro dela também serão excluídos. " if n > 1 else
                  "O script dentro dela também será excluído. " if n == 1 else "")
        if not ask_confirm(self, self.palette, "Excluir categoria",
                           f"Excluir a categoria \u201c{cat['name']}\u201d?",
                           detail + "Essa ação não pode ser desfeita."):
            return
        self.data["categories"] = [c for c in self.data.get("categories", []) if c["id"] != cat_id]
        self.save_data()
        info = self.cat_frames.pop(cat_id, None)
        if info:
            try:
                info["outer"].destroy()
            except tk.TclError:
                pass
        self.cat_rows = [(cid, f) for cid, f in self.cat_rows if cid != cat_id]
        for item_id, _row in self.item_rows_by_cat.pop(cat_id, []):
            self.item_row_widgets.pop(item_id, None)
        self._update_status()
        self._apply_search_filter()

    def add_item(self, cat_id):
        cat = self.find_category(cat_id)
        if not cat:
            return
        dlg = ItemDialog(self, self.palette)
        self.wait_window(dlg)
        if not dlg.result:
            return
        new_item = {"id": str(uuid.uuid4()), "name": dlg.result["name"], "content": dlg.result["content"]}
        cat["items"].append(new_item)
        self.save_data()
        info = self.cat_frames.get(cat_id)
        if info:
            p = self.palette
            row = self.render_item_row(info["body"], cat_id, new_item, p)
            self.item_rows_by_cat.setdefault(cat_id, []).append((new_item["id"], row))
        self._update_status()
        self._apply_search_filter()

    def edit_item(self, cat_id, item_id):
        item = self.find_item(cat_id, item_id)
        if not item:
            return
        dlg = ItemDialog(self, self.palette, name=item["name"], content=item["content"])
        self.wait_window(dlg)
        if not dlg.result:
            return
        item["name"] = dlg.result["name"]
        item["content"] = dlg.result["content"]
        self.save_data()
        info = self.item_row_widgets.get(item_id)
        if info:
            try:
                info["name_lbl"].set_text(item["name"])
                info["prev_lbl"].set_text(self._preview_text(item["content"]))
            except tk.TclError:
                pass
        self._apply_search_filter()

    def delete_item(self, cat_id, item_id):
        cat = self.find_category(cat_id)
        if not cat:
            return
        item = self.find_item(cat_id, item_id)
        name = item["name"] if item else "este script"
        if not ask_confirm(self, self.palette, "Excluir script",
                           f"Excluir o script \u201c{name}\u201d?",
                           "Essa ação não pode ser desfeita."):
            return
        cat["items"] = [it for it in cat["items"] if it["id"] != item_id]
        self.save_data()
        info = self.item_row_widgets.pop(item_id, None)
        if info:
            try:
                info["row"].destroy()
            except tk.TclError:
                pass
        rows = self.item_rows_by_cat.get(cat_id)
        if rows is not None:
            self.item_rows_by_cat[cat_id] = [(iid, row) for iid, row in rows if iid != item_id]
        self._update_status()
        self._apply_search_filter()

    # --- DRAG AND DROP APENAS PARA OS SCRIPTS ---
    def start_item_drag(self, cat_id, item_id, event):
        if self.search_query:
            return
        self._cancel_drag()
        self._drag = {"kind": "item", "cat_id": cat_id, "item_id": item_id, "target_index": None}
        self.config(cursor="fleur")
        info = getattr(self, "item_row_widgets", {}).get(item_id)
        if info:
            try:
                info["row"].configure(highlightbackground=self.palette["accent"], highlightthickness=2)
            except tk.TclError:
                pass
        self._drag_indicator = tk.Frame(self.content, bg=self.palette["accent"], height=3)
        self.bind_all("<B1-Motion>", self._on_item_drag_motion)
        self.bind_all("<ButtonRelease-1>", self._on_item_drag_release)

    def _on_item_drag_motion(self, event):
        if not self._drag or self._drag["kind"] != "item":
            return
        cat_id = self._drag["cat_id"]
        rows = self.item_rows_by_cat.get(cat_id, [])
        target_index = len(rows)
        for i, (iid, row) in enumerate(rows):
            try:
                ry = row.winfo_rooty()
                rh = row.winfo_height()
            except tk.TclError:
                continue
            if event.y_root < ry + rh / 2:
                target_index = i
                break
        self._drag["target_index"] = target_index
        self._show_drag_indicator(rows, target_index)

    def _show_drag_indicator(self, rows, target_index):
        if self._drag_indicator is None:
            return
        ind = self._drag_indicator
        if not rows:
            ind.place_forget()
            return
        try:
            if target_index >= len(rows):
                ref = rows[-1][1]
                ind.place(in_=ref.master, relx=0, x=0, y=ref.winfo_y() + ref.winfo_height() + 1, relwidth=1, height=3)
            else:
                ref = rows[target_index][1]
                ind.place(in_=ref.master, relx=0, x=0, y=ref.winfo_y() - 2, relwidth=1, height=3)
            ind.lift()
        except tk.TclError:
            pass

    def _on_item_drag_release(self, event):
        self.unbind_all("<B1-Motion>")
        self.unbind_all("<ButtonRelease-1>")
        self.config(cursor="")
        drag = self._drag
        self._drag = None
        if self._drag_indicator is not None:
            try:
                self._drag_indicator.destroy()
            except tk.TclError:
                pass
            self._drag_indicator = None
        if not drag or drag["kind"] != "item":
            return
        info = getattr(self, "item_row_widgets", {}).get(drag["item_id"])
        if info:
            try:
                info["row"].configure(highlightthickness=1, highlightbackground=info["normal"])
            except tk.TclError:
                pass
        self._reorder_item(drag["cat_id"], drag["item_id"], drag.get("target_index"))

    def _reorder_item(self, cat_id, item_id, target_index):
        if target_index is None:
            return
        cat = self.find_category(cat_id)
        if not cat:
            return
        items = cat["items"]
        old_index = next((i for i, it in enumerate(items) if it["id"] == item_id), None)
        if old_index is None:
            return
        it = items.pop(old_index)
        if old_index < target_index:
            target_index -= 1
        target_index = max(0, min(target_index, len(items)))
        items.insert(target_index, it)
        self.save_data()
        self._repack_items(cat_id)

    def _repack_items(self, cat_id):
        self._filter_sig = {}
        cat = self.find_category(cat_id)
        rows_by_id = dict(self.item_rows_by_cat.get(cat_id, []))
        if not cat or not rows_by_id:
            return
        new_order = []
        for it in cat["items"]:
            row = rows_by_id.get(it["id"])
            if row is None:
                continue
            try:
                row.pack_forget()
                row.pack(fill="x", pady=3)
            except tk.TclError:
                continue
            new_order.append((it["id"], row))
        self.item_rows_by_cat[cat_id] = new_order

    def _repack_categories(self):
        self._filter_sig = {}
        frames_by_id = dict(self.cat_rows)
        new_order = []
        for cat in self.data.get("categories", []):
            frame = frames_by_id.get(cat["id"])
            if frame is None:
                continue
            try:
                frame.pack_forget()
                frame.pack(fill="x", padx=20, pady=8)
            except tk.TclError:
                continue
            new_order.append((cat["id"], frame))
        self.cat_rows = new_order

    def _cancel_drag(self):
        if self._drag is not None:
            self.unbind_all("<B1-Motion>")
            self.unbind_all("<ButtonRelease-1>")
            self.config(cursor="")
            self._drag = None
        if self._drag_indicator is not None:
            try:
                self._drag_indicator.destroy()
            except tk.TclError:
                pass
            self._drag_indicator = None

if __name__ == "__main__":
    app = CopyScriptsApp()
    app.mainloop()