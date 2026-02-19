# 🎮 Molty Royale — AI Agent Bot v3.0

Bot AI pintar untuk Molty Royale battle royale, siap dijalankan di Ubuntu cloud.  
Semua strategi mengikuti **SKILL.md** secara penuh.

---

## 📋 File Structure

```
molty_agent/
├── bot.py              ← Bot utama (semua logic ada di sini)
├── requirements.txt    ← Python dependencies
├── run.sh              ← Script setup & run otomatis
├── molty-bot.service   ← Systemd service (jalankan 24/7)
├── .env                ← Konfigurasi (dibuat otomatis)
└── logs/
    └── bot.log         ← Log file bot
```

---

## 🚀 Quick Start di Ubuntu Cloud

### Step 1 — Upload & Setup
```bash
# Upload semua file ke server
scp -r molty_agent/ ubuntu@YOUR_SERVER_IP:~/

# Masuk ke server
ssh ubuntu@YOUR_SERVER_IP

# Masuk ke folder bot
cd ~/molty_agent

# Jalankan setup script
chmod +x run.sh
bash run.sh
```

### Step 2 — Set API Key
```bash
nano .env
```
Isi:
```
MOLTY_API_KEY=key_kamu_disini
MOLTY_AGENT_NAME=NamaAgentKamu
```

### Step 3 — Jalankan Bot
```bash
bash run.sh
```

---

## ⚙️ Jalankan 24/7 dengan Systemd

```bash
# Copy service file
sudo cp molty-bot.service /etc/systemd/system/

# Edit path jika user bukan 'ubuntu'
sudo nano /etc/systemd/system/molty-bot.service

# Aktifkan dan jalankan
sudo systemctl daemon-reload
sudo systemctl enable molty-bot
sudo systemctl start molty-bot

# Cek status
sudo systemctl status molty-bot

# Lihat log real-time
sudo journalctl -u molty-bot -f
```

---

## 📊 Strategi Bot (dari SKILL.md)

### Global Priority Order
| Priority | Action |
|----------|--------|
| 1 ⚡ | **Zone Escape** — selalu keluar dari Death Zone |
| 2 💊 | **Heal kritis** — HP < 35% → heal dulu |
| 3 🔫 | **Weapon Hunt** — ambil senjata ≥15% lebih baik |
| 4 💊 | **Heal normal** — HP < 60% → heal |
| 5 🎯 | **Target Lock** — serang musuh jika win_prob ≥ 60% |
| 6 🗺 | **Explore** — region terbaik berdasarkan RVS |
| 7 📦 | **Loot** — ambil item di sekitar |
| 8 🔄 | **Patrol** — terus bergerak |

### Room Selection Rules
- ❌ Skip room PENUH (current == max)
- ❌ Skip PAID room jika balance kurang
- ✅ Pilih room dengan player paling banyak (kill potential lebih tinggi)

### Win Probability Formula
```
Win Prob = (My DPS × My HP × Position × Vision)
         / (Enemy DPS × Enemy HP × Distance Risk)

Engage jika: Win Prob ≥ 60% AND Enemy Escape Prob ≤ 40%
```

### Weapon Score Formula
```
Weapon Score = DPS × Accuracy × Range × Tier Multiplier

Tier Multipliers:
  Legendary = 3.0×
  Epic      = 2.2×
  Rare      = 1.5×
  Uncommon  = 1.2×
  Common    = 1.0×
```

### Region Value System (RVS)
Bot belajar mana region yang bagus:
```
Base RVS = 1.0

+0.3  high-tier weapon ditemukan
+0.2  berhasil kill
-0.3  2 explore gagal
-0.5  region jadi zone-prone
-0.2  kena ambush

Hindari region dengan RVS < 0.5
```

---

## 🔧 Konfigurasi (.env)

| Variable | Default | Keterangan |
|----------|---------|------------|
| `MOLTY_API_KEY` | - | **Wajib diisi** |
| `MOLTY_AGENT_NAME` | `ShadowStrike_v3` | Nama agent di game |
| `MOLTY_API_BASE` | `https://www.moltyroyale.com/api` | Base URL API |
| `TICK_INTERVAL` | `1.0` | Detik antar keputusan |
| `LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING |

---

## 🔌 Menyesuaikan API Endpoint

Jika endpoint game berbeda dari yang dipakai bot, edit bagian `MoltyClient` di `bot.py`:

```python
# Contoh — sesuaikan dengan docs resmi Molty Royale
async def list_rooms(self):
    return await self._req("GET", "/rooms")         # atau /v1/rooms, dll

async def get_state(self, match_id):
    return await self._req("GET", f"/game/{match_id}")  # sesuaikan

async def send_action(self, match_id, action):
    return await self._req("POST", f"/game/{match_id}/act", json=action)
```

Juga sesuaikan `StateParser.parse()` dengan field nama dari response API asli.

---

## 📝 Log Output

```
2026-02-19 10:00:01  [INFO    ]  🎮  MOLTY ROYALE BOT  |  Agent: ShadowStrike_v3
2026-02-19 10:00:02  [INFO    ]  [ROOM] 🔍 Scanning rooms...
2026-02-19 10:00:03  [INFO    ]  [ROOM] Selected 'room_42' — 9/10 players, type=free
2026-02-19 10:00:05  [INFO    ]  [WEAPON] Hunting M4A1 (score 28.6)
2026-02-19 10:00:06  [WARNING ]  [ZONE] ⚠ ESCAPE! dist=35m timer=5s hp=80%
2026-02-19 10:00:08  [INFO    ]  [COMBAT] Attacking enemy_07 (win_prob=74%, hp=45%)
2026-02-19 10:00:09  [INFO    ]  [KILL] 💀 +1 kill(s) | Match total: 3
```
