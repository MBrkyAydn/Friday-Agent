<div align="center">

# 🤖 FRIDAY: Otonom Çoklu-Ajan (Multi-Agent) Yapay Zeka Geliştirici Ekosistemi

**Python 3.11+, AsyncIO ve reaktif olay tabanlı mimari ile geliştirilmiş, kurumsal düzeyde otonom yazılım geliştirici CLI ajanı ve dağıtık çoklu ajan ekosistemi.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Mimari](https://img.shields.io/badge/Mimari-Olay%20Tabanl%C4%B1%20%7C%20ReAct-orange.svg)](docs/superpowers/specs/2026-09-30-friday-cli-design.md)
[![Testler](https://img.shields.io/badge/Testler-120%2B%20Ge%C3%A7ti-brightgreen.svg?logo=pytest&logoColor=white)](Friday/tests/)
[![Lisans](https://img.shields.io/badge/Lisans-MIT-purple.svg)](LICENSE)
[![G%C3%BCvenlik](https://img.shields.io/badge/G%C3%BCvenlik-Workspace%20Jail%20%26%20Kademeli%20%C4%B0zinler-red.svg)](#g%C3%BCvenlik-ve-al%C4%B1%C5%9Fma-alan%C4%B1-izolasyonu-jail)

[🇬🇧 English](README.md) • [🇹🇷 Türkçe](README.tr.md)

</div>

---

## 📌 Yönetici Özeti

**FRIDAY**, gerçek dünya projelerinde kaynak kodları incelemek, hassas düzenlemeler yapmak, terminal komutları çalıştırmak, testleri yürütmek ve kendi hatalarını onarmak üzere tasarlanmış **terminal öncelikli otonom bir AI yazılım mühendisliği ajanıdır** (Claude Code benzeri bir mantıkla çalışır).

FRIDAY; asenkron bir **Reaktif Olay Veri Yolu (EventBus)**, akıl yürütme döngüsüne sahip **ReAct Lider Ajan**, katı **Çalışma Alanı İzolasyonu (Workspace Jail)**, **Özel Alt Ajan Havuzu (Researcher, Coder, Tester)** ve arka planda ağır görevleri yürüten bağımsız bir servis ajanı olan **JARVIS** ile birlikte çalışır.

Körü körüne kod üreten geleneksel yapay zeka script'lerinin aksine FRIDAY, **Zorunlu Doğrulama Sözleşmesi (Mandatory Verification Contract)** ile çalışır: *Derleme, sözdizimi ve otomatik testler başarıyla geçmeden hiçbir görev ASLA tamamlandı (`DONE`) ilan edilmez.* Testler başarısız olursa FRIDAY, gerilemeleri (regressions) çözmek için otonom bir **kendi kendini onarma (self-repair)** döngüsüne girer.

---

## 🏛️ Sistem Mimarisi

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Etkileşimli Terminal ve Web Arayüzü                   │
│     Prompt Toolkit REPL  │  Rich Akış Ekranı  │  FastAPI Canlı Dashboard    │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Asenkron Olaylar
┌──────────────────────────────────────▼──────────────────────────────────────┐
│                    Reaktif AsyncIO Olay Veri Yolu (EventBus)                 │
│         Yayınla/Abone Ol (Pub/Sub): Arayüzü, Ajanı ve I/O'yu Ayrıştırır     │
└──────┬───────────────────────┬───────────────────────────────┬──────────────┘
       │                       │                               │
┌──────▼──────────────┐ ┌──────▼────────────────┐    ┌─────────▼──────────────┐
│  ReAct Lider Ajan   │ │   Kademeli İzinler    │    │  İzole Araç Motoru     │
│  - Çoklu-LLM Router │ │  - Salt Okunur (T0)   │    │  - Workspace Guard     │
│  - Context Sıkıştırma│ │ - Güvenli Komut (T1) │    │  - Kabuk / AST Editör  │
│  - Durum Makinesi   │ │  - Tehlikeli / YOLO   │    │  - Kod Arama / Git     │
└──────┬──────────────┘ └───────────────────────┘    └─────────┬──────────────┘
       │                                                       │
       ├─────────────────────────────────┐                     │
┌──────▼───────────────────────┐ ┌────────▼────────────────────▼──────────────┐
│     Özel Alt Ajan Havuzu     │ │       Zorunlu Doğrulama Döngüsü            │
│  - Researcher (Salt okunur)  │ │   Hedef Proje Testlerini/Lint'i Koş        │
│  - Coder (Hassas kodlama)    │ │   Hata -> Kendi Kendini Onar (3 deneme)    │
│  - Tester (Pytest/Birim test)│ │   Çözülemezse -> BLOCKED Teşhis Raporu     │
└──────────────────────────────┘ └────────────────────────────────────────────┘
                                       │ Dosya Tabanlı IPC JSON
┌──────────────────────────────────────▼──────────────────────────────────────┐
│          Ajanlar Arası Ortak Veri Yolu Protokolü (D:\AI-Agents\Shared)      │
│     Posta Kutuları (IPC)  │   Dağıtık Durum Takibi   │  SQLite FTS5 Bellek  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
┌──────────────────────────────────────▼──────────────────────────────────────┐
│                     JARVIS İşçi Servisi (Arka Plan Daemon)                  │
│        Kendisine delege edilen ağır görevleri yürüten sessiz işçi ajan       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🌟 Temel İlkeler ve Mimari Özellikler

### 1. Zorunlu Doğrulama ve Otonom Kendi Kendini Onarma
* **Doğrulama Sözleşmesi:** FRIDAY bir LLM metin üretti diye kodun çalıştığını varsaymaz. Tüm kod değişikliklerinin ardından otomatik sözdizimi derlemesi (`compileall`), linter ve hedef projenin test suiteleri (`pytest`, `npm test` vb.) çalıştırılır.
* **Sınırlı Onarım Döngüsü:** Testler başarısız olursa, dönen hata izi (traceback) ve konsol çıktısı ajanın düşünce zincirine geri beslenir. Ajan **en fazla 3 deneme** boyunca hatayı kendi kendine düzeltmeye çalışır.
* **Garantili BLOCKED Durumu:** Hata çözülemezse, ajan asla "yaptım" diyerek halüsinasyon görmez; işlemi durdurur ve detaylı bir arıza raporu (`BLOCKED`) üretir.

### 2. Katı Çalışma Alanı İzolasyonu (Workspace Jail)
* FRIDAY, kendi kaynak kodunu üzerinde çalıştığı hedef projeden kesin olarak ayırır.
* Tüm dosya sistemi araçları (`view_file`, `write_file`, `replace_file_content`) ve terminal komutları (`run_command`), sadece kullanıcı tarafından belirtilen `target_dir` sınırları içerisinde yürütülür.
* Dizin aşma saldırıları (`../../`) veya işletim sisteminin kritik dizinlerine erişim denemeleri `WorkspaceGuard` tarafından yakalanır ve anında `SecurityError` fırlatılır.

### 3. Ajanlar Arası İletişim Protokolü (IPC Shared Bus)
* FRIDAY, arka planda çalışan bağımsız **JARVIS** işçi servisi ile işbirliği yapar.
* Ajanlar arası sinyalleşme, `Shared/mailboxes/` dizinindeki JSON tabanlı posta kutuları üzerinden tamamen asenkron olarak gerçekleştirilir.
* Ajanlar birbirlerinin kaynak kodlarına doğrudan yazamaz; tüm koordinasyon doğrulanmış mesaj zarfları ile sağlanır.

### 4. Çoklu-LLM Yönlendirici (Multi-LLM Router) ve Otomatik Yedekleme
* **LiteLLM** ve yerel **Ollama** motorlarını destekler.
* Yapılandırılabilir profiller:
  * **Gemini:** `gemini/gemini-2.5-flash`, `gemini/gemini-3.8-flash`
  * **Groq:** `groq/openai/gpt-oss-120b`, `llama-3.3-70b-versatile`
  * **Yerel Ollama:** %100 çevrimdışı ve gizli geliştirme için `ollama/deepseek-r1`, `qwen2.5-coder`.
* Hata Toleransı: Bir sağlayıcıda hız limiti (Rate Limit 429), sunucu hatası (503) veya context aşımı yaşandığında, yönlendirici kullanıcının işini bölmeden otomatik olarak bir sonraki modele geçiş yapar.

### 5. Context Bütçeleme ve Dinamik Sıkıştırma
* Büyük kod tabanlarında context penceresinin patlamasını önlemek için katı token limitleri uygular.
* Görev sırasında token eşiği aşıldığında, eski konuşma turları ve ara araç çıktıları otomatik olarak özetlenir (in-flight compaction).

### 6. İnsan Denetimi (Human-in-the-Loop) ve Çok Kanallı Gözlem
* **Telegram Bot Entegrasyonu:** Mobil cihazınızdan görev onaylama (`Onayla`, `Reddet`, `Her Zaman İzin Ver`, `YOLO Modu`), uzaktan komut gönderme ve işlem sonuç bildirimleri.
* **FastAPI + Vue Canlı İzleme Paneli:** Gerçek zamanlı WebSocket olay akışı, ajan durum monitörü, anlık profil değiştirme ve manuel görev atama.

---

## 📂 Depo Dizin Yapısı

```
AI-Agents/
├── Friday/                              # Ana FRIDAY CLI Paketi
│   ├── friday/
│   │   ├── agent/                       # ReAct Lider Ajan, LLM Sağlayıcı & Alt Ajanlar
│   │   ├── core/                        # EventBus, WorkspaceGuard, İzinler, Doğrulayıcı
│   │   ├── dashboard/                   # FastAPI Web İzleme Paneli & WebSocket
│   │   ├── telegram/                    # Telegram servisi, 4 seviyeli onay köprüsü
│   │   ├── tools/                       # İzole dosya, terminal, git ve arama araçları
│   │   └── ui/                          # Rich akış arayüzü & Prompt Toolkit REPL
│   ├── tests/                           # 120+ birim, entegrasyon ve uçtan uca test
│   ├── docs/superpowers/                # Mimari tasarım dokümanları & SDD planları
│   └── pyproject.toml                   # Python paket tanımları ve bağımlılıklar
│
├── Jarvis/                              # JARVIS Otonom Arka Plan Servisi
│   ├── jarvis/                          # IPC posta kutusu dinleyicisi & otonom coder motoru
│   ├── tests/                           # Daemon ve worker birim testleri
│   └── pyproject.toml
│
├── Shared/                              # Çoklu Ajan Koordinasyon Altyapısı
│   ├── mailboxes/                       # JSON IPC mesaj kuyrukları (friday_inbox, jarvis_inbox)
│   ├── state/                           # Daemon PID takibi ve görev bildirimleri
│   └── memory/                          # SQLite FTS5 kalıcı uzun süreli bellek
│
├── Logs/                                # Merkezi telemetri ve oturum logları (git-ignored)
├── .gitignore                           # Kapsamlı gizlilik ve güvenlik kuralları
├── README.md                            # Ana İngilizce Dokümantasyon
└── README.tr.md                         # Türkçe Dokümantasyon
```

---

## 🚀 Hızlı Başlangıç

### Gereksinimler
* **Python 3.11+**
* **Git**
* *(İsteğe bağlı)* Gemini / Groq API anahtarı veya çalışan yerel bir **Ollama** servisi.

### Kurulum

1. **Depoyu klonlayın:**
   ```bash
   git clone https://github.com/MBrkyAydn/Friday-Private.git
   cd Friday-Private
   ```

2. **FRIDAY paketini düzenlenebilir (editable) modda kurun:**
   ```bash
   cd Friday
   pip install -e .
   ```

3. **Kurulumu doğrulayın:**
   ```bash
   friday --version
   ```

---

## 💻 CLI Kullanımı ve Komutlar

### 1. Etkileşimli REPL Modu
Geçerli dizinde etkileşimli terminal geliştirici kabuğunu başlatın:
```bash
friday
```

Belirli bir hedef projeyi izole ederek çalıştırmak için:
```bash
friday --project-dir /path/to/target/project
```

### 2. Tek Komutla Görev Yürütme (One-Shot Task)
Terminalden doğrudan tek bir prompt ile kodlama veya refactoring başlatın:
```bash
friday -p "Kimlik doğrulama modülünü JWT kullanacak şekilde refactor et ve testleri çalıştır"
```

### 3. Model Profilini Değiştirme
LLM modelleri arasında dinamik olarak geçiş yapın:
```bash
# Terminalde veya REPL içinde:
friday use gemini
friday use groq
friday use local
```

### 4. Arka Plan Web Dashboard'unu Başlatma
Gerçek zamanlı web gözlem panelini ayağa kaldırın:
```bash
friday dashboard start --port 8000
# Tarayıcınızda http://localhost:8000 adresini açın
```

### 5. Telegram Uzaktan Komut Dinleyicisi
Mobil cihazınızdan onay vermek ve komut göndermek için dinleyiciyi başlatın:
```bash
friday telegram listen
```

---

## 🧪 Kapsamlı Test Paketi (TDD / SDD)

FRIDAY, **Test Odaklı Geliştirme (TDD)** ve **Spesifikasyon Odaklı Geliştirme (SDD)** disiplinleriyle inşa edilmiştir. Tüm sistem sınırlarını ve güvenlik katmanlarını test eden **120'den fazla otomatik test** içerir:

```bash
cd Friday
pytest -v
```

### Önemli Test Başlıkları:
* `test_workspace.py`: Dizin aşma (path traversal), yol temizleme ve sembolik bağ kaçış engellerini test eder.
* `test_verifier.py`: Otonom derleme kontrolü, sözdizimi doğrulaması ve 3 adımlı kendi kendini onarma döngüsünü sınar.
* `test_router.py`: Hız limitlerinde birincil LLM'den yedek LLM'e otomatik geçişi doğrular.
* `test_permissions.py`: Kademeli güvenlik seviyelerini ve kullanıcı onay mekanizmalarını test eder.
* `test_bus.py`: Asenkron olay dağıtımını ve gecikme izolasyonunu doğrular.

---

## 🔒 Güvenlik ve Çalışma Alanı İzolasyonu (Jail)

* **Sıfır Sabit Kodlanmış Anahtar (Zero Hardcoded Secrets):** Tüm kimlik bilgileri, API anahtarları ve bot tokenları yalnızca yerel `.env` dosyalarından veya ortam değişkenlerinden okunur.
* **Sıkı .gitignore Politikası:** Kök ve alt dizin `.gitignore` dosyaları ortam değişkenlerinin (`**/.env*`), çalışma zamanı loglarının (`Logs/`) ve geçici IPC dosyalarının kazara commit edilmesini engeller.
* **Sürekli Güvenlik Denetimi:** Depo genelinde **Gitleaks** ve **Security Audit** taramaları yapılarak tüm commit geçmişinin sızıntılardan arındırıldığı doğrulanmıştır.

---

## 📄 Lisans

Bu proje [MIT Lisansı](LICENSE) kapsamında lisanslanmıştır.
