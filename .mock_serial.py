"""
_mock_serial.py - OBD-II Stres Testi Simülatörü (V107)
=====================================================
Aktif Senaryo: SUBAP KAÇAĞI / TEKLEYEN BENZİNLİ ARAÇ

Özellikler:
  [G1] Multi-ECU Yanıtı (7E8 + 7E9) - Insignia/GM çakışma testi
  [G2] Gerçekçi Sensör Dalgalanması (Jitter) - random.uniform ile
  [G3] Hata Enjeksiyonu - Her 15 sorguda BUSY/NO DATA
  [G4] Faz Geçişli Zaman Tüneli - KOEO→CRANKING→WARMUP→HOT→LOAD
  [G5] Protokol Simülasyonu - KWP (ATSP5) yavaş, CAN (ATSP6) hızlı

  [S1] FRP (0123) → Daima NO DATA  → Benzinli araç tespiti
  [S2] MAP → random.uniform(35,68) → Vakum dalgalanması (subap kaçağı)
  [S3] HOT RPM → random.uniform(710, 890) → Silindir güç kaybı (misfire)
  [S4] LTFT/STFT → %18-%24 pozitif trim → Bozuk hava/yakıt karışımı
  [S5] DTC 03 → P0300 her zaman aktif → Rastgele ateşleme hatası
"""

import time
import random

