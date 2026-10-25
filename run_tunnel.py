"""
Tabîb Ekmeleddin'in Kazanı — Cloudflare Tunnel Başlatıcı
Bu betik:
1. 'cloudflared' uygulamasını kontrol eder (yoksa resmi GitHub adresinden tek tuşla indirir).
2. FastAPI sunucusunu (server.py) yerel olarak başlatır ve hazır olmasını bekler.
3. Ücretsiz, SSL korumalı bir Cloudflare Tüneli açar (https://xxx.trycloudflare.com).
   - Pipe kilitlenmesini (deadlock) önlemek için arka plan okuma iş parçacığı ve --logfile kullanır.
   - UDP/QUIC engellemelerine takılmamak için --protocol http2 (gerekirse otomatik fallback) kullanır.
4. Tünel URL'sini yakalayarak oyunun QR koduna enjekte eder.
5. Pygame oyun penceresini (desktop_game.py) açar.
6. Oyun penceresi kapandığında sunucuyu ve tüneli arka planda temiz bir şekilde kapatır.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

# Windows Türkçe (cp1254) konsollarda UnicodeEncodeError çökmesini önle
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = Path(__file__).parent.resolve()
VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
PYTHON_BIN = str(VENV_PYTHON if VENV_PYTHON.exists() else sys.executable)
LOCAL_PORT = int(os.environ.get("PORT", "8000"))
LOG_FILE = BASE_DIR / "cloudflared.log"
CLOUDFLARED_DOWNLOAD_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
URL_PATTERN = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")


def find_or_download_cloudflared() -> str | None:
    local_binary = BASE_DIR / "cloudflared.exe"
    if local_binary.exists():
        return str(local_binary)

    system_path = shutil.which("cloudflared")
    if system_path:
        return system_path

    print("=" * 65)
    print("  [BİLGİ] 'cloudflared' (Cloudflare Tünel Motoru) bulunamadı.")
    print("  Oyunun aynı WiFi olmadan internetten oynanabilmesi için")
    print("  resmi Cloudflare yürütücüsü indiriliyor...")
    print("=" * 65)
    print(f"Kaynak: {CLOUDFLARED_DOWNLOAD_URL}")

    try:
        def _report(block_num: int, block_size: int, total_size: int) -> None:
            downloaded = block_num * block_size
            if total_size > 0:
                percent = min(100, int(downloaded * 100 / total_size))
                sys.stdout.write(f"\r  İlerleme: %{percent} ({downloaded // 1048576}MB / {total_size // 1048576}MB)")
                sys.stdout.flush()

        urllib.request.urlretrieve(CLOUDFLARED_DOWNLOAD_URL, str(local_binary), reporthook=_report)
        print("\n  [OK] 'cloudflared.exe' başarıyla indirildi ve hazırlandı!\n")
        return str(local_binary)
    except Exception as e:
        print(f"\n  [HATA] Otomatik indirme başarısız oldu: {e}")
        print("  Alternatif olarak PowerShell'de şu komutu çalıştırabilirsiniz:")
        print("  winget install --id Cloudflare.cloudflared -e")
        return None


def _is_local_server_alive() -> bool:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{LOCAL_PORT}/health", headers={"User-Agent": "BeyHekimLauncher"})
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            return resp.status == 200
    except Exception:
        return False


def _start_tunnel_attempt(cf_bin: str, protocol: str | None = "http2", timeout_sec: float = 18.0) -> tuple[subprocess.Popen | None, str | None]:
    try:
        LOG_FILE.write_text("", encoding="utf-8")
    except Exception:
        pass

    cmd = [
        cf_bin,
        "tunnel",
        "--url", f"http://127.0.0.1:{LOCAL_PORT}",
        "--logfile", str(LOG_FILE),
    ]
    if protocol:
        cmd.extend(["--protocol", protocol])

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

    found_url: list[str] = []

    def _drain_stdout() -> None:
        """Windows 4KB pipe tamponunun dolup cloudflared.exe'yi dondurmasını önler."""
        if not proc.stdout:
            return
        try:
            for line in proc.stdout:
                if not found_url:
                    m = URL_PATTERN.search(line)
                    if m:
                        found_url.append(m.group(0))
        except Exception:
            pass

    reader = threading.Thread(target=_drain_stdout, daemon=True)
    reader.start()

    start_time = time.time()
    while time.time() - start_time < timeout_sec:
        if found_url:
            return proc, found_url[0]
        if LOG_FILE.exists():
            try:
                content = LOG_FILE.read_text(encoding="utf-8", errors="ignore")
                m = URL_PATTERN.search(content)
                if m:
                    found_url.append(m.group(0))
                    return proc, m.group(0)
            except Exception:
                pass
        if proc.poll() is not None:
            break
        time.sleep(0.25)

    try:
        proc.terminate()
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    return None, None


