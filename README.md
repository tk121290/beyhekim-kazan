# Bey Hekim'in Kazanı (Tabîb Ekmeleddin)

FastAPI sunucusu ile telefon kontrolcüsünü Pygame masaüstü oyununa bağlayan, 13. yüzyıl Selçuklu başhekimi ve Hz. Mevlânâ'nın tabibi **Tabîb Ekmeleddin (Bey Hekim)** temalı kadim tıp ve simya hafıza oyunu.

## Özellikler

- **Tek Kişilik Macera & 1v1 Çırak Düellosu:** İster tek kişilik 100 seviyeli kadim iksir yolculuğu, ister iki ayrı telefonla gerçek zamanlı hafıza düellosu!
- **Tabîb Ekmeleddin (Bey Hekim) Başlangıç Anlatımı (Prolog):** Oyun öncesinde Bey Hekim'in sesli/animasyonlu talimatları ve kadim Konya Dârüşşifası hikâyesi.
- **Tezhipli Selçuklu Risalesi (PDF):** Selçuklu turkuazı ve altın tezhip motifleriyle hazırlanmış "Tabîb Ekmeleddin (Bey Hekim) Kimdir?" bilgilendirme risalesi.
- **ERÜ Anadolu Tıp Tarihi Topluluğu Künyesi:** Topluluk kayıt, yönetim ekibi ve kadim tıp tarihi künye ekranı.
- **Mobil Web Kumandası:** Tarayıcı üzerinden sıfır kurulumla bağlanan antik parşömen temalı telefon kumandası ve dokunsal geri bildirimler (haptic feedback).

## Kurulum

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

## Çalıştırma

### 🌐 Seçenek A — İnternet Üzerinden Oynatma (Aynı WiFi Gerekmez - Önerilen)

Oyuncuların aynı WiFi ağına bağlanması gerekmez; 4.5G/5G mobil veri veya herhangi bir internet bağlantısıyla oynayabilirler:

```powershell
.\baslat_internetle.bat
```
*(Arka planda FastAPI sunucusunu ve ücretsiz, SSL sertifikalı Cloudflare tünelini başlatarak QR koduna küresel linki enjekte eder).*

---

### 🏠 Seçenek B — Yerel Ağda (Aynı WiFi) Çalıştırma

Bir terminalde:

```powershell
py -m uvicorn server:app --host 0.0.0.0 --port 8000
```

Başka bir terminalde:

```powershell
py desktop_game.py
```

Pygame penceresindeki QR kodu telefonla okut. Telefon ve masaüstü aynı WiFi ağında olmalıdır.


Pygame yerel IP adresini otomatik bulur ve QR koduna örneğin `http://192.168.1.25:8000/play/ABC-123` adresini koyar. Otomatik IP yanlış seçilirse PowerShell'de şu şekilde belirtebilirsin:

```powershell
$env:BEYHEKIM_HOST = "192.168.1.25"
py desktop_game.py
```

## Akış

- `MODE_SELECT`: Tek Kişilik veya 1v1 Çırak Düellosu mod seçimi.
- `WAITING_FOR_PLAYER`: Oda kodu ve QR kodu gösterilir.
- `PROLOGUE`: Tabîb Ekmeleddin talimatları aktarır; hem ekrandan hem telefondan "BAŞLA" tuşuna basılarak oyun başlatılır.
- `RHAZI_TURN` (Bey Hekim Sırası): Bey Hekim şifalı cevherleri sırayla kazana atar.
- `PLAYER_TURN`: Telefon butonları üzerinden aynı sıra kazana eklenir.
- `RESOLUTION`: Doğru dizi seviyeyi/raundu kazandırır; 3 can hakkı ve kombo sistemi mevcuttur.
- `CREDITS_VIEW`: Anadolu Tıp Tarihi Kulübü & Gürgen Ekibi film sonu kayan jenerik ekranı, kulüp üyeliği ve Tabîb Ekmeleddin tezhipli PDF risalesi.

---

## 🏛️ Projede Emeği Geçenler & Yönetim Kurulu

> **"ANADOLU TIP TARİHİ KULÜBÜNÜN GÜRGEN EKİBİ TARAFINDAN HAZIRLANMIŞTIR"**

### 💻 Projede Emeği Geçenler
- **Proje Yöneticisi:** Tahsin Efe KARAKÖSE
- **Web Sunucusu, Hosting & Debug:** Ahmet Yasin MARŞİL
- **Tasarım Destek:** Mürsel Musa İLBASMIŞ, Baran PEKDOĞAN
- **Teşekkür:** Mustafa Safa ŞENBAK, Yusuf Efe BAYRAKTAR, Muhammed Serhat TURSUN, Fatıma Zehra KARAKAYA

### 👑 Anadolu Tıp Yönetimi
- **Başkan:** Mustafa Safa ŞENBAK
- **Başkan Yardımcısı:** Elif Sude BOSTANCI
- **Akademik Başkan Yardımcısı:** Tahsin Efe KARAKÖSE
- **Faaliyet Sorumlusu:** Banu Ece PÜSKÜLLÜOĞLU
- **Eğitim Sorumlusu:** Baran PEKDOĞAN
- **Gürgen Grubu Yöneticisi:** Ahmet Yasin MARŞİL
- **Dergi Direktörü:** Fatıma Zehra KARAKAYA
- **Sosyal Medya Ekibi:** Mina ALKAÇ, Muhammet Serhat TURSUN
- **Denetleme Ekibi:** Zişan ÇELİK, Nehir BÜYÜKDOĞAN

📢 **Kulübümüze Üye Olmayı UNUTMAYIN!**  
👉 [kulup.erciyes.edu.tr/uyelik/uyeol](https://kulup.erciyes.edu.tr/uyelik/uyeol)