class MockSerial:
    """
    V107 - Profesyonel OBD-II Stres Testi Simülatörü
    motor.py ile %100 uyumlu. Tüm kenar vakaları test eder.
    """

    def __init__(self, port="COM_MOCK", baudrate=9600, timeout=1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.is_open = True

        # --- Simülasyon Durumu ---
        self._buffer = []           # (timestamp, byte) listesi
        self._locked_until = 0
        self.headers_active = True  # ATH1 varsayılan (motor.py ister)
        self.current_sim_header = "7DF"  # AT SH ile değişen, mode22/UDS session simülasyonu için
        self.sim_sessions = set()        # Hangi header'larda '1003' extended session açıldı (simülasyon amaçlı)
        self.start_time = time.time()

        # [G5] Protokol: "KWP" veya "CAN" (ATSP komutuyla değişir)
        self.protocol_mode = "KWP"
        self.protocol_set = False

        # [G3] Hata Enjeksiyonu Sayacı
        self._query_count = 0

        # Araç Sensör Verileri (Başlangıç KOEO)
        self.sim_data = {
            "RPM": 0, "ECT": 35, "SPEED": 0, "MAP": 101,
            "STFT": 0.0, "LTFT": 0.0, "TPS": 0.0, "LOAD": 0.0,
            "Voltaj": 12.6, "TIMING_ADV": 0.0, "MAF": 0.0,
            "IAT": 28, "O2_B1S1": 0.45, "O2_B1S2": 0.50,
            "FUEL_RAIL_PRESS": 0,
        }

        print(f"🔌 MOCK SİMÜLATÖR V107 BAŞLATILDI | Port: {port} | Stres Testi Aktif")
        print(f"   [G1] Multi-ECU (7E8+7E9) | [G2] Jitter | [G3] BUSY/NO DATA | [G4] Faz Tüneli | [G5] KWP/CAN")

    # -----------------------------------------------------------------
    # DÜŞÜK SEVİYE INTERFACE (motor.py uyumu)
    # -----------------------------------------------------------------

    @property
    def in_waiting(self):
        if not self.is_open:
            return 0
        now = time.time()
        return sum(1 for t, _ in self._buffer if t <= now)

    def write(self, data):
        if not self.is_open:
            return 0
        if time.time() < self._locked_until:
            return len(data)
        try:
            cmd = data.decode('ascii', errors='ignore').strip().upper()
        except Exception:
            return len(data)
        self._process_command(cmd)
        return len(data)

    def read(self, size=1):
        if not self.is_open:
            return b""
        if time.time() < self._locked_until:
            return b""
        now = time.time()
        result = b""
        new_buffer = []
        taken = 0
        for t, b in self._buffer:
            if t <= now and taken < size:
                result += b
                taken += 1
            else:
                new_buffer.append((t, b))
        self._buffer = new_buffer
        return result

    def flush(self):
        pass  # motor.py flush çağırır ama buffer temizlemeyelim

    def reset_input_buffer(self):
        self._buffer = []

    def close(self):
        self.is_open = False
        print("🔌 MOCK SİMÜLATÖR KAPATILDI")

    # -----------------------------------------------------------------
    # [G5] GECİKME HESABI - Protokole Göre
    # -----------------------------------------------------------------

    def _get_delay(self, base_delay=0.0):
        """KWP için ağır gecikme, CAN için milisaniyeler."""
        if self.protocol_mode == "CAN":
            return base_delay + random.uniform(0.005, 0.020)  # 5-20ms
        else:  # KWP
            return base_delay + random.uniform(0.15, 0.40)   # 150-400ms

    def _schedule_response(self, text, start_delay=0.0):
        """Byte-by-byte zamanlı gönderim simülasyonu."""
        # [G5] KWP çok yavaş, CAN çok hızlı
        if self.protocol_mode == "CAN":
            byte_delay = 0.001
        else:
            byte_delay = 0.008  # K-Line: 10.4kbps ~= 1 char/ms ama simülasyon için 8ms

        now = time.time() + start_delay
        for char in text:
            self._buffer.append((now, char.encode('ascii')))
            now += byte_delay
        # Satır sonu (CR) - motor.py bunu bekler
        self._buffer.append((now + byte_delay, b'\r'))

    # -----------------------------------------------------------------
    # [G4] ZAMANa BAĞLI SENARYO GÜNCELLEMESİ
    # -----------------------------------------------------------------

    def _update_scenario(self):
        """
        [G4] Faz Geçişli Zaman Tüneli:
          0-5s   → KOEO   (kontak açık, motor dönmüyor)
          5-8s   → CRANKING (düşük voltaj, düşük RPM)
          8-20s  → WARMUP  (rölantiyle ısınma)
          20-35s → HOT     (tam ısınmış, rölanti)
          35s+   → LOAD    (gaz veriliyor, hızlanma)
        """
        elapsed = time.time() - self.start_time

        if elapsed < 5:
            # KOEO: Motor çalışmıyor
            self.sim_data["RPM"]     = 0
            self.sim_data["Voltaj"]  = round(12.6 + random.uniform(-0.05, 0.05), 2)  # [G2]
            self.sim_data["TPS"]     = 0.0
            self.sim_data["LOAD"]    = 0.0
            self.sim_data["MAP"]     = 101
            self.sim_data["ECT"]     = 35 + random.uniform(-0.3, 0.3)  # [G2]
            self.sim_data["MAF"]     = 0.0
            self.sim_data["FUEL_RAIL_PRESS"] = 0

        elif elapsed < 8:
            # CRANKING: Marş çekiliyor
            self.sim_data["RPM"]     = random.randint(180, 350)
            self.sim_data["Voltaj"]  = round(9.2 + random.uniform(-0.3, 0.3), 2)  # [G2] Voltaj düşük
            self.sim_data["MAP"]     = random.randint(85, 95)
            self.sim_data["TPS"]     = random.uniform(0, 5)
            self.sim_data["LOAD"]    = random.uniform(5, 20)
            self.sim_data["MAF"]     = 0.0
            self.sim_data["FUEL_RAIL_PRESS"] = 250

        elif elapsed < 20:
            # WARMUP: Motor çalışıyor, ısınıyor
            warmup_t = elapsed - 8  # 0..12
            self.sim_data["Voltaj"] = round(14.2 + random.uniform(-0.1, 0.1), 2)  # [G2]

            # [G2] RPM Jitter: 1200'den 800'e düşerken rastgele titre
            base_rpm = 1200 - warmup_t * 30
            if base_rpm < 800:
                base_rpm = 800
            self.sim_data["RPM"]    = int(base_rpm + random.uniform(-8, 8))  # [G2] ±8 RPM jitter

            # ECT: 35'ten 80'e tırmanış
            self.sim_data["ECT"]    = round(35 + warmup_t * 3.7 + random.uniform(-0.5, 0.5), 1)  # [G2]
            self.sim_data["MAP"]    = int(random.uniform(35, 68))              # [S2] Vakum delisi
            self.sim_data["STFT"]   = round(random.uniform(18.0, 24.0), 1)     # [S4] Yüksek pozitif trim
            self.sim_data["LTFT"]   = round(random.uniform(18.0, 24.0), 1)     # [S4] Yüksek pozitif trim
            self.sim_data["MAF"]    = round(3.8 + random.uniform(-0.3, 0.3), 2)  # [G2]
            self.sim_data["FUEL_RAIL_PRESS"] = 0  # [S1] Benzinli → FRP yok

        elif elapsed < 35:
            # HOT: Tam sıcaklık, rölanti
            self.sim_data["Voltaj"] = round(14.1 + random.uniform(-0.05, 0.05), 2)  # [G2]
            self.sim_data["RPM"]    = int(random.uniform(710, 890))             # [S3] Misfire vibrasyonu
            self.sim_data["ECT"]    = round(88 + random.uniform(-1.5, 1.5), 1)  # [G2]
            self.sim_data["TPS"]    = round(random.uniform(0, 3), 1)
            self.sim_data["LOAD"]   = round(random.uniform(15, 25), 1)
            self.sim_data["STFT"]   = round(random.uniform(18.0, 24.0), 1)     # [S4] Yüksek pozitif trim
            self.sim_data["LTFT"]   = round(random.uniform(18.0, 24.0), 1)     # [S4] Yüksek pozitif trim
            self.sim_data["MAP"]    = int(random.uniform(35, 68))              # [S2] Vakum dalgalanması
            self.sim_data["MAF"]    = round(4.2 + random.uniform(-0.2, 0.2), 2)  # [G2]
            self.sim_data["FUEL_RAIL_PRESS"] = 0  # [S1] Benzinli → FRP yok

        else:
            # LOAD / DYNO: Gaz verildi, hızlanma
            load_t = elapsed - 35
            self.sim_data["Voltaj"] = round(14.0 + random.uniform(-0.1, 0.1), 2)
            self.sim_data["TPS"]    = min(95.0, 75.0 + load_t * 0.5)
            self.sim_data["LOAD"]   = min(98.0, 80.0 + load_t * 0.8)
            self.sim_data["RPM"]    = int(min(6200, 2000 + load_t * 200) + random.uniform(-20, 20))
            self.sim_data["SPEED"]  = int(min(180, 30 + load_t * 3))
            self.sim_data["ECT"]    = round(92 + random.uniform(-1, 1), 1)
            self.sim_data["STFT"]   = round(random.uniform(-12, 12), 1)
            self.sim_data["LTFT"]   = round(5 + random.uniform(-2, 2), 1)
            self.sim_data["MAP"]    = int(90 + random.uniform(-5, 5))
            self.sim_data["MAF"]    = round(30.0 + (self.sim_data["RPM"] / 1000) * 5 + random.uniform(-1, 1), 2)
            self.sim_data["FUEL_RAIL_PRESS"] = 12000 + random.randint(-200, 200)

    # -----------------------------------------------------------------
    # KOMUT İŞLEYİCİ
    # -----------------------------------------------------------------

    def _process_command(self, cmd):
        clean = cmd.replace(" ", "")

        # =============================================================
        # AT KOMUTLARI
        # =============================================================
        if clean == "ATZ":
            self._schedule_response("ELM327 v1.5", 0.3)
            self._schedule_response(">",           0.35)
            return

        if clean in ("ATE0", "ATE1", "ATS0", "ATL0", "ATAT1", "ATAT2"):
            self._schedule_response("OK", self._get_delay(0.05))
            self._schedule_response(">",  self._get_delay(0.1))
            return

        if clean == "ATH1":
            self.headers_active = True
            self._schedule_response("OK", self._get_delay(0.05))
            self._schedule_response(">",  self._get_delay(0.1))
            return

        if clean == "ATH0":
            self.headers_active = False
            self._schedule_response("OK", self._get_delay(0.05))
            self._schedule_response(">",  self._get_delay(0.1))
            return

        if clean == "ATDP":
            if self.protocol_mode == "CAN":
                self._schedule_response("ISO 15765-4 CAN (11 bit, 500K)", self._get_delay(0.1))
            else:
                self._schedule_response("ISO 14230-4 KWP (5 baud)",       self._get_delay(0.1))
            self._schedule_response(">", self._get_delay(0.15))
            return

        if clean == "ATRV":
            self._update_scenario()
            self._schedule_response(f"{self.sim_data['Voltaj']:.1f}V", self._get_delay(0.05))
            self._schedule_response(">", self._get_delay(0.1))
            return

        if clean.startswith("ATSH"):
            self.current_sim_header = clean[4:].upper()
            self._schedule_response("OK", self._get_delay(0.05))
            self._schedule_response(">",  self._get_delay(0.1))
            return

        if clean.startswith("ATST"):
            # Timeout ayarı - kabul et, sessiz geç
            self._schedule_response("OK", self._get_delay(0.05))
            self._schedule_response(">",  self._get_delay(0.1))
            return

        # [G5] PROTOKOL SEÇİMİ
        if clean.startswith("ATSP"):
            self.protocol_set = True
            proto_char = clean[4:] if len(clean) > 4 else "0"
            if proto_char in ("6", "7", "8", "9", "A"):   # CAN ailesı
                self.protocol_mode = "CAN"
                print(f"   🚀 (MOCK) Protokol: CAN → Hızlı Mod (ms yanıtlar)")
            elif proto_char in ("4", "5"):                 # KWP ailesi
                self.protocol_mode = "KWP"
                print(f"   🐢 (MOCK) Protokol: KWP → Yavaş Mod (150-400ms yanıtlar)")
            else:
                self.protocol_mode = "KWP"                # Bilinmiyor → KWP
            self._schedule_response("OK", self._get_delay(0.05))
            self._schedule_response(">",  self._get_delay(0.1))
            return

        if clean == "ATRESET_SIM":
            self.start_time = time.time()
            self._query_count = 0
            print("🔄 (MOCK) Simülasyon süresi ve sayaçlar sıfırlandı!")
            self._schedule_response("OK", 0.1)
            self._schedule_response(">",  0.15)
            return

        # =============================================================
        # [G1] PID TARAMA BLOKLARI (0100, 0120, 0140, 0160, 0180, 01A0)
        # =============================================================
        if clean in ("0100", "0120", "0140", "0160", "0180", "01A0"):
            if not self.protocol_set:
                self._schedule_response("UNABLE TO CONNECT", 0.5)
                self._schedule_response(">", 0.6)
                return

            block = clean  # "0100", "0120" vb.
            d = self._get_delay(0.1)

            if block == "0100":
                if self.protocol_mode == "CAN":
                    # [G1] Multi-ECU: 7E8 (zengin) + 7E9 (kısıtlı) - Insignia/GM testi
                    # 7E8: BE1FB811  → Motor ECU - zengin PID seti
                    # 7E9: 80000000  → Şanzıman ECU - sadece 010D (speed)
                    print("   🔀 (MOCK) Multi-ECU yanıtı üretiliyor (7E8=ECM, 7E9=TCM)")
                    self._schedule_response("7E8 06 41 00 BE 1F B8 11", d)
                    self._schedule_response("7E9 06 41 00 80 00 00 00", d + 0.005)
                else:
                    # KWP: Tek ECU (Aveo tarzı)
                    self._schedule_response("BUS INIT: OK", 0.05)
                    self._schedule_response("41 00 BE 1F B8 11", d)

            elif block == "0120":
                # PID 0x21-0x40: Yakıt ve egzos sensörleri
                self._schedule_response("7E8 06 41 20 80 01 81 00", d)

            elif block == "0140":
                # PID 0x41-0x60: O2, katalitik, EGR
                self._schedule_response("7E8 06 41 40 44 00 00 10", d)

            else:
                # Diğer bloklar: NO DATA (ECU bunları desteklemiyor)
                self._schedule_response("NO DATA", d)

            self._schedule_response(">", d + 0.02)
            return

        # =============================================================
        # DTC SORGULAMA (03)
        # =============================================================
        if clean == "03":
            d = self._get_delay(0.1)
            # [S5] P0300 (Rastgele Ateşleme Hatası) HER ZAMAN aktif
            # 43 01 03 00 = P0300 (Random/Multiple Misfire Detected)
            self._schedule_response("43 01 03 00 00 00 00", d)
            self._schedule_response(">", d + 0.01)
            return

        # =============================================================
        # OBD PID SORGULARI (01xx)
        # =============================================================
        if clean.startswith("01") and len(clean) >= 4:
            self._query_count += 1
            self._update_scenario()

            pid = clean[2:4]
            d   = self._get_delay(0.05)

            # [G3] HATA ENJEKSİYONU: Her 15 sorguda bir hata
            if self._query_count % 15 == 0:
                hata_turu = random.choice(["BUSY", "NO DATA", "NO DATA"])
                pid_str = f"01{pid}"
                print(f"   💥 (MOCK) Hata Enjeksiyonu → [{pid_str}] → {hata_turu} (sorgu #{self._query_count})")
                self._schedule_response(hata_turu, d)
                self._schedule_response(">", d + 0.01)
                return

            # Normal PID yanıtları
            resp = self._build_pid_response(pid)

            # [G1] CAN modunda header ekle
            if self.protocol_mode == "CAN":
                self._schedule_response(f"7E8 {resp}", d)
            else:
                self._schedule_response(resp, d)

            self._schedule_response(">", d + 0.01)
            return

        # =============================================================
        # VIN SORGULAMA (0902)
        # =============================================================
        if clean == "0902":
            d = self._get_delay(0.1)
            self._schedule_response("49 02 01 57 30 4C 30 30 30", d)
            self._schedule_response("49 02 02 30 30 30 30 30 30", d + 0.01)
            self._schedule_response("49 02 03 30 30 30 30 30 30", d + 0.02)
            self._schedule_response(">", d + 0.03)
            return

        # =============================================================
        # UDS / MODE 22 SİMÜLASYONU (V202 test desteği)
        # =============================================================
        if clean == "1003":
            self.sim_sessions.add(self.current_sim_header)
            self._schedule_response("5003", self._get_delay(0.1))
            self._schedule_response(">",    self._get_delay(0.15))
            return

        if clean == "3E00":
            if self.current_sim_header in self.sim_sessions:
                self._schedule_response("7E00", self._get_delay(0.05))
            else:
                self._schedule_response("7F3E10", self._get_delay(0.05))  # general reject, session yok
            self._schedule_response(">", self._get_delay(0.1))
            return

        if clean.startswith("22") and len(clean) >= 6:
            did = clean[2:6]
            if self.current_sim_header not in self.sim_sessions:
                self._schedule_response(f"7F2222", self._get_delay(0.1))  # conditions not correct: session açık değil
            elif did == "1640":
                # Örnek: mevcut CSV'lerde geçen bir DID'e sahte ama tutarlı bir pozitif cevap
                self._schedule_response(f"6216400096", self._get_delay(0.15))
            elif did == "1940":
                # DID Mismatch testi için bozuk/başta olmayan DID yanıtı
                self._schedule_response(f"AA6219400096", self._get_delay(0.15))
            else:
                self._schedule_response(f"7F2231", self._get_delay(0.1))  # request out of range: bilinmeyen DID
            self._schedule_response(">", self._get_delay(0.15))
            return

        # =============================================================
        # BİLİNMEYEN KOMUT
        # =============================================================
        self._schedule_response("?", self._get_delay(0.05))
        self._schedule_response(">", self._get_delay(0.1))

    # -----------------------------------------------------------------
    # PID YANIT ÜRETECİ
    # -----------------------------------------------------------------

    def _build_pid_response(self, pid: str) -> str:
        """
        OBD-II PID için doğru formatlı HEX yanıtı üretir.
        Tüm formüller OBD-II standardına (%100 uyumlu) göre hesaplanır.
        """
        d = self.sim_data

        if pid == "0C":  # RPM: (A*256+B)/4
            val = int(d["RPM"] * 4)
            return f"41 0C {val >> 8:02X} {val & 0xFF:02X}"

        if pid == "0D":  # Hız: A km/h
            return f"41 0D {int(d['SPEED']):02X}"

        if pid == "05":  # ECT: A-40 °C
            return f"41 05 {int(d['ECT'] + 40):02X}"

        if pid == "0B":  # MAP: A kPa
            return f"41 0B {int(d['MAP']):02X}"

        if pid == "11":  # TPS: A*100/255 %
            val = int(d["TPS"] * 2.55)
            return f"41 11 {val:02X}"

        if pid == "04":  # LOAD: A*100/255 %
            val = int(d["LOAD"] * 2.55)
            return f"41 04 {val:02X}"

        if pid == "06":  # STFT: (A-128)*100/128 %
            val = int(d["STFT"] * 1.28 + 128)
            return f"41 06 {max(0, min(255, val)):02X}"

        if pid == "07":  # LTFT
            val = int(d["LTFT"] * 1.28 + 128)
            return f"41 07 {max(0, min(255, val)):02X}"

        if pid == "0E":  # Timing Adv: (A/2)-64 °
            val = int((d["TIMING_ADV"] + 64) * 2)
            return f"41 0E {max(0, min(255, val)):02X}"

        if pid == "0F":  # IAT: A-40 °C
            return f"41 0F {int(d['IAT'] + 40):02X}"

        if pid == "10":  # MAF: (A*256+B)/100 g/s
            val = int(d["MAF"] * 100)
            return f"41 10 {val >> 8:02X} {val & 0xFF:02X}"

        if pid == "01":  # MIL + DTC sayısı
            elapsed = time.time() - self.start_time
            # 30. saniyeden sonra MIL yanar (2 DTC)
            mil_byte = 0x82 if elapsed > 30 else 0x00
            return f"41 01 {mil_byte:02X} 00 00 00"

        if pid == "14":  # O2 B1S1: A*0.005 V
            val = int(d["O2_B1S1"] * 200)
            return f"41 14 {val:02X} FF"

        if pid == "15":  # O2 B1S2
            val = int(d["O2_B1S2"] * 200)
            return f"41 15 {val:02X} FF"

        if pid == "23":  # Fuel Rail Pressure → [S1] Benzinli araç: FRP yok
            return "NO DATA"

        if pid == "1F":  # Çalışma Süresi: A*256+B saniye
            elapsed_s = int(max(0, time.time() - self.start_time))
            return f"41 1F {elapsed_s >> 8:02X} {elapsed_s & 0xFF:02X}"

        if pid == "2C":  # EGR Command: A*100/255 %
            val = int(35 * 2.55)  # %35 EGR
            return f"41 2C {val:02X}"

        if pid == "2D":  # EGR Error: (A-128)*100/128 %
            return f"41 2D {128:02X}"  # 0% hata

        if pid == "42":  # Modül Voltajı: (A*256+B)/1000 V
            val = int(d["Voltaj"] * 1000)
            return f"41 42 {val >> 8:02X} {val & 0xFF:02X}"

        if pid == "46":  # Dış Sıcaklık: A-40 °C
            return f"41 46 {int(28 + 40):02X}"

        if pid == "5C":  # Yağ Sıcaklığı: A-40 °C
            oil_t = min(d["ECT"] + 10, 120)
            return f"41 5C {int(oil_t + 40):02X}"

        # Bilinmeyen/desteklenmeyen PID → 00 ile doldur
        return f"41 {pid} 00"