def main() -> int:
    os.chdir(str(BASE_DIR))
    cf_bin = find_or_download_cloudflared()
    if not cf_bin:
        input("\nDevam etmek için Enter'a basın...")
        return 1

    print("\n" + "=" * 65)
    print("  * TABİB EKMELEDDİN'İN KAZANI - CLOUDFLARE İNTERNET YAYINI *")
    print("=" * 65)

    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUTF8"] = "1"
    child_env["RAZI_MANAGED_TUNNEL"] = "1"
    # Eski .env içindeki ölü tünel adreslerinin karışmasını önle
    child_env.pop("RAZI_PLAY_URL", None)

    # 1. FastAPI sunucusunu başlat (zaten açık değilse)
    server_proc: subprocess.Popen | None = None
    if _is_local_server_alive():
        print(f"[1/3] Oyun sunucusu zaten aktif (http://127.0.0.1:{LOCAL_PORT}).")
    else:
        print("[1/3] Oyun sunucusu (server.py) başlatılıyor...")
        server_proc = subprocess.Popen(
            [PYTHON_BIN, "server.py"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=child_env,
            cwd=str(BASE_DIR),
        )
        for _ in range(30):
            if _is_local_server_alive():
                break
            time.sleep(0.25)

    # 2. Cloudflare Tünelini başlat ve URL'yi yakala
    print("[2/3] Cloudflare güvenli tüneli kuruluyor (HTTP/2)...")
    tunnel_proc, public_url = _start_tunnel_attempt(cf_bin, protocol="http2", timeout_sec=16.0)
    if not public_url:
        print("      HTTP/2 yanıt vermedi, QUIC/otomatik protokol deneniyor...")
        tunnel_proc, public_url = _start_tunnel_attempt(cf_bin, protocol=None, timeout_sec=16.0)

    if not public_url or not tunnel_proc:
        print("[HATA] Cloudflare tünel URL'i alınamadı. İnternet bağlantınızı kontrol edin.")
        if server_proc:
            server_proc.terminate()
        return 1

    play_url = f"{public_url}/play"

    print("\n" + "+" + "-" * 63 + "+")
    print("|   İNTERNET YAYINI BAŞARIYLA AKTİF EDİLDİ!                     |")
    print("+" + "-" * 63 + "+")
    print(f"|  Telefon Linki : {play_url:<43} |")
    print("|  Ağ Kapsamı    : Tüm Dünya (4.5G / 5G / Farklı WiFi'lar)      |")
    print("|  Durum         : SSL Sertifikalı ve Güvenli (HTTPS/WSS)       |")
    print("+" + "-" * 63 + "+\n")

    # 3. Oyun ortam değişkenini ayarla ve oyunu başlat
    print("[3/3] Pygame oyun penceresi açılıyor...")
    child_env["RAZI_PLAY_URL"] = play_url

    try:
        subprocess.run([PYTHON_BIN, "desktop_game.py"], env=child_env, cwd=str(BASE_DIR))
    except KeyboardInterrupt:
        pass
    finally:
        print("\nOyun kapatıldı. Tünel ve yerel sunucu temizleniyor...")
        if tunnel_proc:
            try:
                tunnel_proc.terminate()
                tunnel_proc.wait(timeout=2)
            except Exception:
                try:
                    tunnel_proc.kill()
                except Exception:
                    pass

        if server_proc:
            try:
                server_proc.terminate()
                server_proc.wait(timeout=2)
            except Exception:
                try:
                    server_proc.kill()
                except Exception:
                    pass

        try:
            LOG_FILE.write_text("", encoding="utf-8")
        except Exception:
            pass

        print("[OK] Tüm süreçler güvenle sonlandırıldı.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
