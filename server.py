from __future__ import annotations

import asyncio
import html
import io
import json
import logging
import os
import random
import re
import socket
import time
import urllib.request as _urllib
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite
import qrcode
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("beyhekim")

BASE_DIR = Path(__file__).parent
DB_PATH = Path(os.environ.get("DB_DIR", str(BASE_DIR))) / "leaderboard.db"
PORT    = int(os.environ.get("PORT", 8000))

# ── Güvenlik Sabitleri ────────────────────────────────────────────────────────
ROOM_ID_PATTERN = re.compile(r"^[A-Z0-9_-]{3,12}$")
VALID_BUTTON_PATTERN = re.compile(r"^[a-z0-9_]{1,32}$")
MAX_ACTIVE_ROOMS = 250
MAX_MSG_RATE_PER_SEC = 25  # Bir WebSocket'ten saniyede izin verilen maks mesaj
SCORE_POST_LIMIT_PER_MIN = 15

# IP bazlı rate-limiter
score_rate_tracker: dict[str, list[float]] = defaultdict(list)


# ── Simya Elementleri ve Tarihi Veriler ──────────────────────────────────────

def _load_elements():
    json_path = BASE_DIR / "razi_elements.json"
    if json_path.exists():
        try:
            items = json.loads(json_path.read_text(encoding="utf-8"))
            mats = tuple(it["id"] for it in items)
            names = {it["id"]: it["name"] for it in items}
            symbols = {it["id"]: it["symbol"] for it in items}
            notes = {it["id"]: it.get("fact", "") for it in items}
            colors = {it["id"]: tuple(it["color"]) for it in items}
            colors_lt = {it["id"]: tuple(it.get("color_lt", [min(255, c + 45) for c in it["color"]])) for it in items}
            return mats, names, symbols, notes, colors, colors_lt
        except Exception as e:
            log.warning("razi_elements.json yüklenemedi: %s", e)
    mats = ("civa", "kukurt", "antimon", "tuz", "demir", "bakir", "fosfor", "arsenik")
    names = {m: m.capitalize() for m in mats}
    symbols = {m: "*" for m in mats}
    notes = {m: "" for m in mats}
    colors = {m: (150, 150, 150) for m in mats}
    colors_lt = {m: (200, 200, 200) for m in mats}
    return mats, names, symbols, notes, colors, colors_lt


MATERIALS, MATERIAL_NAMES, MATERIAL_SYMBOLS, MATERIAL_NOTES, COLORS, COLORS_LT = _load_elements()

HISTORICAL_RECIPES = {
    5:   ("Tuz Asidi Damıtımı", ("tuz", "kukurt", "tuz")),
    10:  ("Zaç & Demir Sentezi", ("tuz", "demir", "bakir", "civa")),
    25:  ("Sirke Özütü", ("sirke", "sap", "tuz", "bakir", "civa")),
    50:  ("El-Kühül Damıtımı", ("sirke", "kukurt", "civa", "nisadir", "altin")),
    75:  ("Tıbbi Panzehir Sentezi", ("altin", "gumus", "civa", "safran", "afyon", "kafur")),
    100: ("Büyük Bileşim", ("civa", "kukurt", "altin", "gumus", "buyuk_iksir")),
}

BEYHEKIM_PROLOGUE_SINGLE = (
    "Hoş geldin hekim namzedi! Ben Tabîb Ekmeleddin, nam-ı diğer Bey Hekim. "
    "Konya Dârüşşifası'nın ve kadim hekimliğin sırlarını öğrenmek için kazanın başına geçtin. "
    "Birazdan üstteki sahnede kazana şifalı cevherler ve bitkiler ekleyeceğim. Bu sırayı dikkatle aklında tut! "
    "Sıra sana geldiğinde aşağıdaki butonlarla aynı sırayla kazana ekle. 3 şişe kırma hakkın var. "
    "Her 3 elementte bir süren artacak. Zihnini topla ve hazır olduğunda Başla'ya bas!"
)

BEYHEKIM_PROLOGUE_DUEL = (
    "Huzuruma hoş geldiniz çıraklar! Ben Tabîb Ekmeleddin, nam-ı diğer Bey Hekim. "
    "Hanginizin dârüşşifanın yeni baş hekimi olacağını görmek için bu yarışı tertip ettim. "
    "Üstteki sahnede kazana atacağımız şifalı malzemeleri dikkatle izleyin. Sıra size geldiğinde aynı sırayı ilk ve eksiksiz "
    "tamamlayan çırak raundu ve 1 yıldızı kazanır. Yanlış malzeme seçen 1.2 saniye sersemler ve 1 can kaybeder! "
    "Her iki çırağın da 3 canı vardır. Canları tükenen elenir ve ayakta kalan şampiyon olur! Hazırsanız Başla'ya basın!"
)

SABUNCUOGLU_GREETINGS = [
    "Amasya Dârüşşifası'ndan Melikü'l-Hükemâ Tabîb Ekmeleddin'e ve hünerli çıraklarına selam olsun! Kolay gelsin!",
    "Selam olsun dostlar! Cerrahlıkta el titremez, simyada akıl şaşmaz! Gayretiniz daim olsun!",
    "Amasya'dan geçerken bir uğrayıp selam vereyim dedim. Tabîb Ekmeleddin üstadın kazanı bereketli olsun!",
    "Mücerreb-nâme'de yazdım: Sabırla pişen iksir şifa dağıtır. Selamlarımı getirdim, muvaffak olasınız!",
    "Gözüm üzerinizde hünerli çıraklar! Her bir cevher hastaya sıhhat, hekime şereftir. Başarılar dilerim!",
    "Cerrâhiyyetü'l-İlhâniyye'nin bereketi üzerinize olsun! İlim meclisinde bir arada olmak ne güzel!",
    "Selamün aleyküm erenler! Şifa arayan gönüllere merhem olasınız. Kazanın ateşi hiç sönmesin!",
    "Tababet ilmi nezaket ve zarafet ister. Maşallah çıraklar, hüneriniz Amasya'ya kadar nam saldı!",
]


def make_room_id(prefix: str = "") -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    if prefix:
        raw = "".join(random.choice(alphabet) for _ in range(5))
        return f"{prefix}-{raw}"
    raw = "".join(random.choice(alphabet) for _ in range(6))
    return f"{raw[:3]}-{raw[3:]}"


def local_network_host() -> str:
    configured_host = os.environ.get("RAZI_HOST") or os.environ.get("BEYHEKIM_HOST")
    if configured_host:
        return configured_host
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def resolve_public_play_url(request: Request | None = None) -> str:
    env_url = os.environ.get("RAZI_PLAY_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
    if render_url:
        return f"{render_url.rstrip('/')}/play"
    space_host = os.environ.get("SPACE_HOST", "").strip()
    if space_host:
        return f"https://{space_host.rstrip('/')}/play"
    log_file = BASE_DIR / "cloudflared.log"
    if log_file.exists():
        try:
            if time.time() - log_file.stat().st_mtime < 7200:
                content = log_file.read_text(encoding="utf-8", errors="ignore")
                matches = re.findall(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
                if matches:
                    return f"{matches[-1]}/play"
        except Exception:
            pass
    if request is not None:
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        host = host.split(",")[0].strip()
        raw_scheme = request.headers.get("x-forwarded-proto", request.url.scheme or "http")
        scheme = raw_scheme.split(",")[0].strip() or "https"
        if host and not host.startswith("localhost") and not host.startswith("127.0.0.1"):
            return f"{scheme}://{host}/play"
    return f"http://{local_network_host()}:{PORT}/play"


# ── Sunucu Tabanlı Bağımsız Oyun Motoru (Tamamen Telefondan Oynama) ───────────

class ServerRoomEngine:
    """Masaüstü Pygame ekranına ihtiyaç duymadan her odayı kendi içinde yürüten
    asenkron oyun motoru. Hem Tek Kişilik hem 1v1 Çırak Düellosu modlarını destekler."""

    def __init__(self, room_id: str, room: dict[str, Any]) -> None:
        self.room_id = room_id
        self.room = room
        self.state = "WAITING"  # WAITING, DUEL_LOBBY, PROLOGUE, COUNTDOWN, RHAZI_TURN, PLAYER_TURN, RESOLUTION, GAME_OVER, DUEL_MATCH_OVER
        self.level = 1
        self.lives = 3
        self.combo = 0
        self.max_combo = 0
        self.recipe_name = ""
        self.sequence: list[str] = []
        self.player_index = 0
        self.phase_started = time.monotonic()
        self.phase_cursor = 0
        self.round_success = False
        self.last_unlocked_count = 4
        self.last_guest_level = 0
        self.is_reverse_round = False

        # Countdown
        self.countdown_start = 0.0
        self.countdown_last_num: int | None = None
        self.lobby_countdown_start: float | None = None
        self._last_tick = 0.0

        # 1v1 Düello durumu
        self.duel_round = 1
        self.duel_scores = {"player_1": 0, "player_2": 0}
        self.player_sequences: dict[str, list[str]] = {"player_1": [], "player_2": []}
        self.player_cursors = {"player_1": 0, "player_2": 0}
        self.player_lives = {"player_1": 3, "player_2": 3}
        self.player_completed = {"player_1": False, "player_2": False}
        self.first_completer: str | None = None
        self.grace_period_end: float | None = None
        self.player_stuns = {"player_1": 0.0, "player_2": 0.0}
        self.round_winner: str | None = None
        self.duel_match_winner: str | None = None

        self._task: asyncio.Task | None = None
        self._stopped = False

    @property
    def mode(self) -> str:
        return self.room.get("mode", "single")

    @property
    def duel_material_pool(self) -> tuple[str, ...]:
        total_mats = len(MATERIALS)
        base_count = 4
        if self.duel_round <= 1:
            count = base_count
        elif self.duel_round >= 25:
            count = total_mats
        else:
            count = min(total_mats, base_count + int(round((self.duel_round - 1) * ((total_mats - base_count) / 24.0))))
        return tuple(MATERIALS[:count])

    @property
    def material_pool(self) -> tuple[str, ...]:
        if self.mode == "duel":
            return self.duel_material_pool
        total_mats = len(MATERIALS)
        base_count = 4
        if self.level <= 1:
            count = base_count
        elif self.level >= 50:
            count = total_mats
        else:
            count = min(total_mats, base_count + int(round((self.level - 1) * ((total_mats - base_count) / 49.0))))
        return tuple(MATERIALS[:count])

    @property
    def reveal_duration(self) -> float:
        lvl = self.duel_round if self.mode == "duel" else self.level
        if lvl <= 5:
            dur = 1.30
        elif lvl <= 12:
            dur = 1.10
        elif lvl <= 17:
            dur = 0.92
        else:
            steps_after_17 = (lvl - 17) // 5 + 1
            dur = 0.92 - (steps_after_17 * 0.08)
        return max(0.50, dur)

    @property
    def player_duration(self) -> float:
        if self.mode == "duel":
            seq_len = len(self.sequence) if self.sequence else (2 + self.duel_round)
            pool_size = len(self.duel_material_pool)
            base_time = 6.0
            seq_time = seq_len * 2.2
            seq_bonus = (seq_len // 3) * 2.5
            pool_bonus = max(0, (pool_size - 4) // 3) * 1.0
            total = max(14.0, base_time + seq_time + seq_bonus + pool_bonus)
            return total * 4.0 if self.is_reverse_round else total

        seq_len = len(self.sequence) if self.sequence else (2 + self.level)
        pool_size = len(self.material_pool)
        base_time = 5.0
        seq_time = seq_len * 2.0
        seq_bonus = (seq_len // 3) * 3.0
        pool_bonus = max(0, (pool_size - 4) // 3) * 1.0
        total = max(12.0, base_time + seq_time + seq_bonus + pool_bonus)
        return total * 4.0 if self.is_reverse_round else total

    def ensure_running(self) -> None:
        if self._task is None or self._task.done():
            self._stopped = False
            self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        self._stopped = True
        if self._task and not self._task.done():
            self._task.cancel()

    async def send_mobile(self, message: dict[str, Any]) -> None:
        await broadcast_mobile(self.room, message)
        desktop = self.room.get("desktop")
        if isinstance(desktop, WebSocket):
            await safe_send(desktop, message)

    async def on_player_connected(self, player_id: str) -> None:
        self.ensure_running()
        players = self.room.get("players", {})
        if self.mode == "duel":
            if len(players) >= 2 and self.state == "WAITING":
                self.state = "DUEL_LOBBY"
                self.duel_scores = {"player_1": 0, "player_2": 0}
                self.duel_round = 1
                self.lobby_countdown_start = None
            player_summary = {pid: {"name": p["name"], "emblem": p["emblem"], "ready": p["ready"]} for pid, p in players.items()}
            await self.send_mobile({
                "type": "duel_lobby_state",
                "room_id": self.room_id,
                "player_count": len(players),
                "players": player_summary,
                "mode": "duel",
            })
        elif self.mode == "single":
            await self.start_prologue()
        else:
            await self.send_mobile({"type": "choose_mode", "room_id": self.room_id})

    async def on_mode_selected(self, mode: str, player_id: str) -> None:
        self.ensure_running()
        self.room["mode"] = mode
        self.room["started"] = False
        await self.send_mobile({"type": "mode_changed", "mode": mode})
        if mode == "single":
            await self.start_prologue()
        else:
            self.state = "DUEL_LOBBY"
            self.lobby_countdown_start = None
            players = self.room.get("players", {})
            player_summary = {pid: {"name": p["name"], "emblem": p["emblem"], "ready": p["ready"]} for pid, p in players.items()}
            await self.send_mobile({
                "type": "duel_lobby_state",
                "room_id": self.room_id,
                "player_count": len(players),
                "players": player_summary,
                "mode": "duel",
            })

    async def on_player_ready_changed(self) -> None:
        players = self.room.get("players", {})
        if self.mode == "duel" and self.state in ("WAITING", "DUEL_LOBBY"):
            self.state = "DUEL_LOBBY"
            p1_ready = players.get("player_1", {}).get("ready", False)
            p2_ready = players.get("player_2", {}).get("ready", False)
            if len(players) >= 2 and p1_ready and p2_ready:
                if not self.lobby_countdown_start:
                    self.lobby_countdown_start = time.monotonic()
            else:
                self.lobby_countdown_start = None

    async def start_prologue(self) -> None:
        self.state = "PROLOGUE"
        self.room["started"] = False
        if self.mode == "duel":
            await self.send_mobile({
                "type": "prologue",
                "mode": "duel",
                "title": "Tabîb Ekmeleddin'in Talimatları",
                "text": BEYHEKIM_PROLOGUE_DUEL,
                "button_text": "BAŞLA",
                "bubble_text": "Huzuruma hoş geldiniz çıraklar! Dikkatle dinleyin.",
            })
        else:
            await self.send_mobile({
                "type": "prologue",
                "mode": "single",
                "title": "Tabîb Ekmeleddin'in Talimatları",
                "text": BEYHEKIM_PROLOGUE_SINGLE,
                "button_text": "BAŞLA",
                "bubble_text": "Hoş geldin hekim namzedi! Konya Dârüşşifası'nın sırlarını öğrenmeye hazır mısın?",
            })

    async def on_start_game(self, player_id: str) -> None:
        self.ensure_running()
        if self.state not in ("PROLOGUE", "WAITING", "DUEL_LOBBY"):
            return
        if self.mode == "duel":
            self.duel_round = 1
            self.duel_scores = {"player_1": 0, "player_2": 0}
            self.player_lives = {"player_1": 3, "player_2": 3}
            self.player_cursors = {"player_1": 0, "player_2": 0}
            self.player_completed = {"player_1": False, "player_2": False}
            self.player_sequences = {"player_1": [], "player_2": []}
            self.first_completer = None
            self.grace_period_end = None
            self.player_stuns = {"player_1": 0.0, "player_2": 0.0}
            self.round_winner = None
            self.duel_match_winner = None
            self.is_reverse_round = False
        else:
            self.level = 1
            self.lives = 3
            self.combo = 0
            self.max_combo = 0
            self.sequence = []
            self.last_unlocked_count = 4
            self.last_guest_level = 0
            self.is_reverse_round = False
        await self.start_countdown()

    async def start_countdown(self) -> None:
        self.state = "COUNTDOWN"
        self.room["started"] = True
        self.countdown_start = time.monotonic()
        self.countdown_last_num = None
        await self._tick_countdown(force=True)

    async def _tick_countdown(self, force: bool = False) -> None:
        now = time.monotonic()
        elapsed = now - self.countdown_start
        if elapsed < 1.0:
            num = 3
        elif elapsed < 2.0:
            num = 2
        elif elapsed < 3.0:
            num = 1
        elif elapsed < 3.8:
            num = 0
        else:
            await self.start_rhazi_turn()
            return

        if force or num != self.countdown_last_num:
            self.countdown_last_num = num
            web_label = "BAŞLA!" if num == 0 else str(num)
            await self.send_mobile({
                "type": "countdown",
                "count": num,
                "label": web_label,
                "mode": self.mode,
            })

    async def start_rhazi_turn(self) -> None:
        self.round_success = False
        self.is_reverse_round = False
        self.room["started"] = True

        if self.mode == "duel":
            pool = self.duel_material_pool
            p1_seq = self.player_sequences.get("player_1", [])
            p2_seq = self.player_sequences.get("player_2", [])
            if self.duel_round == 1 or not p1_seq or not p2_seq:
                p1_seq = [random.choice(pool) for _ in range(3)]
                p2_seq = [random.choice(pool) for _ in range(3)]
                attempts = 0
                while p2_seq == p1_seq and len(pool) > 1 and attempts < 10:
                    p2_seq = [random.choice(pool) for _ in range(3)]
                    attempts += 1
                self.player_sequences["player_1"] = p1_seq
                self.player_sequences["player_2"] = p2_seq
            else:
                self.player_sequences["player_1"].append(random.choice(pool))
                self.player_sequences["player_2"].append(random.choice(pool))

            self.sequence = self.player_sequences["player_1"]
            self.recipe_name = HISTORICAL_RECIPES[self.duel_round][0] if self.duel_round in HISTORICAL_RECIPES else ""

            self.player_cursors = {"player_1": 0, "player_2": 0}
            self.player_completed = {"player_1": False, "player_2": False}
            self.first_completer = None
            self.grace_period_end = None
            self.player_stuns = {"player_1": 0.0, "player_2": 0.0}
            self.round_winner = None
            self.phase_cursor = -1
            self.phase_started = time.monotonic() - max(0.0, self.reveal_duration - 0.60)
            self.state = "RHAZI_TURN"

            bubble = (
                f"Seviye {self.duel_round}: Formül '{self.recipe_name}'! Dikkatle izleyin!"
                if self.recipe_name
                else f"Düello Seviye {self.duel_round}! Malzemeleri dikkatle izleyin!"
            )

            await self.send_mobile({
                "type": "round_started",
                "mode": "duel",
                "unlocked": list(pool),
                "round_num": self.duel_round,
                "level": self.duel_round,
                "duel_scores": self.duel_scores,
                "player_lives": self.player_lives,
                "lives": self.player_lives,
                "recipe": self.recipe_name,
                "is_reverse": self.is_reverse_round,
                "reveal_duration": round(self.reveal_duration, 2),
                "seq_len": len(self.sequence),
                "p1_sequence": list(self.player_sequences["player_1"]),
                "p2_sequence": list(self.player_sequences["player_2"]),
                "bubble_text": bubble,
            })
            return

        # Tek Kişilik Macera
        unlocked = list(self.material_pool)
        if self.level == 1 or not self.sequence:
            self.sequence = [random.choice(unlocked) for _ in range(3)]
        else:
            self.sequence.append(random.choice(unlocked))

        self.recipe_name = HISTORICAL_RECIPES[self.level][0] if self.level in HISTORICAL_RECIPES else ""
        self.phase_cursor = -1
        self.phase_started = time.monotonic() - max(0.0, self.reveal_duration - 0.60)
        self.state = "RHAZI_TURN"

        # Sabuncuoğlu Şerefeddin ziyareti kontrolü
        sab_greeting = None
        if self.level > 1 and (self.level - self.last_guest_level >= 2) and (random.random() < 0.35):
            self.last_guest_level = self.level
            sab_greeting = random.choice(SABUNCUOGLU_GREETINGS)

        info_mat = None
        if self.recipe_name:
            bubble = f"Tarihi Formül: '{self.recipe_name}'! Malzemeleri dikkatle izle."
        elif len(unlocked) > self.last_unlocked_count:
            info_mat = unlocked[-1]
            self.last_unlocked_count = len(unlocked)
            bubble = f"Seviye {self.level}! Yeni cevher açıldı: {MATERIAL_NAMES.get(info_mat, info_mat)}"
        elif self.combo >= 2:
            bubble = f"Harika seri! x{self.combo} Kombo! Odaklan."
        else:
            if random.random() < 0.4:
                info_mat = random.choice(unlocked)
            bubble = f"Seviye {self.level}. Attığım malzemeleri dikkatle izle!"

        await self.send_mobile({
            "type": "round_started",
            "mode": "single",
            "level": self.level,
            "unlocked": unlocked,
            "lives": self.lives,
            "combo": self.combo,
            "recipe": self.recipe_name,
            "is_reverse": self.is_reverse_round,
            "reveal_duration": round(self.reveal_duration, 2),
            "seq_len": len(self.sequence),
            "sequence": list(self.sequence),
            "bubble_text": bubble,
            "info_card_mat": info_mat,
            "sabuncuoglu_greeting": sab_greeting,
        })

    async def on_button(self, button: str, player_id: str) -> None:
        if self.room.get("desktop") is not None:
            return
        if button == "reset":
            self.level = 1
            self.lives = 3
            self.combo = 0
            self.max_combo = 0
            self.recipe_name = ""
            self.sequence = []
            self.player_index = 0
            self.phase_cursor = 0
            self.last_unlocked_count = 4
            await self.start_countdown()
            return
        if button == "rematch":
            await self.reset_duel()
            return

        if self.state != "PLAYER_TURN":
            return

        if button not in self.material_pool and button not in MATERIALS:
            return

        if self.mode == "duel":
            await self._handle_duel_button(button, player_id)
        else:
            await self._handle_single_button(button, player_id)

    async def _handle_single_button(self, button: str, player_id: str) -> None:
        target_seq = list(reversed(self.sequence)) if self.is_reverse_round else self.sequence
        if self.player_index >= len(target_seq):
            return

        correct = target_seq[self.player_index]
        if button != correct:
            self.lives -= 1
            self.combo = 0
            name = MATERIAL_NAMES.get(button, button)
            correct_tr = MATERIAL_NAMES.get(correct, correct)
            rev_note = " (Tersten gidiyordun!)" if self.is_reverse_round else ""

            if self.lives > 0:
                self.phase_started = time.monotonic()
                self._last_tick = 0.0
                await self.send_mobile({
                    "type": "life_lost",
                    "lives": self.lives,
                    "combo": 0,
                    "wrong_material": button,
                    "is_reverse": self.is_reverse_round,
                    "bubble_text": f"Yanlış malzeme! '{name}' değil.{rev_note} ({self.lives} can kaldı!)",
                    "message": f"Yanlış seçim ('{name}')! {self.lives} canın kaldı. Doğru malzemeyi tekrar dene!{rev_note}",
                    "total": round(self.player_duration, 1),
                })
                return

            self.state = "RESOLUTION"
            self.round_success = False
            self.phase_started = time.monotonic()
            self.room["started"] = False
            await self.send_mobile({
                "type": "game_over",
                "message": f"Yanlış! '{name}' seçildi (Doğrusu: {correct_tr}).",
                "bubble_text": f"Eyvah! Tüm şişeler kırıldı! Doğrusu {correct_tr} idi!",
                "level": self.level,
                "max_combo": self.max_combo,
            })
            return

        # Doğru seçim
        self.player_index += 1
        await self.send_mobile({
            "type": "player_step_ok",
            "player_id": player_id,
            "cursor": self.player_index,
            "total": len(target_seq),
            "material": button,
            "name": MATERIAL_NAMES.get(button, button),
            "fact": MATERIAL_NOTES.get(button, ""),
        })

        if self.player_index == len(target_seq):
            self.state = "RESOLUTION"
            self.round_success = True
            self.combo += 1
            self.max_combo = max(self.max_combo, self.combo)
            self.phase_started = time.monotonic()
            self.level += 1

            await self.send_mobile({
                "type": "round_success",
                "level": self.level,
                "combo": self.combo,
                "lives": self.lives,
                "recipe_completed": bool(self.recipe_name),
                "bubble_text": f"Mükemmel! Seviye {self.level}'e geçtik!",
            })

            if self.level in (26, 51, 76) and self.lives < 3:
                self.lives += 1
                await self.send_mobile({"type": "life_gained", "lives": self.lives})

    async def _handle_duel_button(self, button: str, player_id: str) -> None:
        if player_id not in ("player_1", "player_2"):
            return
        now = time.monotonic()
        if now < self.player_stuns.get(player_id, 0.0):
            return
        if self.player_lives.get(player_id, 3) <= 0:
            return
        if self.player_completed.get(player_id, False):
            return

        cur_idx = self.player_cursors.get(player_id, 0)
        p_seq = self.player_sequences.get(player_id, self.sequence)
        target_seq = list(reversed(p_seq)) if self.is_reverse_round else p_seq
        if cur_idx >= len(target_seq):
            return

        correct = target_seq[cur_idx]
        players = self.room.get("players", {})
        p_name = players.get(player_id, {}).get("name", player_id)
        other_id = "player_2" if player_id == "player_1" else "player_1"
        other_name = players.get(other_id, {}).get("name", other_id)

        if button == correct:
            cur_idx += 1
            self.player_cursors[player_id] = cur_idx
            await self.send_mobile({
                "type": "duel_progress",
                "player_id": player_id,
                "cursor": cur_idx,
                "total": len(target_seq),
                "material": button,
                "name": MATERIAL_NAMES.get(button, button),
                "is_reverse": self.is_reverse_round,
            })

            if cur_idx == len(target_seq):
                self.player_completed[player_id] = True
                if self.first_completer is None:
                    self.first_completer = player_id
                    self.round_winner = player_id
                    self.duel_scores[player_id] = self.duel_scores.get(player_id, 0) + 1

                    if self.player_lives.get(other_id, 3) > 0 and not self.player_completed.get(other_id, False):
                        self.grace_period_end = now + 3.5
                        await self.send_mobile({
                            "type": "opponent_finished",
                            "target": other_id,
                            "finisher": p_name,
                            "grace_seconds": 3.5,
                            "message": f"[!] {p_name} tamamladı! Canını korumak için 3.5 saniyede bitir!",
                        })
                        await self.send_mobile({
                            "type": "first_completed",
                            "target": player_id,
                            "scores": self.duel_scores,
                            "message": "Kazanı ilk sen tamamladın! (+1 Yıldız)",
                        })
                    else:
                        await self._finish_duel_round(winner_id=player_id)
                else:
                    await self.send_mobile({
                        "type": "second_completed",
                        "target": player_id,
                        "message": "Süre dolmadan tamamladın! Canın korundu.",
                    })
                    await self._finish_duel_round(winner_id=self.first_completer)
        else:
            self.player_lives[player_id] -= 1
            self.player_stuns[player_id] = now + 1.2
            rem_lives = self.player_lives[player_id]
            rev_note = " (Tersten gidiyordun!)" if self.is_reverse_round else ""

            await self.send_mobile({
                "type": "life_lost",
                "target": player_id,
                "player_id": player_id,
                "lives": rem_lives,
                "player_lives": self.player_lives,
                "wrong_material": button,
                "is_reverse": self.is_reverse_round,
                "message": f"Yanlış malzeme! 1 Can kaybettin ({rem_lives} can kaldı). Doğru malzemeyi tekrar dene!{rev_note}",
            })
            await self.send_mobile({
                "type": "stunned",
                "target": player_id,
                "player_id": player_id,
                "duration": 1.2,
                "message": "Yanlış malzeme! 1.2 saniye sersemledin.",
            })
            await self.send_mobile({
                "type": "opponent_mistake",
                "target": other_id,
                "player_id": player_id,
                "opp_lives": rem_lives,
                "player_lives": self.player_lives,
                "message": f"Rakip {p_name} hata yaptı ve 1 can kaybetti! ({rem_lives} canı kaldı)",
            })

            if rem_lives <= 0:
                self.duel_match_winner = other_id
                self.state = "DUEL_MATCH_OVER"
                self.room["started"] = False
                await self.send_mobile({
                    "type": "duel_match_over",
                    "winner_id": other_id,
                    "winner_name": other_name,
                    "loser_id": player_id,
                    "loser_name": p_name,
                    "scores": self.duel_scores,
                    "player_lives": self.player_lives,
                    "level_reached": self.duel_round,
                })

    async def _finish_duel_round(self, winner_id: str | None) -> None:
        self.state = "RESOLUTION"
        self.phase_started = time.monotonic()
        self.grace_period_end = None
        players = self.room.get("players", {})
        w_name = players.get(winner_id, {}).get("name", "Çırak") if winner_id else None
        if winner_id:
            await self.send_mobile({
                "type": "duel_round_won",
                "winner_id": winner_id,
                "winner_name": w_name,
                "scores": self.duel_scores,
                "player_lives": self.player_lives,
                "round_num": self.duel_round,
            })
        else:
            await self.send_mobile({
                "type": "duel_round_draw",
                "scores": self.duel_scores,
                "player_lives": self.player_lives,
                "round_num": self.duel_round,
            })

    async def _handle_duel_grace_timeout(self) -> None:
        self.grace_period_end = None
        first_p = self.first_completer or "player_1"
        second_p = "player_2" if first_p == "player_1" else "player_1"
        players = self.room.get("players", {})
        s_name = players.get(second_p, {}).get("name", second_p)
        w_name = players.get(first_p, {}).get("name", first_p)

        if not self.player_completed.get(second_p, False):
            self.player_lives[second_p] -= 1
            s_lives = self.player_lives[second_p]
            await self.send_mobile({
                "type": "life_lost",
                "target": second_p,
                "player_id": second_p,
                "lives": s_lives,
                "player_lives": self.player_lives,
                "message": f"Süre tükendi! 1 Can kaybettin ({s_lives} can kaldı).",
            })
            await self.send_mobile({
                "type": "opponent_mistake",
                "target": first_p,
                "player_id": second_p,
                "opp_lives": s_lives,
                "player_lives": self.player_lives,
                "message": f"Rakip {s_name} sürede tamamlayamadı ve 1 can kaybetti! ({s_lives} can kaldı)",
            })
            if s_lives <= 0:
                self.duel_match_winner = first_p
                self.state = "DUEL_MATCH_OVER"
                self.room["started"] = False
                await self.send_mobile({
                    "type": "duel_match_over",
                    "winner_id": first_p,
                    "winner_name": w_name,
                    "loser_id": second_p,
                    "loser_name": s_name,
                    "scores": self.duel_scores,
                    "player_lives": self.player_lives,
                    "level_reached": self.duel_round,
                })
                return

        await self._finish_duel_round(winner_id=first_p)

    async def _duel_time_out(self) -> None:
        p1_done = self.player_completed.get("player_1", False)
        p2_done = self.player_completed.get("player_2", False)
        if not p1_done:
            self.player_lives["player_1"] -= 1
        if not p2_done:
            self.player_lives["player_2"] -= 1

        p1_lives = self.player_lives["player_1"]
        p2_lives = self.player_lives["player_2"]
        players = self.room.get("players", {})
        p1_name = players.get("player_1", {}).get("name", "Çırak 1")
        p2_name = players.get("player_2", {}).get("name", "Çırak 2")

        for pid, lives in [("player_1", p1_lives), ("player_2", p2_lives)]:
            if not self.player_completed.get(pid, False):
                await self.send_mobile({
                    "type": "life_lost",
                    "target": pid,
                    "player_id": pid,
                    "lives": lives,
                    "player_lives": self.player_lives,
                    "message": f"Süre doldu! 1 Can kaybettin ({lives} can kaldı).",
                })

        if p1_lives <= 0 and p2_lives <= 0:
            s1 = self.duel_scores.get("player_1", 0)
            s2 = self.duel_scores.get("player_2", 0)
            winner_id = "player_1" if s1 >= s2 else "player_2"
            w_name = players.get(winner_id, {}).get("name", winner_id)
            self.state = "DUEL_MATCH_OVER"
            self.room["started"] = False
            await self.send_mobile({
                "type": "duel_match_over",
                "winner_id": winner_id,
                "winner_name": w_name,
                "scores": self.duel_scores,
                "player_lives": self.player_lives,
                "level_reached": self.duel_round,
            })
        elif p1_lives <= 0:
            self.state = "DUEL_MATCH_OVER"
            self.room["started"] = False
            await self.send_mobile({
                "type": "duel_match_over",
                "winner_id": "player_2",
                "winner_name": p2_name,
                "loser_id": "player_1",
                "loser_name": p1_name,
                "scores": self.duel_scores,
                "player_lives": self.player_lives,
                "level_reached": self.duel_round,
            })
        elif p2_lives <= 0:
            self.state = "DUEL_MATCH_OVER"
            self.room["started"] = False
            await self.send_mobile({
                "type": "duel_match_over",
                "winner_id": "player_1",
                "winner_name": p1_name,
                "loser_id": "player_2",
                "loser_name": p2_name,
                "scores": self.duel_scores,
                "player_lives": self.player_lives,
                "level_reached": self.duel_round,
            })
        else:
            self.state = "RESOLUTION"
            self.phase_started = time.monotonic()
            await self.send_mobile({
                "type": "duel_round_draw",
                "scores": self.duel_scores,
                "player_lives": self.player_lives,
                "round_num": self.duel_round,
            })

    async def _single_time_out(self) -> None:
        self.lives -= 1
        self.combo = 0
        if self.lives > 0:
            self.phase_started = time.monotonic()
            self._last_tick = 0.0
            await self.send_mobile({
                "type": "life_lost",
                "lives": self.lives,
                "combo": 0,
                "bubble_text": f"Vakit tükendi! Bir şişen kırıldı ({self.lives} can kaldı).",
                "message": f"Süre tükendi! {self.lives} canın kaldı. Kaldığın yerden devam et!",
                "total": round(self.player_duration, 1),
            })
            return

        self.state = "GAME_OVER"
        self.round_success = False
        self.room["started"] = False
        await self.send_mobile({
            "type": "game_over",
            "message": "Süre doldu — Kazan taştı!",
            "bubble_text": "Vakit tükendi ve tüm şişeler kırıldı!",
            "level": self.level,
            "max_combo": self.max_combo,
        })

    async def reset_duel(self) -> None:
        self.duel_scores = {"player_1": 0, "player_2": 0}
        self.duel_round = 1
        self.player_cursors = {"player_1": 0, "player_2": 0}
        self.player_lives = {"player_1": 3, "player_2": 3}
        self.player_completed = {"player_1": False, "player_2": False}
        self.player_sequences = {"player_1": [], "player_2": []}
        self.sequence = []
        self.first_completer = None
        self.grace_period_end = None
        self.player_stuns = {"player_1": 0.0, "player_2": 0.0}
        self.round_winner = None
        self.duel_match_winner = None
        self.lobby_countdown_start = None
        for p in self.room.get("players", {}).values():
            p["ready"] = False
        self.state = "DUEL_LOBBY"
        self.room["started"] = False
        await self.send_mobile({
            "type": "duel_lobby_reset",
            "scores": self.duel_scores,
            "player_lives": self.player_lives,
        })

    async def _loop(self) -> None:
        try:
            while not self._stopped:
                await asyncio.sleep(0.05)
                if not self.room.get("players"):
                    break

                now = time.monotonic()

                if self.state == "DUEL_LOBBY":
                    if self.lobby_countdown_start and (now - self.lobby_countdown_start >= 0.8):
                        self.lobby_countdown_start = None
                        await self.on_start_game("player_1")
                    continue

                if self.state == "COUNTDOWN":
                    await self._tick_countdown()
                    continue

                if self.state == "RHAZI_TURN":
                    if now - self.phase_started >= self.reveal_duration:
                        self.phase_started = now
                        self.phase_cursor += 1
                        if self.phase_cursor >= len(self.sequence):
                            self.state = "PLAYER_TURN"
                            self.player_index = 0
                            if self.mode == "duel":
                                self.player_cursors = {"player_1": 0, "player_2": 0}
                                self.player_completed = {"player_1": False, "player_2": False}
                                self.first_completer = None
                                self.grace_period_end = None
                                self.player_stuns = {"player_1": 0.0, "player_2": 0.0}
                            self._last_tick = 0.0
                            await self.send_mobile({
                                "type": "player_turn",
                                "mode": self.mode,
                                "total": round(self.player_duration, 1),
                                "seq_len": len(self.sequence),
                                "is_reverse": self.is_reverse_round,
                                "bubble_text": "Yarış başladı! Sırayı hatasız tamamlayın!" if self.mode == "duel" else "Sıra sende çırak! Malzemeleri sırayla seç.",
                            })
                        else:
                            if self.mode == "duel":
                                p1_seq = self.player_sequences.get("player_1", self.sequence)
                                p2_seq = self.player_sequences.get("player_2", self.sequence)
                                p1_m = p1_seq[self.phase_cursor] if self.phase_cursor < len(p1_seq) else p1_seq[-1]
                                p2_m = p2_seq[self.phase_cursor] if self.phase_cursor < len(p2_seq) else p2_seq[-1]
                                m1_lbl = MATERIAL_NAMES.get(p1_m, p1_m)
                                m2_lbl = MATERIAL_NAMES.get(p2_m, p2_m)
                                await self.send_mobile({
                                    "type": "reveal_step",
                                    "target": "player_1",
                                    "step": self.phase_cursor + 1,
                                    "total": len(p1_seq),
                                    "material": p1_m,
                                    "name": m1_lbl,
                                    "p1_material": p1_m,
                                    "p2_material": p2_m,
                                    "p1_name": m1_lbl,
                                    "p2_name": m2_lbl,
                                    "reveal_duration": round(self.reveal_duration, 2),
                                })
                                await self.send_mobile({
                                    "type": "reveal_step",
                                    "target": "player_2",
                                    "step": self.phase_cursor + 1,
                                    "total": len(p2_seq),
                                    "material": p2_m,
                                    "name": m2_lbl,
                                    "p1_material": p1_m,
                                    "p2_material": p2_m,
                                    "p1_name": m1_lbl,
                                    "p2_name": m2_lbl,
                                    "reveal_duration": round(self.reveal_duration, 2),
                                })
                            else:
                                mat = self.sequence[self.phase_cursor]
                                m_lbl = MATERIAL_NAMES.get(mat, mat)
                                await self.send_mobile({
                                    "type": "reveal_step",
                                    "step": self.phase_cursor + 1,
                                    "total": len(self.sequence),
                                    "material": mat,
                                    "name": m_lbl,
                                    "reveal_duration": round(self.reveal_duration, 2),
                                    "bubble_text": f"{m_lbl} ekliyorum...",
                                })

                elif self.state == "PLAYER_TURN":
                    if self.mode == "duel" and self.grace_period_end is not None:
                        remaining = max(0.0, self.grace_period_end - now)
                        tot = 3.5
                    else:
                        remaining = max(0.0, self.player_duration - (now - self.phase_started))
                        tot = self.player_duration

                    if now - self._last_tick >= 0.4:
                        self._last_tick = now
                        await self.send_mobile({
                            "type": "timer_tick",
                            "remaining": round(remaining, 1),
                            "total": round(tot, 1),
                        })

                    if self.mode == "duel" and self.grace_period_end is not None and now >= self.grace_period_end:
                        await self._handle_duel_grace_timeout()
                    elif now - self.phase_started >= self.player_duration:
                        if self.mode == "duel":
                            await self._duel_time_out()
                        else:
                            await self._single_time_out()

                elif self.state == "RESOLUTION":
                    if now - self.phase_started >= 2.3:
                        if self.mode == "duel":
                            self.duel_round += 1
                            await self.start_rhazi_turn()
                        else:
                            if self.round_success:
                                await self.start_rhazi_turn()
                            else:
                                self.state = "GAME_OVER"
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error("ServerRoomEngine error in room %s: %s", self.room_id, e)


# ── Cloudflare Tünel Keepalive (100s timeout önlemi) ─────────────────────────

async def _ws_keepalive_loop() -> None:
    while True:
        await asyncio.sleep(50)
        for room in list(rooms.values()):
            desktop = room.get("desktop")
            if isinstance(desktop, WebSocket):
                try:
                    await desktop.send_json({"type": "ping"})
                except Exception:
                    pass
            for p_info in list(room.get("players", {}).values()):
                ws = p_info.get("ws")
                if ws:
                    try:
                        await ws.send_json({"type": "ping"})
                    except Exception:
                        pass


# ── Başlangıç / Kapatma ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_name TEXT DEFAULT 'Simyacı',
                level INTEGER NOT NULL,
                max_combo INTEGER DEFAULT 0,
                room_id TEXT,
                ts INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor = await db.execute("PRAGMA table_info(scores)")
        cols = [c[1] for c in await cursor.fetchall()]
        if "player_name" not in cols:
            await db.execute("ALTER TABLE scores ADD COLUMN player_name TEXT DEFAULT 'Simyacı'")
        if "max_combo" not in cols:
            await db.execute("ALTER TABLE scores ADD COLUMN max_combo INTEGER DEFAULT 0")
        if "ts" not in cols:
            await db.execute("ALTER TABLE scores ADD COLUMN ts INTEGER")
        await db.commit()

    log.info("Database ready: %s", DB_PATH)
    keepalive_task = asyncio.create_task(_ws_keepalive_loop())
    log.info("WebSocket keepalive task started (50s interval).")

    tunnel_holder: list[Any] = []
    if os.environ.get("RAZI_MANAGED_TUNNEL") != "1" and not os.environ.get("RAZI_PLAY_URL"):
        cf_bin = BASE_DIR / "cloudflared.exe"
        if cf_bin.exists():
            import subprocess
            import threading

            def _bg_tunnel() -> None:
                log_file = BASE_DIR / "cloudflared.log"
                url_pat = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
                for proto in ("http2", None):
                    try:
                        log_file.write_text("", encoding="utf-8")
                    except Exception:
                        pass
                    cmd = [str(cf_bin), "tunnel", "--url", f"http://127.0.0.1:{PORT}", "--logfile", str(log_file)]
                    if proto:
                        cmd.extend(["--protocol", proto])
                    try:
                        proc = subprocess.Popen(
                            cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            bufsize=1,
                            cwd=str(BASE_DIR),
                        )
                    except Exception as exc:
                        log.warning("Cloudflare tunnel failed to spawn: %s", exc)
                        return
                    found: list[str] = []

                    def _drain(p=proc, out=found) -> None:
                        if not p.stdout:
                            return
                        try:
                            for line in p.stdout:
                                if not out:
                                    m = url_pat.search(line)
                                    if m:
                                        out.append(m.group(0))
                        except Exception:
                            pass

                    threading.Thread(target=_drain, daemon=True).start()
                    t0 = time.time()
                    while time.time() - t0 < 15.0:
                        if found:
                            break
                        if log_file.exists():
                            try:
                                m = url_pat.search(log_file.read_text(encoding="utf-8", errors="ignore"))
                                if m:
                                    found.append(m.group(0))
                                    break
                            except Exception:
                                pass
                        if proc.poll() is not None:
                            break
                        time.sleep(0.25)

                    if found:
                        tunnel_holder.append(proc)
                        play_url = f"{found[0]}/play"
                        os.environ["RAZI_PLAY_URL"] = play_url
                        log.info("Cloudflare Tunnel Ready: %s", play_url)
                        return
                    else:
                        try:
                            proc.terminate()
                        except Exception:
                            pass

            threading.Thread(target=_bg_tunnel, daemon=True).start()

    yield
    keepalive_task.cancel()
    for p in tunnel_holder:
        try:
            p.terminate()
        except Exception:
            pass


app = FastAPI(title="Tabîb Ekmeleddin'in Kazanı — Sunucu", lifespan=lifespan)

# Statik görseller ve fontlar (/assets/...)
if (BASE_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(BASE_DIR / "assets")), name="assets")


# ── Güvenlik Başlıkları Middleware'i ─────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://www.gstatic.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data: blob:; "
            "object-src 'self' blob:; "
            "frame-src 'self' blob:; "
            "connect-src 'self' ws: wss:; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "frame-ancestors 'self';"
        )
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response

app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# room_id → {"desktop": WebSocket | None, "players": dict[str, dict], "sockets": dict[WebSocket, str], "engine": ServerRoomEngine}
rooms: dict[str, dict[str, Any]] = {}


# ── Yardımcılar ───────────────────────────────────────────────────────────────

async def safe_send(ws: WebSocket, message: dict[str, Any]) -> None:
    try:
        await ws.send_json(message)
    except Exception:
        pass


async def broadcast_mobile(room: dict, message: dict[str, Any]) -> None:
    target = message.get("target")
    players = room.get("players", {})
    if target and target in players:
        ws = players[target].get("ws")
        if ws:
            await safe_send(ws, message)
        return

    for p_info in list(players.values()):
        ws = p_info.get("ws")
        if ws:
            await safe_send(ws, message)


def get_or_create_room(clean_id: str, mode: str = "undecided") -> dict[str, Any]:
    if clean_id not in rooms:
        room: dict[str, Any] = {
            "desktop": None,
            "players": {},
            "sockets": {},
            "mode": mode,
            "started": False,
            "created_at": time.monotonic(),
        }
        room["engine"] = ServerRoomEngine(clean_id, room)
        rooms[clean_id] = room
    return rooms[clean_id]


# ── QR & Eşleştirme API ───────────────────────────────────────────────────────

@app.get("/api/qr")
async def get_qr_image(request: Request, url: str | None = None) -> Response:
    """Ekrandan okutulacak QR kodu PNG olarak üretir."""
    target_url = url or resolve_public_play_url(request)
    img = qrcode.make(target_url).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@app.post("/api/matchmake")
@app.get("/api/matchmake")
async def matchmake(request: Request, mode: str = "single", room: str = "") -> JSONResponse:
    """Telefondan mod seçildiğinde uygun bir oda bulur veya yeni oda açar."""
    clean_mode = "duel" if mode == "duel" else "single"
    requested_room = room.strip().upper()

    if clean_mode == "single":
        # Tek kişilik modda her oyuncuya kendi bağımsız odasını ver
        new_id = make_room_id("S")
        while new_id in rooms:
            new_id = make_room_id("S")
        r = get_or_create_room(new_id, mode="single")
        r["mode"] = "single"
        return JSONResponse({"ok": True, "room_id": new_id, "mode": "single"})

    # 1v1 Düello modu:
    # 1) Belirli bir oda kodu girildiyse oraya katıl
    if requested_room and ROOM_ID_PATTERN.match(requested_room):
        r = get_or_create_room(requested_room, mode="duel")
        r["mode"] = "duel"
        return JSONResponse({"ok": True, "room_id": requested_room, "mode": "duel"})

    # 2) Açıkta bekleyen (0 veya 1 oyunculu, henüz başlamamış) düello odası varsa eşleştir
    now_mono = time.monotonic()
    for rid, r_info in list(rooms.items()):
        p_cnt = len(r_info.get("players", {}))
        age = now_mono - r_info.get("created_at", now_mono)
        if (
            r_info.get("desktop") is None
            and r_info.get("mode") == "duel"
            and not r_info.get("started", False)
            and (p_cnt == 1 or (p_cnt == 0 and age < 120.0))
        ):
            return JSONResponse({"ok": True, "room_id": rid, "mode": "duel", "matched": True})

    # 3) Yoksa yeni bir 1v1 düello odası oluştur
    new_duel_id = make_room_id("D")
    while new_duel_id in rooms:
        new_duel_id = make_room_id("D")
    r = get_or_create_room(new_duel_id, mode="duel")
    r["mode"] = "duel"
    return JSONResponse({"ok": True, "room_id": new_duel_id, "mode": "duel", "matched": False})


# ── Statik, Stand Sergi & Canlı Skor Dashboard Sayfaları ─────────────────────

@app.get("/api/dashboard")
async def get_dashboard_data(request: Request) -> JSONResponse:
    """Stand ekranı ve mobil tek kişilik skor dashboard'u için canlı verileri döner."""
    play_url = resolve_public_play_url(request)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT player_name, level, max_combo, room_id, ts FROM scores ORDER BY level DESC, max_combo DESC, ts DESC LIMIT 35"
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        total_cur = await db.execute("SELECT COUNT(*), COALESCE(MAX(level), 0), COALESCE(MAX(max_combo), 0) FROM scores")
        tot_row = await total_cur.fetchone()
        total_scores = int(tot_row[0] or 0)
        max_level = int(tot_row[1] or 0)
        max_combo = int(tot_row[2] or 0)

    champion_name = str(rows[0]["player_name"]) if rows else "Henüz Yok"
    formatted_scores = []
    for i, r in enumerate(rows):
        lvl = int(r.get("level") or 1)
        ts_val = int(r.get("ts") or time.time())
        formatted_scores.append({
            "rank": i + 1,
            "player_name": str(r.get("player_name") or "Simyacı"),
            "title": get_alchemical_title(lvl),
            "level": lvl,
            "max_combo": int(r.get("max_combo") or 0),
            "room_id": str(r.get("room_id") or "—"),
            "ts": ts_val,
            "time_str": time.strftime("%d.%m %H:%M", time.localtime(ts_val)),
        })

    active_sessions = []
    active_players_count = 0
    for rid, r_info in list(rooms.items()):
        p_map = r_info.get("players", {})
        if not p_map:
            continue
        active_players_count += len(p_map)
        eng: ServerRoomEngine | None = r_info.get("engine")
        lvl = (eng.duel_round if eng.mode == "duel" else eng.level) if eng else 1
        cmb = eng.combo if eng else 0
        p_names = [str(p.get("name") or "Hekim") for p in p_map.values()]
        active_sessions.append({
            "room_id": rid,
            "mode": r_info.get("mode", "single"),
            "level": lvl,
            "combo": cmb,
            "players": p_names,
            "state": eng.state if eng else "WAITING",
        })

    return JSONResponse({
        "ok": True,
        "play_url": play_url,
        "total_scores": total_scores,
        "max_level": max_level,
        "max_combo": max_combo,
        "champion_name": champion_name,
        "active_rooms_count": len(active_sessions),
        "active_players_count": active_players_count,
        "active_sessions": active_sessions,
        "scores": formatted_scores,
    })


@app.get("/", response_class=HTMLResponse)
@app.get("/kiosk", response_class=HTMLResponse)
@app.get("/stand", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    play_url = resolve_public_play_url(request)
    return HTMLResponse(f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Tabîb Ekmeleddin'in Kazanı — Stand & Canlı Skor Dashboard</title>
  <style>
    :root {{
      --bg: #100b08; --panel: #1d130c; --panel-2: #261910; --border: #6a4628;
      --gold: #d4a848; --gold-lt: #f8d568; --ink: #f2e6cf; --muted: #a8987e;
      --green: #4ade80; --red: #f87171;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      min-height: 100vh;
      background:
        radial-gradient(ellipse at 20% 0%, rgba(212, 168, 72, 0.16) 0%, transparent 55%),
        radial-gradient(ellipse at 80% 100%, rgba(82, 185, 130, 0.10) 0%, transparent 55%),
        linear-gradient(180deg, #1b110b 0%, #0e0906 100%);
      color: var(--ink);
      font-family: Georgia, 'Segoe UI', serif;
      padding: 18px;
    }}
    .stand-shell {{
      max-width: 1280px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .stand-topbar {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      background: linear-gradient(135deg, #26180f, #170e09);
      border: 1.5px solid var(--gold);
      border-radius: 16px;
      padding: 14px 20px;
      box-shadow: 0 8px 28px rgba(0,0,0,0.65);
    }}
    .brand-title h1 {{
      font-size: clamp(1.3rem, 3vw, 1.85rem);
      color: var(--gold-lt);
      letter-spacing: .02em;
    }}
    .brand-title p {{
      font-size: .85rem;
      color: #dfb558;
      font-style: italic;
      margin-top: 2px;
    }}
    .topbar-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .top-btn {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 9px 14px;
      border-radius: 10px;
      font-size: .84rem;
      font-weight: 700;
      text-decoration: none;
      cursor: pointer;
      border: 1px solid var(--border);
      background: #281a10;
      color: var(--ink);
      transition: all .2s;
      font-family: inherit;
    }}
    .top-btn:hover {{
      border-color: var(--gold-lt);
      color: var(--gold-lt);
      transform: translateY(-1px);
    }}
    .top-btn.primary {{
      background: linear-gradient(135deg, var(--gold-lt), #b58020);
      color: #120c07;
      border-color: var(--gold-lt);
      font-weight: 900;
    }}
    .stand-grid {{
      display: grid;
      grid-template-columns: 380px 1fr;
      gap: 18px;
      align-items: start;
    }}
    @media (max-width: 960px) {{
      .stand-grid {{ grid-template-columns: 1fr; }}
    }}
    .card {{
      background: var(--panel);
      border: 1.5px solid var(--border);
      border-radius: 16px;
      padding: 20px;
      box-shadow: 0 10px 32px rgba(0,0,0,0.65);
    }}
    .qr-stand-card {{
      border-color: var(--gold);
      text-align: center;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 12px;
      position: sticky;
      top: 18px;
    }}
    .stand-badge {{
      display: inline-block;
      padding: 4px 12px;
      border-radius: 20px;
      font-size: .72rem;
      font-weight: 800;
      letter-spacing: .08em;
      background: rgba(212, 168, 72, 0.18);
      color: var(--gold-lt);
      border: 1px solid rgba(212, 168, 72, 0.45);
    }}
    .qr-frame {{
      background: #fff;
      padding: 12px;
      border-radius: 16px;
      border: 4px solid var(--gold-lt);
      box-shadow: 0 0 28px rgba(212, 168, 72, 0.35);
      cursor: pointer;
      transition: transform .2s;
    }}
    .qr-frame:hover {{ transform: scale(1.03); }}
    .qr-frame img {{
      display: block;
      width: 240px;
      height: 240px;
    }}
    .qr-call {{
      font-size: 1.02rem;
      color: var(--gold-lt);
      font-weight: 800;
      line-height: 1.35;
    }}
    .qr-url-pill {{
      width: 100%;
      padding: 8px 10px;
      background: #120b07;
      border: 1px solid var(--border);
      border-radius: 8px;
      font-size: .76rem;
      color: var(--muted);
      word-break: break-all;
      font-family: monospace;
    }}
    .btn-block {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      width: 100%;
      padding: 12px 16px;
      border-radius: 10px;
      font-size: .92rem;
      font-weight: 800;
      text-decoration: none;
      cursor: pointer;
      border: 1px solid var(--border);
      background: #27190f;
      color: var(--ink);
      font-family: inherit;
      transition: all .2s;
    }}
    .btn-block:hover {{ border-color: var(--gold-lt); color: var(--gold-lt); }}
    .btn-block.gold {{
      background: linear-gradient(135deg, var(--gold-lt), #a37218);
      color: #120c07;
      border: none;
      font-size: 1rem;
      box-shadow: 0 4px 16px rgba(212, 168, 72, 0.35);
    }}
    /* Dashboard Sağ Sütun */
    .dashboard-col {{
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .stats-row {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
    }}
    @media (max-width: 680px) {{
      .stats-row {{ grid-template-columns: repeat(2, 1fr); }}
    }}
    .stat-card {{
      background: linear-gradient(145deg, #25180f, #170f09);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px 14px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}
    .stat-card .lbl {{ font-size: .68rem; color: var(--muted); letter-spacing: .06em; font-weight: 700; }}
    .stat-card .val {{ font-size: 1.55rem; font-weight: 900; color: var(--gold-lt); }}
    .stat-card .sub {{ font-size: .74rem; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .live-rooms-strip {{
      background: #17120d;
      border: 1px solid #3a5a40;
      border-radius: 12px;
      padding: 10px 14px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }}
    .live-dot {{
      width: 9px; height: 9px; border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 10px var(--green);
      display: inline-block;
    }}
    .live-pill {{
      background: #231911;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 4px 10px;
      font-size: .78rem;
      color: var(--ink);
    }}
    .podium-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
    }}
    @media (max-width: 640px) {{
      .podium-grid {{ grid-template-columns: 1fr; }}
    }}
    .podium-box {{
      background: linear-gradient(145deg, #2a1b10, #18100a);
      border: 1.5px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .podium-box.rank-1 {{ border-color: var(--gold-lt); box-shadow: 0 0 18px rgba(248, 213, 104, 0.2); }}
    .podium-medal {{ font-size: 1.9rem; }}
    .podium-info {{ flex: 1; min-width: 0; }}
    .podium-name {{ font-size: .95rem; font-weight: 800; color: #fff; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .podium-title {{ font-size: .70rem; color: var(--gold); }}
    .podium-lvl {{ font-size: 1.35rem; font-weight: 900; color: var(--gold-lt); }}
    .table-wrap {{
      overflow-x: auto;
      border: 1px solid var(--border);
      border-radius: 12px;
      background: #170f09;
    }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{
      text-align: left;
      padding: 11px 12px;
      font-size: .72rem;
      letter-spacing: .08em;
      color: var(--muted);
      background: #120b07;
      border-bottom: 1px solid var(--border);
    }}
    td {{
      padding: 10px 12px;
      border-bottom: 1px solid #26180f;
      font-size: .88rem;
    }}
    tr:last-child td {{ border-bottom: none; }}
    tr.top-row td {{ background: rgba(212, 168, 72, 0.06); }}
    .lvl-badge {{
      display: inline-block;
      padding: 3px 9px;
      border-radius: 8px;
      background: rgba(212, 168, 72, 0.18);
      border: 1px solid var(--gold);
      color: var(--gold-lt);
      font-weight: 900;
      font-size: .95rem;
    }}
    /* Tam Ekran QR & Künye Modalları */
    .modal-bg {{
      position: fixed;
      inset: 0;
      background: rgba(8, 5, 3, 0.92);
      backdrop-filter: blur(6px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 2000;
      padding: 18px;
    }}
    .modal-bg.open {{ display: flex; }}
    .modal-box {{
      background: #1d130c;
      border: 2px solid var(--gold-lt);
      border-radius: 20px;
      max-width: 580px;
      width: 100%;
      padding: 24px;
      text-align: center;
      box-shadow: 0 0 50px rgba(212, 168, 72, 0.35);
      max-height: 90vh;
      overflow-y: auto;
    }}
  </style>
</head>
<body>
  <div class="stand-shell">
    <header class="stand-topbar">
      <div class="brand-title">
        <h1>⚗️ Tabîb Ekmeleddin'in Kazanı (Bey Hekim)</h1>
        <p>13. Yüzyıl Selçuklu Dârüşşifası · ERÜ Anadolu Tıp Tarihi Kulübü Gürgen Ekibi</p>
      </div>
      <div class="topbar-actions">
        <button type="button" class="top-btn" id="openBigQrBtn">📱 Dev Stand QR Kodu</button>
        <a href="/download/tabib_ekmeleddin_kimdir.pdf" target="_blank" rel="noopener" class="top-btn">📜 Tabîb Ekmeleddin PDF</a>
        <button type="button" class="top-btn" id="openStandCreditsBtn">🏛️ Emeği Geçenler & Künye</button>
        <a href="/play" class="top-btn primary">▶ Bu Cihazda Hemen Oyna</a>
      </div>
    </header>

    <div class="stand-grid">
      <!-- Sol Sütun: Stand QR Kod & Katılım -->
      <aside class="card qr-stand-card">
        <span class="stand-badge">📱 STAND & TABLET SERGİ EKRANI</span>
        <div class="qr-frame" id="qrFrameClick" title="Tam ekran büyütmek için dokunun">
          <img src="/api/qr" alt="Oyuna Başlamak İçin QR Kodu Okutun">
        </div>
        <div class="qr-call">Kameranla QR Kodu Okut,<br>Telefonunda Hemen Oyna!</div>
        <p style="font-size: .80rem; color: var(--muted); line-height: 1.4;">
          İster <strong>Tek Kişilik Macera</strong> oyna ve adını skor tablosuna yazdır, ister arkadaşınla okutup <strong>1v1 Çırak Düellosu</strong> yap!
        </p>
        <div class="qr-url-pill" id="standPlayUrl">{html.escape(play_url)}</div>
        <button type="button" class="btn-block" id="openBigQrBtn2">🔍 QR Kodu Tam Ekran Büyüt</button>
        <a href="/play" class="btn-block gold">⚗️ Bu Tablette / Cihazda Oyna</a>
        <div style="display: flex; gap: 8px; width: 100%;">
          <a href="/download/tabib_ekmeleddin_kimdir.pdf" target="_blank" rel="noopener" class="btn-block" style="font-size: .78rem; padding: 10px;">📄 PDF'i Aç</a>
          <a href="/download/tabib_ekmeleddin_kimdir.pdf?download=1" class="btn-block" style="font-size: .78rem; padding: 10px;">📥 PDF İndir</a>
        </div>
        <a href="https://kulup.erciyes.edu.tr/uyelik/uyeol" target="_blank" rel="noopener" class="btn-block" style="font-size: .80rem; border-color: var(--gold); color: var(--gold-lt);">
          🏛️ ERÜ Anadolu Tıp Tarihi Kulübüne Üye Ol
        </a>
      </aside>

      <!-- Sağ Sütun: Tek Kişilik & Genel Canlı Oyuncu Skorları Dashboard'u -->
      <section class="dashboard-col">
        <div class="stats-row">
          <div class="stat-card">
            <span class="lbl">🏆 REKOR SEVİYE</span>
            <span class="val" id="statMaxLevel">--</span>
            <span class="sub" id="statChampion">Yükleniyor...</span>
          </div>
          <div class="stat-card">
            <span class="lbl">🔥 EN YÜKSEK KOMBO</span>
            <span class="val" id="statMaxCombo">--</span>
            <span class="sub">Kesintisiz İksir Serisi</span>
          </div>
          <div class="stat-card">
            <span class="lbl">📜 KAYITLI OYUNCU</span>
            <span class="val" id="statTotalScores">--</span>
            <span class="sub">Tamamlanan Derece</span>
          </div>
          <div class="stat-card">
            <span class="lbl">🟢 CANLI OYUNCU</span>
            <span class="val" id="statActivePlayers">0</span>
            <span class="sub" id="statActiveRooms">0 Aktif Oda</span>
          </div>
        </div>

        <div class="live-rooms-strip" id="liveRoomsStrip">
          <span class="live-dot"></span>
          <strong style="font-size: .80rem; color: var(--green);">Canlı Dârüşşifa Durumu:</strong>
          <span id="liveRoomsList" style="font-size: .80rem; color: var(--muted);">QR kodu okutan oyuncular burada canlı görünür.</span>
        </div>

        <div class="card" style="padding: 16px;">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
            <div>
              <h2 style="font-size: 1.15rem; color: var(--gold-lt);">🏆 Tek Kişilik Oyuncu Skorları & Şampiyonlar</h2>
              <span style="font-size: .75rem; color: var(--muted);">Canlı güncellenen Dârüşşifa liderlik panosu</span>
            </div>
            <span style="font-size: .72rem; color: var(--muted);" id="lastRefreshText">Canlı</span>
          </div>

          <div class="podium-grid" id="podiumGrid" style="margin-bottom: 14px;"></div>

          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>SIRA</th>
                  <th>HEKİM ADI & UNVANI</th>
                  <th>SEVİYE</th>
                  <th>EN YÜKSEK KOMBO</th>
                  <th>ODA</th>
                  <th>SAAT</th>
                </tr>
              </thead>
              <tbody id="scoresTableBody">
                <tr><td colspan="6" style="text-align:center; padding: 28px; color: var(--muted);">Skorlar yükleniyor...</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  </div>

  <!-- Tam Ekran Stand QR Modalı -->
  <div class="modal-bg" id="bigQrModal">
    <div class="modal-box">
      <span class="stand-badge">📱 TELEFONUNLA QR KODU OKUT VE OYNA</span>
      <h2 style="color: var(--gold-lt); margin: 10px 0 4px;">Tabîb Ekmeleddin'in Kazanı</h2>
      <p style="font-size: .86rem; color: var(--muted); margin-bottom: 14px;">Aynı Wi-Fi şartı yoktur · Tek Kişilik Macera veya 1v1 Düello</p>
      <div style="background:#fff; padding:16px; border-radius:20px; display:inline-block; border:5px solid var(--gold-lt);">
        <img src="/api/qr" alt="Stand QR Kod" style="width: min(340px, 72vw); height: min(340px, 72vw); display:block;">
      </div>
      <div class="qr-url-pill" style="margin-top: 14px; font-size: .88rem;" id="bigQrUrlText">{html.escape(play_url)}</div>
      <button type="button" class="btn-block gold" style="margin-top: 14px;" id="closeBigQrBtn">✕ Kapat</button>
    </div>
  </div>

  <!-- Stand Emeği Geçenler & Künye Modalı -->
  <div class="modal-bg" id="standCreditsModal">
    <div class="modal-box" style="text-align: left;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; border-bottom:1px solid var(--border); padding-bottom:8px;">
        <h2 style="color: var(--gold-lt); font-size: 1.15rem;">🏛️ Oyunda Emeği Geçenler & Kulüp Künyesi</h2>
        <button type="button" id="closeStandCreditsBtn" style="background:none; border:none; color:var(--muted); font-size:1.3rem; cursor:pointer;">✕</button>
      </div>
      <div style="display:flex; flex-direction:column; gap:10px; font-size:.86rem; line-height:1.55;">
        <div style="background:#140d08; border:1px solid var(--gold); border-radius:10px; padding:12px;">
          <strong style="color:var(--gold-lt); display:block; margin-bottom:4px;">💻 PROJE GELİŞTİRME KURULU (GÜRGEN EKİBİ)</strong>
          • <strong>Proje Yöneticisi:</strong> Tahsin Efe KARAKÖSE<br>
          • <strong>Web Sunucusu, Hosting, Debug:</strong> Ahmet Yasin MARŞİL<br>
          • <strong>Tasarım Destek:</strong> Mürsel Musa İLBASMIŞ, Baran PEKDOĞAN
        </div>
        <div style="background:#140d08; border:1px solid var(--border); border-radius:10px; padding:12px;">
          <strong style="color:var(--gold-lt); display:block; margin-bottom:4px;">👑 ANADOLU TIP TARİHİ KULÜBÜ YÖNETİM KURULU</strong>
          • <strong>Başkan:</strong> Mustafa Safa ŞENBAK<br>
          • <strong>Başkan Yardımcısı:</strong> Elif Sude BOSTANCI<br>
          • <strong>Akademik Başkan Yardımcısı:</strong> Tahsin Efe KARAKÖSE<br>
          • <strong>Faaliyet Sorumlusu:</strong> Banu Ece PÜSKÜLLÜOĞLU<br>
          • <strong>Eğitim Sorumlusu:</strong> Baran PEKDOĞAN<br>
          • <strong>Gürgen Grubu Yöneticisi:</strong> Ahmet Yasin MARŞİL<br>
          • <strong>Dergi Direktörü:</strong> Fatıma Zehra KARAKAYA
        </div>
        <div style="background:#140d08; border:1px solid var(--border); border-radius:10px; padding:12px;">
          <strong style="color:var(--gold-lt); display:block; margin-bottom:4px;">🌟 KATKI, SOSYAL MEDYA VE DENETİM EKİBİ</strong>
          • <strong>Katkı ve Destek:</strong> Mustafa Safa ŞENBAK, Yusuf Efe BAYRAKTAR, Muhammed Serhat TURSUN, Fatıma Zehra KARAKAYA<br>
          • <strong>Sosyal Medya Ekibi:</strong> Mina ALKAÇ, Muhammet Serhat TURSUN<br>
          • <strong>Denetleme Kurulu:</strong> Zişan ÇELİK, Nehir BÜYÜKDOĞAN
        </div>
        <div style="display:flex; gap:8px; margin-top:4px;">
          <a href="/download/tabib_ekmeleddin_kimdir.pdf" target="_blank" rel="noopener" class="btn-block" style="flex:1;">📜 Bey Hekim PDF Aç</a>
          <a href="https://kulup.erciyes.edu.tr/uyelik/uyeol" target="_blank" rel="noopener" class="btn-block gold" style="flex:1;">🏛️ Kulübe Üye Ol</a>
        </div>
      </div>
    </div>
  </div>

  <script>
    const bigQrModal = document.getElementById('bigQrModal');
    const standCreditsModal = document.getElementById('standCreditsModal');
    document.getElementById('openBigQrBtn').addEventListener('click', () => bigQrModal.classList.add('open'));
    document.getElementById('openBigQrBtn2').addEventListener('click', () => bigQrModal.classList.add('open'));
    document.getElementById('qrFrameClick').addEventListener('click', () => bigQrModal.classList.add('open'));
    document.getElementById('closeBigQrBtn').addEventListener('click', () => bigQrModal.classList.remove('open'));
    bigQrModal.addEventListener('click', (e) => {{ if (e.target === bigQrModal) bigQrModal.classList.remove('open'); }});

    document.getElementById('openStandCreditsBtn').addEventListener('click', () => standCreditsModal.classList.add('open'));
    document.getElementById('closeStandCreditsBtn').addEventListener('click', () => standCreditsModal.classList.remove('open'));
    standCreditsModal.addEventListener('click', (e) => {{ if (e.target === standCreditsModal) standCreditsModal.classList.remove('open'); }});

    function esc(s) {{
      const d = document.createElement('div');
      d.textContent = s || '';
      return d.innerHTML;
    }}

    async function refreshDashboard() {{
      try {{
        const res = await fetch('/api/dashboard');
        const data = await res.json();
        if (!data || !data.ok) return;

        document.getElementById('statMaxLevel').textContent = data.max_level ? String(data.max_level).padStart(2, '0') : '00';
        document.getElementById('statChampion').textContent = 'Şampiyon: ' + (data.champion_name || '—');
        document.getElementById('statMaxCombo').textContent = data.max_combo >= 2 ? ('🔥 x' + data.max_combo) : '—';
        document.getElementById('statTotalScores').textContent = data.total_scores || 0;
        document.getElementById('statActivePlayers').textContent = data.active_players_count || 0;
        document.getElementById('statActiveRooms').textContent = (data.active_rooms_count || 0) + ' Aktif Oda';

        if (data.play_url) {{
          document.getElementById('standPlayUrl').textContent = data.play_url;
          document.getElementById('bigQrUrlText').textContent = data.play_url;
        }}

        const liveRoomsList = document.getElementById('liveRoomsList');
        if (data.active_sessions && data.active_sessions.length > 0) {{
          liveRoomsList.innerHTML = data.active_sessions.map(s => {{
            const modeTag = s.mode === 'duel' ? '⚔️ 1v1' : '🧪 Tek';
            return `<span class="live-pill">${{modeTag}} <strong>${{esc(s.players.join(' vs '))}}</strong> · Sv.${{String(s.level).padStart(2, '0')}}</span>`;
          }}).join(' ');
        }} else {{
          liveRoomsList.textContent = 'Şu an aktif oda bekleniyor — QR kodu okutarak hemen katılın!';
        }}

        const scores = data.scores || [];
        const medals = ['🥇', '🥈', '🥉'];
        const podiumGrid = document.getElementById('podiumGrid');
        if (scores.length > 0) {{
          podiumGrid.innerHTML = scores.slice(0, 3).map((s, idx) => `
            <div class="podium-box rank-${{idx + 1}}">
              <div class="podium-medal">${{medals[idx]}}</div>
              <div class="podium-info">
                <div class="podium-name">${{esc(s.player_name)}}</div>
                <div class="podium-title">${{esc(s.title)}}</div>
              </div>
              <div class="podium-lvl">Sv.${{String(s.level).padStart(2, '0')}}</div>
            </div>
          `).join('');
        }} else {{
          podiumGrid.innerHTML = '';
        }}

        const tbody = document.getElementById('scoresTableBody');
        if (scores.length === 0) {{
          tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding: 32px; color: var(--muted);">Henüz skor kaydedilmedi. QR kodu okutup ilk rekoru sen kır!</td></tr>';
        }} else {{
          tbody.innerHTML = scores.map((s, idx) => `
            <tr class="${{idx < 3 ? 'top-row' : ''}}">
              <td style="font-size:1.1rem; font-weight:800;">${{idx < 3 ? medals[idx] : (s.rank + '.')}}</td>
              <td>
                <strong style="color:#fff; display:block;">${{esc(s.player_name)}}</strong>
                <small style="color:var(--gold); font-size:.72rem;">${{esc(s.title)}}</small>
              </td>
              <td><span class="lvl-badge">${{String(s.level).padStart(2, '0')}}</span></td>
              <td style="color:var(--gold-lt); font-weight:700;">${{s.max_combo >= 2 ? ('🔥 x' + s.max_combo) : '—'}}</td>
              <td style="color:var(--muted); font-size:.80rem;">${{esc(s.room_id)}}</td>
              <td style="color:var(--muted); font-size:.78rem;">${{esc(s.time_str)}}</td>
            </tr>
          `).join('');
        }}
        const now = new Date();
        document.getElementById('lastRefreshText').textContent = 'Son güncelleme: ' + now.toLocaleTimeString('tr-TR');
      }} catch (err) {{}}
    }}

    refreshDashboard();
    setInterval(refreshDashboard, 4000);
  </script>
</body>
</html>""")


@app.get("/play", response_class=HTMLResponse)
async def play_direct(request: Request, room: str = "") -> HTMLResponse:
    """QR kod okutulduğunda doğrudan telefon oyununu başlatır ve mod seçimi sunar."""
    clean_room = room.strip().upper()
    if clean_room and ROOM_ID_PATTERN.match(clean_room):
        get_or_create_room(clean_room)
    else:
        clean_room = ""
    return templates.TemplateResponse(
        request=request,
        name="play.html",
        context={"room_id": clean_room},
    )


@app.get("/play/{room_id}", response_class=HTMLResponse)
async def play(request: Request, room_id: str) -> HTMLResponse:
    clean_id = room_id.strip().upper()
    if not ROOM_ID_PATTERN.match(clean_id):
        return HTMLResponse(
            "<h1>Geçersiz Oda Kodu</h1><p>Oda kodu 3-12 karakter ve alfanümerik olmalıdır.</p>",
            status_code=400,
        )
    get_or_create_room(clean_id)
    return templates.TemplateResponse(
        request=request,
        name="play.html",
        context={"room_id": clean_id},
    )


@app.get("/razi_elements.json")
async def get_razi_elements():
    path = BASE_DIR / "razi_elements.json"
    if path.exists():
        return FileResponse(path, media_type="application/json")
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/download/tabib_ekmeleddin_kimdir.pdf")
@app.get("/download/beyhekim_kimdir.pdf")
async def download_ekmeleddin_pdf(download: int = 0):
    """Tabîb Ekmeleddin (Bey Hekim) Kimdir? tezhip süslemeli PDF'ini sunar."""
    path = BASE_DIR / "assets" / "tabib_ekmeleddin_kimdir.pdf"
    if not path.exists():
        try:
            from generate_pdf import build_pdf
            build_pdf()
        except Exception as e:
            log.error("PDF auto-generation error: %s", e)
    if path.exists():
        disposition = "attachment" if download else "inline"
        return FileResponse(
            path,
            media_type="application/pdf",
            filename="Tabib_Ekmeleddin_Bey_Hekim_Kimdir.pdf",
            content_disposition_type=disposition,
        )
    return JSONResponse({"error": "PDF bulunamadı"}, status_code=404)


# ── Liderlik Tablosu ──────────────────────────────────────────────────────────

@app.post("/api/scores")
async def post_score(request: Request) -> JSONResponse:
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    timestamps = [t for t in score_rate_tracker[client_ip] if now - t < 60.0]
    if len(timestamps) >= SCORE_POST_LIMIT_PER_MIN:
        return JSONResponse({"ok": False, "error": "Çok fazla skor isteği. Lütfen bekleyin."}, status_code=429)
    timestamps.append(now)
    score_rate_tracker[client_ip] = timestamps

    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            return JSONResponse({"ok": False, "error": "Geçersiz veri biçimi"}, status_code=400)

        level_raw = payload.get("level")
        if not isinstance(level_raw, int) or not (1 <= level_raw <= 100):
            return JSONResponse({"ok": False, "error": "Geçersiz seviye değeri (1-100)"}, status_code=400)
        level = level_raw

        room_raw = str(payload.get("room_id", "")).strip().upper()[:12]
        if room_raw and not ROOM_ID_PATTERN.match(room_raw):
            return JSONResponse({"ok": False, "error": "Geçersiz oda kodu formatı"}, status_code=400)
        room_id = room_raw

        player_name_raw = str(payload.get("player_name", "Simyacı")).strip()
        player_name = re.sub(r"[^\w\s\-çğıöşüÇĞİÖŞÜ]", "", player_name_raw)[:24].strip()
        if not player_name:
            player_name = "Simyacı"

        max_combo_raw = payload.get("max_combo", 0)
        max_combo = int(max_combo_raw) if isinstance(max_combo_raw, (int, float)) and 0 <= max_combo_raw <= 200 else 0

        ts = int(time.time())
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO scores (player_name, level, max_combo, room_id, ts) VALUES (?, ?, ?, ?, ?)",
                (player_name, level, max_combo, room_id, ts),
            )
            await db.commit()
        log.info("Score saved: player=%s level=%d combo=%d room=%s", player_name, level, max_combo, room_id)
        return JSONResponse({"ok": True})
    except Exception as e:
        log.error("Score save error: %s", e)
        return JSONResponse({"ok": False, "error": "Kayıt sırasında hata oluştu"}, status_code=400)


@app.get("/api/scores")
async def get_scores() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT player_name, level, max_combo, room_id, ts FROM scores ORDER BY level DESC, max_combo DESC, ts DESC LIMIT 50"
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


def get_alchemical_title(lvl: int) -> str:
    if lvl >= 100: return "İksir-i Âzam Üstadı 🌌"
    if lvl >= 75:  return "Şeyhü'l-Etıbbâ 👑"
    if lvl >= 50:  return "Büyük Hekim 📜"
    if lvl >= 25:  return "Usta Simyager ⚗️"
    if lvl >= 10:  return "Kalfa Tabip 🧪"
    return "Çırak Simyacı 🕯️"


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard() -> HTMLResponse:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT player_name, level, max_combo, room_id, ts FROM scores ORDER BY level DESC, max_combo DESC, ts DESC LIMIT 20"
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        total_cur = await db.execute("SELECT COUNT(*) FROM scores")
        total = (await total_cur.fetchone())[0]

    medals = ["🥇", "🥈", "🥉"]

    rows_html = ""
    for i, row in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        ts_str = time.strftime("%d.%m %H:%M", time.localtime(row["ts"]))

        safe_name = html.escape(str(row["player_name"] or "Simyacı"))
        safe_room = html.escape(str(row["room_id"] or "—"))
        safe_level = int(row["level"])
        safe_combo = int(row["max_combo"] or 0)
        title = get_alchemical_title(safe_level)

        combo_str = f"🔥 x{safe_combo}" if safe_combo >= 2 else "—"

        rows_html += f"""
        <tr class="{'top' if i < 3 else ''}">
          <td class="rank">{medal}</td>
          <td class="player"><strong>{safe_name}</strong><small>{title}</small></td>
          <td class="level">{safe_level:02d}</td>
          <td class="combo">{combo_str}</td>
          <td class="room">{safe_room}</td>
          <td class="time">{ts_str}</td>
        </tr>"""

    return HTMLResponse(f"""
<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="15">
  <title>Liderlik Tablosu — Tabîb Ekmeleddin'in Kazanı</title>
  <style>
    :root {{
      --bg:#110d0b; --panel:#211810; --border:#6a4628;
      --ink:#f0e4c8; --muted:#a09278; --gold:#d4a848;
      --green:#52b982; --red:#c84b3c;
    }}
    * {{ box-sizing:border-box; margin:0; padding:0; }}
    body {{
      min-height:100vh; background:var(--bg); color:var(--ink);
      font-family:Georgia,serif; padding:32px 16px;
    }}
    .container {{ max-width:720px; margin:0 auto; }}
    header {{ text-align:center; margin-bottom:32px; }}
    h1 {{ font-size:clamp(1.4rem,5vw,2rem); color:var(--gold); margin-bottom:6px; }}
    .subtitle {{ color:var(--muted); font-size:.9rem; }}
    .total {{ display:inline-block; margin-top:10px; font-size:.8rem;
              color:var(--muted); border:1px solid var(--border);
              padding:4px 12px; border-radius:20px; }}
    table {{
      width:100%; border-collapse:collapse;
      background:var(--panel); border:1px solid var(--border);
      border-radius:12px; overflow:hidden;
    }}
    th {{
      padding:12px 14px; text-align:left; font-size:.72rem;
      letter-spacing:.1em; color:var(--muted);
      border-bottom:1px solid var(--border);
      background:#1a100a;
    }}
    td {{ padding:12px 14px; border-bottom:1px solid #2a1a10; }}
    tr:last-child td {{ border-bottom:none; }}
    tr.top td {{ color:var(--gold); }}
    tr:hover td {{ background:#2a1810; }}
    .rank  {{ font-size:1.2rem; width:44px; }}
    .player strong {{ display:block; font-size:.92rem; color:var(--ink); }}
    .player small {{ display:block; font-size:.68rem; color:var(--gold); margin-top:1px; }}
    .level {{ font-size:1.5rem; font-weight:bold; width:64px; color:var(--gold); }}
    tr.top .level {{ color:#f5d060; text-shadow:0 0 12px #f5d06066; }}
    .combo {{ font-size:.82rem; color:var(--gold); font-weight:bold; }}
    .room  {{ color:var(--muted); font-size:.80rem; }}
    .time  {{ color:var(--muted); font-size:.75rem; white-space:nowrap; }}
    .empty {{ text-align:center; padding:48px; color:var(--muted); font-style:italic; }}
    .refresh {{ text-align:center; margin-top:16px; font-size:.75rem; color:var(--muted); }}
    a {{ color:var(--gold); text-decoration:none; }}
  </style>
</head>
<body>
<div class="container">
  <header>
    <h1>🏺 Liderlik Tablosu</h1>
    <div class="subtitle">Tabîb Ekmeleddin'in Kazanı (Bey Hekim)</div>
    <span class="total">{total} toplam oyun</span>
  </header>

  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>SİMYACI</th>
        <th>SEVİYE</th>
        <th>KOMBO</th>
        <th>ODA</th>
        <th>ZAMAN</th>
      </tr>
    </thead>
    <tbody>
      {'<tr><td colspan="6" class="empty">Henüz kayıt yok. İlk oyunu oyna!</td></tr>' if not rows else rows_html}
    </tbody>
  </table>

  <p class="refresh">
    Sayfa her 15 saniyede otomatik yenilenir · 
    <a href="/leaderboard">Şimdi yenile</a> · 
    <a href="/play">⚗️ Hemen Oyna</a> · 
    <a href="/">🏠 Ana Sayfa</a> · 
    <a href="/download/tabib_ekmeleddin_kimdir.pdf" download>📜 Tezhipli Risale (PDF)</a>
  </p>
</div>
</body>
</html>
""")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/{room_id}")
async def room_socket(websocket: WebSocket, room_id: str) -> None:
    clean_id = room_id.strip().upper()

    if not ROOM_ID_PATTERN.match(clean_id):
        await websocket.close(code=4000)
        return

    role = websocket.query_params.get("role", "mobile")
    req_mode = websocket.query_params.get("mode", "")
    if role not in ("desktop", "mobile"):
        await websocket.close(code=4000)
        return

    if clean_id not in rooms and len(rooms) >= MAX_ACTIVE_ROOMS:
        # Eski boş odaları temizle
        for rid, r_val in list(rooms.items()):
            if not r_val.get("players") and r_val.get("desktop") is None:
                eng = r_val.get("engine")
                if eng:
                    eng.stop()
                rooms.pop(rid, None)
        if len(rooms) >= MAX_ACTIVE_ROOMS:
            await websocket.close(code=4002)
            return

    room = get_or_create_room(clean_id)
    if req_mode in ("single", "duel"):
        room["mode"] = req_mode

    engine: ServerRoomEngine = room["engine"]
    await websocket.accept()

    if role == "desktop":
        old = room["desktop"]
        if isinstance(old, WebSocket):
            await safe_send(old, {"type": "error", "message": "Replaced by a new game session."})
        room["desktop"] = websocket
        log.info("Desktop connected — room %s", clean_id)
        players = room.get("players", {})
        player_summary = {pid: {"name": p["name"], "emblem": p["emblem"], "ready": p["ready"]} for pid, p in players.items()}
        await safe_send(websocket, {
            "type": "desktop_connected",
            "room_id": clean_id,
            "player_count": len(players),
            "players": player_summary,
            "mode": room.get("mode", "undecided"),
        })

    else:  # mobile
        players = room.setdefault("players", {})
        sockets = room.setdefault("sockets", {})
        room_mode = room.get("mode", "undecided")

        if room_mode == "single" and len(players) >= 1 and room.get("started", False):
            await safe_send(websocket, {
                "type": "error",
                "message": "Bu oda Tek Kişilik Mod olarak devam ediyor.",
            })
            await websocket.close(code=4003)
            return

        if "player_1" not in players:
            assigned_id = "player_1"
        elif "player_2" not in players:
            assigned_id = "player_2"
        else:
            await safe_send(websocket, {
                "type": "error",
                "message": "Bu oda dolu (Maksimum 2 çırak düellosu).",
            })
            await websocket.close(code=4001)
            return

        players[assigned_id] = {
            "ws": websocket,
            "name": f"Çırak {1 if assigned_id == 'player_1' else 2}",
            "emblem": "☿" if assigned_id == "player_1" else "🜍",
            "ready": False,
        }
        sockets[websocket] = assigned_id
        player_num = 1 if assigned_id == "player_1" else 2
        log.info("Mobile %s connected (mode=%s) — room %s", assigned_id, room_mode, clean_id)

        desktop = room.get("desktop")
        player_summary = {pid: {"name": p["name"], "emblem": p["emblem"], "ready": p["ready"]} for pid, p in players.items()}
        if isinstance(desktop, WebSocket):
            await safe_send(desktop, {
                "type": "player_connected",
                "player_id": assigned_id,
                "player_num": player_num,
                "player_count": len(players),
                "players": player_summary,
                "mode": room_mode,
            })

        await safe_send(websocket, {
            "type": "connected",
            "room_id": clean_id,
            "player_id": assigned_id,
            "player_num": player_num,
            "player_count": len(players),
            "players": player_summary,
            "mode": room_mode,
        })

        for other_id, other_p in players.items():
            if other_id != assigned_id and other_p.get("ws"):
                await safe_send(other_p["ws"], {
                    "type": "opponent_joined",
                    "player_id": assigned_id,
                    "player_num": player_num,
                    "player_count": len(players),
                    "players": player_summary,
                    "mode": room_mode,
                })

        await engine.on_player_connected(assigned_id)

    msg_timestamps: list[float] = []

    try:
        while True:
            try:
                message = await websocket.receive_json()
            except Exception:
                break

            if not isinstance(message, dict):
                continue

            now = time.monotonic()
            msg_timestamps = [t for t in msg_timestamps if now - t < 1.0]
            if len(msg_timestamps) >= MAX_MSG_RATE_PER_SEC:
                continue
            msg_timestamps.append(now)

            desktop = room.get("desktop")
            if role != "desktop":
                p_id = message.get("player_id") or room.get("sockets", {}).get(websocket, "player_1")
                msg_type = message.get("type")

                # 0. Telefondan Mod Seçimi (Tek Kişilik / 1v1 Düello)
                if msg_type == "select_mode":
                    sel_mode = "duel" if message.get("mode") == "duel" else "single"
                    await engine.on_mode_selected(sel_mode, p_id)

                # 1. Buton basımı
                elif message.get("button") is not None:
                    btn_str = str(message.get("button")).strip().lower()
                    if VALID_BUTTON_PATTERN.match(btn_str):
                        await engine.on_button(btn_str, p_id)
                        if isinstance(desktop, WebSocket):
                            await safe_send(desktop, {
                                "type": "button",
                                "player_id": p_id,
                                "button": btn_str,
                            })

                # 2. Başla butonu
                elif msg_type == "start_game":
                    await engine.on_start_game(p_id)
                    if isinstance(desktop, WebSocket):
                        await safe_send(desktop, {
                            "type": "start_game",
                            "player_id": p_id,
                        })

                # 3. Lobi isim/amblem güncellemesi
                elif msg_type == "join_lobby":
                    name_raw = str(message.get("name", "")).strip()
                    name = re.sub(r"[^\w\s\-çğıöşüÇĞİÖŞÜ]", "", name_raw)[:20].strip() or f"Çırak {1 if p_id == 'player_1' else 2}"
                    emblem = str(message.get("emblem", "☿"))[:4]
                    if p_id in room.get("players", {}):
                        room["players"][p_id]["name"] = name
                        room["players"][p_id]["emblem"] = emblem

                    player_summary = {pid: {"name": p["name"], "emblem": p["emblem"], "ready": p["ready"]} for pid, p in room["players"].items()}
                    if isinstance(desktop, WebSocket):
                        await safe_send(desktop, {
                            "type": "player_updated",
                            "player_id": p_id,
                            "name": name,
                            "emblem": emblem,
                            "players": player_summary,
                        })
                    for other_id, other_p in room["players"].items():
                        if other_id != p_id and other_p.get("ws"):
                            await safe_send(other_p["ws"], {
                                "type": "opponent_updated",
                                "player_id": p_id,
                                "name": name,
                                "emblem": emblem,
                                "players": player_summary,
                            })

                # 4. Hazır durumu
                elif msg_type == "player_ready":
                    ready_val = bool(message.get("ready", True))
                    if p_id in room.get("players", {}):
                        room["players"][p_id]["ready"] = ready_val

                    player_summary = {pid: {"name": p["name"], "emblem": p["emblem"], "ready": p["ready"]} for pid, p in room["players"].items()}
                    if isinstance(desktop, WebSocket):
                        await safe_send(desktop, {
                            "type": "player_ready",
                            "player_id": p_id,
                            "ready": ready_val,
                            "players": player_summary,
                        })
                    for other_id, other_p in room["players"].items():
                        if other_id != p_id and other_p.get("ws"):
                            await safe_send(other_p["ws"], {
                                "type": "opponent_ready",
                                "player_id": p_id,
                                "ready": ready_val,
                                "players": player_summary,
                            })
                    await engine.on_player_ready_changed()
            else:
                msg_type = message.get("type")
                if msg_type == "mode_set":
                    room["mode"] = message.get("mode", "single")
                    room["started"] = False
                    await broadcast_mobile(room, {
                        "type": "mode_changed",
                        "mode": room["mode"],
                    })
                elif msg_type == "mode_changed":
                    room["mode"] = message.get("mode", "single")
                    await broadcast_mobile(room, message)
                else:
                    if msg_type in ("round_started", "player_turn"):
                        room["started"] = True
                    elif msg_type in ("game_over", "duel_match_over", "duel_lobby_reset"):
                        room["started"] = False
                    await broadcast_mobile(room, message)

    except WebSocketDisconnect:
        pass
    finally:
        if role == "desktop":
            if room.get("desktop") is websocket:
                room["desktop"] = None
                log.info("Desktop disconnected — room %s", clean_id)
        else:
            p_id = room.get("sockets", {}).pop(websocket, None)
            if p_id and "players" in room:
                room["players"].pop(p_id, None)
            log.info("Mobile %s disconnected — room %s", p_id, clean_id)
            desktop = room.get("desktop")
            rem_players = room.get("players", {})
            player_summary = {pid: {"name": p["name"], "emblem": p["emblem"], "ready": p["ready"]} for pid, p in rem_players.items()}
            if isinstance(desktop, WebSocket):
                await safe_send(desktop, {
                    "type": "player_disconnected",
                    "player_id": p_id,
                    "player_count": len(rem_players),
                    "players": player_summary,
                })
            for rem_id, rem_p in rem_players.items():
                if rem_p.get("ws"):
                    await safe_send(rem_p["ws"], {
                        "type": "opponent_left",
                        "player_id": p_id,
                        "player_count": len(rem_players),
                        "players": player_summary,
                    })

        if room.get("desktop") is None and not room.get("players"):
            eng = room.get("engine")
            if eng:
                eng.stop()
            rooms.pop(clean_id, None)
            log.info("Room %s cleaned up", clean_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)
