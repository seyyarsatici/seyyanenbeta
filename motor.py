import serial
from serial.tools import list_ports
import time
import logging
import re
import csv
import os
import ast
import operator
import sys
from pathlib import Path
import dashboard as Dashboard
import threading
import queue
from collections import deque

# --- Proje Dizin Yolları ---
_MOTOR_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_DIR  = os.path.join(_MOTOR_SCRIPT_DIR, "csv")
DBCSV_DIR = os.path.join(_MOTOR_SCRIPT_DIR, "dbCSV")
EXTENDED_PIDS_DIR = os.path.join(DBCSV_DIR, "Extended_PIDs")
DTC_CSV_PATH = os.path.join(DBCSV_DIR, "DTC", "OBD2_DTC_Descriptions.csv")
RAPOR_DIR = os.path.join(_MOTOR_SCRIPT_DIR, "rapor")
os.makedirs(RAPOR_DIR, exist_ok=True)

# --- MONKEY PATCH: Dashboard Ekran Silme İptali ---
Dashboard.clear_screen = lambda: print("\n" + "─"*50 + "\n")

# --- MOCK SERIAL KONTROLÜ ---
try:
    from mock_serial import MockSerial
    MOCK_AVAILABLE = True
except ImportError:
    MOCK_AVAILABLE = False

# --- LOGGING SETUP (V97.1: Instant Flush & Force) ---
logging.basicConfig(filename='auto_expert_log.txt', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s', force=True)
logging.getLogger('matplotlib').setLevel(logging.WARNING)

# Force flush on all handlers
for handler in logging.root.handlers:
    handler.flush = lambda: handler.stream.flush() if hasattr(handler.stream, 'flush') else None

def log_flush(msg):
    """Her önemli logdan sonra diske yazmayı zorla"""
    print(f"[{time.ctime()}] {msg}")
    sys.stdout.flush()

# --- V200: Priority Queue I/O Worker Constants ---
PRIORITY_KEEPALIVE = 0  # En yüksek öncelik (düşük sayı = yüksek öncelik)
PRIORITY_NORMAL = 10
PRIORITY_LOW = 20

# --- V200: Protokol Haritası (AT DPN Yanıtı → Protokol Tipi) ---
PROTO_MAP = {
    1: {"name": "ISO 15765-4 (CAN 11/500)", "is_can": True, "is_slow": False},
    2: {"name": "ISO 15765-4 (CAN 29/500)", "is_can": True, "is_slow": False},
    3: {"name": "ISO 15765-4 (CAN 11/250)", "is_can": True, "is_slow": False},
    4: {"name": "ISO 15765-4 (CAN 29/250)", "is_can": True, "is_slow": False},
    5: {"name": "ISO 14230-4 (KWP2000 5baud)", "is_can": False, "is_slow": True},
    6: {"name": "ISO 15765-4 (CAN 11/500)", "is_can": True, "is_slow": False},  # Insignia
    7: {"name": "ISO 9141-2 (3baud)", "is_can": False, "is_slow": True},
    8: {"name": "ISO 14230-4 (KWP2000 Init)", "is_can": False, "is_slow": True},
    9: {"name": "SAE J1850 (PWM 41.6kbaud)", "is_can": False, "is_slow": False},
}

# --- NRC (Negative Response Code) Sınıflandırma Haritası — Mode22 reverse-engineering için ---
NRC_MAP = {
    "10": "General Reject",
    "11": "Service Not Supported",
    "12": "Sub-Function Not Supported",
    "13": "Incorrect Message Length/Format",
    "21": "Busy Repeat Request",
    "22": "Conditions Not Correct",
    "24": "Request Sequence Error",
    "31": "Request Out of Range",       # Mode22 icin: bu DID bu ECU'da yok
    "33": "Security Access Denied",      # Mode22 icin: seed/key gerekiyor
    "35": "Invalid Key",
    "36": "Exceeded Number Of Attempts",
    "37": "Required Time Delay Not Expired",
    "78": "Response Pending",            # _raw_send zaten retry ile hallediyor, buraya normalde ulasmaz
}

# --- Raw Response Status Sınıflandırması — komut_gonder()'ın son çağrısının SEBEBİNİ ayrı takip eder ---
# Bu sabitler mevcut `list` dönüş değerini DEĞİŞTİRMEZ, sadece ek/gözlemsel bir katmandır.
STATUS_VALID = "VALID"                  # Pozitif, kullanılabilir cevap alındı
STATUS_NO_DATA = "NO_DATA"              # ECU/ELM327 açıkça "NO DATA" dedi
STATUS_TIMEOUT = "TIMEOUT"              # Zaman aşımına uğradı, hiç cevap gelmedi
STATUS_NO_CONNECTION = "NO_CONNECTION"  # Seri port açık değil
STATUS_WORKER_DOWN = "WORKER_DOWN"      # SerialIOThread çalışmıyor
STATUS_SERIAL_ERROR = "SERIAL_ERROR"    # Exception (port koptu, I/O hatası vb.)
STATUS_NRC = "NRC"                      # UDS negative response (7F..) alındı — _classify_nrc zaten bunu ayrıca işliyor
STATUS_DID_MISMATCH = "DID_MISMATCH"    # Mode22 cevabı geldi ama beklenen DID echo edilmedi / bozuk format
STATUS_EMPTY_RESPONSE = "EMPTY_RESPONSE" # İletişim tamamlandı/prompt geldi ama faydalı yük yok

# --- Data Quality Sınıflandırması (Phase C-1/C-3) ---
QUALITY_GOOD = "GOOD"                # Son okuma başarılı ve geçerli
QUALITY_STALE = "STALE"              # Veri belirlenen tazelik sınırını aştı
QUALITY_INVALID = "INVALID"          # NRC, DID_MISMATCH veya NO DATA yanıtı
QUALITY_ERROR = "ERROR"              # TIMEOUT, NO_CONNECTION veya seri hatası
QUALITY_IMPLAUSIBLE = "IMPLAUSIBLE"  # Fiziksel plausibility zarfı dışında (Phase C-3)
QUALITY_SUSPECT = "SUSPECT"          # Zamansal rate-of-change şüpheli (Phase C-4)

# --- Physical Plausibility Durumları (Phase C-3) ---
PHYSICS_PLAUSIBLE = "PLAUSIBLE"
PHYSICS_IMPLAUSIBLE_HIGH = "IMPLAUSIBLE_HIGH"
PHYSICS_IMPLAUSIBLE_LOW = "IMPLAUSIBLE_LOW"
PHYSICS_UNKNOWN = "UNKNOWN"

# --- Physical Plausibility Sınırları (Geniş fiziksel limitler, Phase C-3) ---
PHYSICAL_LIMITS = {
    "RPM": (0, 15000),
    "ECT": (-60, 180),
    "MAP": (0, 300),
    "SPEED": (0, 350),
    "TPS": (0, 100),
    "IAT": (-60, 180),
    "STFT": (-100, 100),
    "LTFT": (-100, 100),
}

# --- Temporal Plausibility Durumları (Phase C-4) ---
TEMPORAL_PLAUSIBLE = "PLAUSIBLE"
TEMPORAL_SUSPECT = "SUSPECT"
TEMPORAL_UNKNOWN = "UNKNOWN"

# --- Temporal Plausibility Sınırları (Maksimum mutlak değişim oranı: birim/saniye, Phase C-4) ---
TEMPORAL_LIMITS = {
    "RPM": 50000,    # RPM / saniye
    "ECT": 20,       # °C / saniye
    "MAP": 1000,     # kPa / saniye
    "SPEED": 100,    # km/h / saniye
    "TPS": 500,      # yüzde puanı / saniye
    "IAT": 20,       # °C / saniye
    "STFT": 500,     # yüzde puanı / saniye
    "LTFT": 100,     # yüzde puanı / saniye
}

# --- Cross-Sensor Correlation Durumları (Phase C-5) ---
CORRELATION_COHERENT = "COHERENT"
CORRELATION_INCONSISTENT = "INCONSISTENT"
CORRELATION_UNKNOWN = "UNKNOWN"

# --- Cross-Sensor Correlation Sınırları (Konservatif tutarsızlık eşikleri, Phase C-5) ---
CORRELATION_THRESHOLDS = {
    "RPM_STANDSTILL_MAX": 50,       # RPM bu değerin altındayken araç hareket ediyorsa tutarsız
    "SPEED_MOVING_MIN": 10,         # km/h
    "TPS_HIGH": 80,                 # % gaz kelebeği açıklığı
    "RPM_LOW": 1000,                # RPM
    "RPM_RUNNING": 1500,            # RPM (motor yüke girecek devir)
    "MAP_EXTREMELY_LOW": 20,        # kPa (aşırı düşük emme manifoldu basıncı)
}

# --- Vehicle Operating Envelope Durumları (Phase C-6) ---
ENVELOPE_NORMAL = "NORMAL"
ENVELOPE_OUT_OF_RANGE_HIGH = "OUT_OF_RANGE_HIGH"
ENVELOPE_OUT_OF_RANGE_LOW = "OUT_OF_RANGE_LOW"
ENVELOPE_UNKNOWN = "UNKNOWN"

# --- Diagnostic Evidence Durumları (Phase D-1) ---
EVIDENCE_SUPPORTED = "SUPPORTED"
EVIDENCE_CONTRADICTED = "CONTRADICTED"
EVIDENCE_UNKNOWN = "UNKNOWN"

# --- Diagnostic Evidence Önem Seviyeleri (Phase D-1) ---
EVIDENCE_INFO = "INFO"
EVIDENCE_WARNING = "WARNING"
EVIDENCE_CRITICAL = "CRITICAL"

# --- Diagnostic Evidence Kaynakları (Phase D-1) ---
SOURCE_DIRECT = "DIRECT"
SOURCE_CROSS_SENSOR = "CROSS_SENSOR"
SOURCE_VEHICLE_PROFILE = "VEHICLE_PROFILE"
SOURCE_TEMPORAL = "TEMPORAL"
SOURCE_PHYSICAL = "PHYSICAL"

# --- Fault Hypothesis Durumları (Phase D-2) ---
HYPOTHESIS_SUPPORTED = "SUPPORTED"
HYPOTHESIS_POSSIBLE = "POSSIBLE"
HYPOTHESIS_CONTRADICTED = "CONTRADICTED"
HYPOTHESIS_INSUFFICIENT = "INSUFFICIENT"

# --- Fault Hypothesis Önem Seviyeleri (Phase D-2) ---
HYPOTHESIS_INFO = "INFO"
HYPOTHESIS_WARNING = "WARNING"
HYPOTHESIS_CRITICAL = "CRITICAL"

# --- Test Recommendation Durumları (Phase D-3) ---
TEST_RECOMMENDED = "RECOMMENDED"
TEST_OPTIONAL = "OPTIONAL"
TEST_BLOCKED = "BLOCKED"
TEST_NOT_APPLICABLE = "NOT_APPLICABLE"

# --- Test Recommendation Öncelikleri (Phase D-3) ---
TEST_PRIORITY_LOW = "LOW"
TEST_PRIORITY_MEDIUM = "MEDIUM"
TEST_PRIORITY_HIGH = "HIGH"

# --- Test Recommendation Güvenlik Seviyeleri (Phase D-3) ---
TEST_SAFE_READ = "SAFE_READ"
TEST_GUIDED_DRIVER = "GUIDED_DRIVER"
TEST_WORKSHOP = "WORKSHOP"
TEST_ACTUATION = "ACTUATION"

def derive_quality_from_status(status: str) -> str:
    """STATUS_* değerini deterministik QUALITY_* sınıfına dönüştürür."""
    if status == STATUS_VALID:
        return QUALITY_GOOD
    elif status in (STATUS_TIMEOUT, STATUS_NO_CONNECTION, STATUS_WORKER_DOWN, STATUS_SERIAL_ERROR):
        return QUALITY_ERROR
    elif status in (STATUS_NO_DATA, STATUS_EMPTY_RESPONSE, STATUS_NRC, STATUS_DID_MISMATCH):
        return QUALITY_INVALID
    return QUALITY_INVALID

# --- V200: Tekil I/O Worker Thread (Priority Queue Mimarisi) ---
class SerialIOThread(threading.Thread):
    """
    Priority Queue tabanlı seri I/O işlemcisi.
    Tüm seri yazma/okuma işlemlerini bu thread üzerinden yaparak thread-safety sağlar.
    """
    def __init__(self, ser, timeout=2.0):
        super().__init__(daemon=True)
        self.ser = ser
        self.timeout = timeout
        self.command_queue = queue.PriorityQueue()
        self.running = True
        self._next_id = 0
        self._id_lock = threading.Lock()
        self.responses = {}
        self.last_raw_status = STATUS_VALID
        self.response_lock = threading.RLock()

    def enqueue(self, command, timeout=None, priority=PRIORITY_NORMAL):
        """
        Kuyruğa komut ekle.
        priority: Düşük sayı = yüksek öncelik (0 = KEEPALIVE, 10 = NORMAL, 20 = LOW)
        """
        if timeout is None:
            timeout = self.timeout
        with self._id_lock:
            request_id = self._next_id
            self._next_id += 1
        self.command_queue.put((priority, time.time(), command, timeout, request_id))
        return request_id

    def run(self):
        """Ana I/O loop - tüm komutları serial port'tan gönder/al"""
        while self.running:
            try:
                # Timeout ile sıra bekle (engellememe için)
                try:
                    priority, enqueue_time, command, timeout, request_id = self.command_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                # Komutu gönder ve yanıt al
                response = self._raw_send(command, timeout)

                with self.response_lock:
                    self.responses[request_id] = response

            except Exception as e:
                log_flush(f"[SERIAL_IO_THREAD] Kritik hata: {e}")
                time.sleep(0.1)

    def _raw_send(self, command, timeout):
        """
        Gerçek seri I/O işlemi. ELM327 hatalarını yutup devam eder.
        """
        if not self.ser or not self.ser.is_open:
            with self.response_lock:
                self.last_raw_status = STATUS_NO_CONNECTION
            return []

        try:
            # Buffer temizle
            if not MOCK_AVAILABLE:
                self.ser.reset_input_buffer()

            # Komutu gönder
            self.ser.write((command + "\r").encode())

            raw_data = b""
            nrc_78_retries = 5
            sleep_time = 0.02
            
            start_time = time.time()
            while (time.time() - start_time) < timeout:
                if self.ser.in_waiting > 0:
                    chunk = self.ser.read(self.ser.in_waiting)
                    raw_data += chunk

                    # NRC 0x78 (Response Pending) kontrolü
                    raw_hex = raw_data.decode('ascii', errors='ignore').replace(" ", "").replace("\r", "").replace("\n", "").upper()
                    payload_hex = raw_hex
                    if len(raw_hex) > 6 and raw_hex.startswith(('7E8', '7E9', '7E0', '7E1')):
                        payload_hex = raw_hex[3:]

                    if len(payload_hex) >= 6 and payload_hex.startswith('7F') and payload_hex[4:6] == '78' and nrc_78_retries > 0:
                        log_flush(f"[UDS_REFUSED] NRC 0x78 (Bekle) alindi, retry... ({nrc_78_retries})")
                        time.sleep(0.5)
                        nrc_78_retries -= 1
                        raw_data = b""
                        start_time = time.time()
                        continue

                    if b'>' in raw_data:
                        time.sleep(0.05)
                        if self.ser.in_waiting == 0:
                            break
                time.sleep(sleep_time)

            # Yanıtı işle
            raw_data = raw_data.replace(b'\x00', b'')  # ELM327/EUSART NULL byte bug fix
            text = raw_data.decode('ascii', errors='ignore')
            raw_lines = []
            for part in text.split('\n'):
                for sub in part.split('\r'):
                    stripped = sub.strip()
                    if stripped:
                        raw_lines.append(stripped)

            clean_lines = []
            for l in raw_lines:
                if l == '>' or l.replace(' ', '') == '>':
                    continue
                if l in ["OK", command] or l.startswith("STOPPED"):
                    continue
                l = l.replace('>', '').strip()
                if l:
                    clean_lines.append(l)

            # ELM327 hatalarını logla ve yut (çökmeyi engelle)
            elm_errors = ["BUS BUSY", "STOPPED", "NO DATA", "ERROR", "?"]
            had_no_data = any("NO DATA" in l for l in clean_lines)
            for error in elm_errors:
                if any(error in line for line in clean_lines):
                    log_flush(f"[ELM327_ERROR] {error} alindi (cmd={command})")
                    # Hatayı yut, devam et
                    clean_lines = [l for l in clean_lines if error not in l]

            with self.response_lock:
                if clean_lines:
                    self.last_raw_status = STATUS_VALID
                elif had_no_data:
                    self.last_raw_status = STATUS_NO_DATA
                elif not raw_lines:
                    self.last_raw_status = STATUS_TIMEOUT
                else:
                    self.last_raw_status = STATUS_EMPTY_RESPONSE  # ör: sadece '>' geldi, prompt var ama faydalı yük yok

            return clean_lines

        except Exception as e:
            log_flush(f"[SERIAL_IO] _raw_send hatası: {e}")
            with self.response_lock:
                self.last_raw_status = STATUS_SERIAL_ERROR
            return []

    def get_response(self, request_id):
        """Belirtilen request_id'nin yanıtını thread-safe şekilde al ve sözlükten temizle"""
        with self.response_lock:
            if request_id in self.responses:
                return self.responses.pop(request_id)
            return None

    def stop(self):
        """Thread'i kapat"""
        self.running = False

def port_secici():
    """Otomatik COM Port Seçici"""
    if MOCK_AVAILABLE:
        print("🔌 Simülasyon Aktif: MockSerial Kullanılıyor")
        return "COM_MOCK"

    ports = list_ports.comports()
    if not ports:
        print("❌ Hiç COM portu bulunamadı!")
        return None
    
    keywords = ['vlinker', 'ch340', 'ftdi', 'elm327', 'obd']
    for port in ports:
        desc = (port.description + " " + (port.manufacturer or "")).lower()
        for k in keywords:
            if k in desc:
                print(f"✅ Otomatik: {port.device}")
                return port.device
    
    # Manuel Seçim
    print("\n📡 Mevcut Portlar:")
    for i, p in enumerate(ports, 1):
        print(f"  {i}. {p.device} - {p.description}")
    
    # V94: Gelişmiş hata yönetimi
    while True:
        try:
            secim = input("Seçim (1-{} veya 'q' çıkış): ".format(len(ports)))
            if secim.lower() == 'q':
                return None
            c = int(secim)
            if 1 <= c <= len(ports):
                return ports[c-1].device
            else:
                print(f"❌ Geçersiz seçim. 1-{len(ports)} arası bir sayı girin.")
        except ValueError:
            print("❌ Lütfen geçerli bir sayı girin.")
        except (KeyboardInterrupt, EOFError):
            return None

# --- PID TANIMLARI VE VIN HARİTASI ---
VIN_MAP = {
    "1G": "GM", "KL": "GM", "JT": "TOYOTA", "WF0": "FORD", "WVW": "VW", 
    "VF1": "RENAULT", "JM": "MAZDA", "KM": "HYUNDAI", "ZFA": "FIAT", "VF3": "PEUGEOT"
}

PID_DB = {
    "GM": {"NAME": "GM 6-Speed", "CMD": "221940", "HEADER_LIST": ["7E1", "7E2", "7E9"], "OFFSET": 40, "BYTE_POS": 1},
}

DTC_DB_CSV = {}
def load_dtc_db():
    try:
        dtc_path = os.path.join(CSV_DIR, "obd-trouble-codes.csv")
        if os.path.exists(dtc_path):
            with open(dtc_path, mode='r', encoding='utf-8') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 2:
                        DTC_DB_CSV[row[0].strip().replace('"', '')] = row[1].strip().replace('"', '')
    except Exception as e:
        log_flush(f"[CSV_LOAD_ERROR] DTC veritabanı (CSV) yüklenemedi: {e}")
load_dtc_db()


class PIDManager:
    """Mode 22 extended PID dosyalarını marka/model bazında yönetir."""
    def __init__(self, extended_dir: str):
        self.extended_dir = Path(extended_dir)

    def list_files(self):
        if not self.extended_dir.exists():
            return []
        return sorted(self.extended_dir.glob("*.csv"))

    def load_for_vehicle(self, vehicle_hint: str):
        hint = (vehicle_hint or "").lower()
        matched = []
        for file_path in self.list_files():
            if not hint or hint in file_path.stem.lower():
                matched.append(file_path)
        if matched:
            return matched
        return self.list_files()


def load_dtc_lookup_from_dbcsv():
    lookup = {}
    if not os.path.exists(DTC_CSV_PATH):
        return lookup
    try:
        with open(DTC_CSV_PATH, mode="r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = (row.get("DTC Code") or row.get("Code") or "").strip().upper()
                desc = (row.get("Description") or row.get("Açıklama") or "").strip()
                if code and desc:
                    lookup[code] = desc
    except Exception as e:
        log_flush(f"[CSV_LOAD_ERROR] OBD2_DTC_Descriptions yüklenemedi: {e}")
    return lookup

def _decode_0101(x):
    if len(x) < 4: return {"MIL": False}
    A, B, C, D = x[0], x[1], x[2], x[3]
    return {
        "MIL": (A & 0x80) > 0,
        "DTC_Count": A & 0x7F,
        "Misfire": {"Sup": bool(B & 0x01), "Rdy": not bool(B & 0x10)},
        "FuelSys": {"Sup": bool(B & 0x02), "Rdy": not bool(B & 0x20)},
        "CompCmp": {"Sup": bool(B & 0x04), "Rdy": not bool(B & 0x40)},
        "Cat": {"Sup": bool(C & 0x01), "Rdy": not bool(D & 0x01)},
        "Evap": {"Sup": bool(C & 0x04), "Rdy": not bool(D & 0x04)},
        "O2": {"Sup": bool(C & 0x20), "Rdy": not bool(D & 0x20)},
        "EGR": {"Sup": bool(C & 0x80), "Rdy": not bool(D & 0x80)}
    }

class AutoExpertEngine:
    """V136: Industrial Safe Math Parser (No eval)"""
    def __init__(self):
        self.ops = {
            ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.Pow: operator.pow, ast.BitAnd: operator.and_,
            ast.BitOr: operator.or_, ast.BitXor: operator.xor, ast.LShift: operator.lshift,
            ast.RShift: operator.rshift, ast.Mod: operator.mod, ast.USub: operator.neg,
            ast.UAdd: lambda x: x,
        }
        self.functions = {
            "BIT": lambda val, bit: (int(val) >> int(bit)) & 1,
            "SIGNED": lambda x: x - 256 if x > 127 else x,
            "INT16": lambda a, b: (int(a) * 256) + int(b),
            "MAX": lambda *args: max(args) if args else None,
            "MIN": lambda *args: min(args) if args else None,
            "LOOKUP": self._lookup
        }
        # GÖREV 1: __init__ içine state değişkenlerini ekle
        self.ser = None
        self.is_can = False
        self.is_slow_protocol = False
        self.current_header = "7DF"
        self.last_response_status = STATUS_VALID  # En son komut_gonder() çağrısının durumu (gözlemsel, list dönüşünü etkilemez)
        self.last_did_match_info = None  # Mode22 parse teşhisi: {"expected": str, "found_at": int|None, "reason": str} veya None
        self._loop_counter = 0
        self.last_valid_data_time = time.time()
        self.watchdog_limit = 15.0
        self.test_start_time = 0
        self.ecu_sessions = {}       # {header_str: last_interaction_unix_time} — tracks which ECUs have an open UDS extended session
        self.session_timeout = 4.0   # seconds; refresh before the UDS default 5s S3 timer expires
        self.data_cache = {}
        self.sensor_cache = {}
        self.sensor_history = {}     # {sensor_name: deque(maxlen=50)}
        self.history_max_len = 50
        self.last_correlation_results = []
        self.last_evidence_results = []
        self.last_hypothesis_results = []
        self.last_test_recommendations = []
        self.vehicle_profile = None
        self.ecu_info = {"VIN": "Bilinmiyor"}
        self.desteklenen_pidler = []
        self.failed_pids = {}
        self.custom_pids = {}
        self.custom_pid_counter = 0
        self.fuel_hint = "UNKNOWN"
        self.safe_parser = self
        # V200: Priority Queue I/O Worker değişkenleri
        self.io_worker = None
        self.keep_alive_timer = None
        self.protocol_id = None
        self.FAST = ["010C", "010D", "0111", "010B", "0104", "010E", "0110", "0123", "0101", "011C", "0151"]
        self.MEDIUM = ["0105", "0106", "0107", "0114", "0115", "010F", "013C", "0123", "015C", "015E", "0124", "0134"]
        self.pid_manager = PIDManager(EXTENDED_PIDS_DIR)
        self.dtc_lookup = load_dtc_lookup_from_dbcsv()
        self.vehicle_hint = ""


    def evaluate(self, expr_str, context):
        try:
            # Pre-clean expression (Torque Pro A:B style to INT16)
            expr_str = expr_str.replace(":", ",")
            tree = ast.parse(expr_str, mode='eval')
            return self._eval_node(tree.body, context)
        except Exception as e:
            return None

    def _eval_node(self, node, context):
        if isinstance(node, ast.Constant): return node.value
        if hasattr(node, 'n'): return node.n # Fallback for old ast.Num
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if hasattr(node, 'id') else node.attr
            if name in context: return context[name]
            raise ValueError(f"Forbidden variable: {name}")
        if isinstance(node, ast.BinOp):
            return self.ops[type(node.op)](self._eval_node(node.left, context), self._eval_node(node.right, context))
        if isinstance(node, ast.UnaryOp):
            return self.ops[type(node.op)](self._eval_node(node.operand, context))
        if isinstance(node, ast.Call):
            func_name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            if func_name in self.functions:
                args = [self._eval_node(arg, context) for arg in node.args]
                return self.functions[func_name](*args)
            raise ValueError(f"Forbidden function: {func_name}")
        if isinstance(node, ast.Subscript):
            val = self._eval_node(node.value, context)
            slc = node.slice
            # Robust Index/Constant handling
            if hasattr(ast, 'Index') and isinstance(slc, ast.Index): slc = slc.value
            idx = self._eval_node(slc, context)
            return val[idx]
        raise TypeError(f"Unsupported syntax: {type(node)}")

    def _lookup(self, val, *key_value_pairs):
        """
        Güvenli LOOKUP fonksiyonu. Torque CSV'lerinde yer alan 
        LOOKUP(A:'Label':0='Val1':1='Val2') şeklindeki sensörleri destekler.
        
        Argümanlar:
          val: Kontrol edilecek değer
          *key_value_pairs: Alternatif (key, value) çiftleri
        
        Örnek: LOOKUP(A, 0, 'Kapalı', 1, 'Açık', 2, 'Hata')
               A=0 ise 'Kapalı', A=1 ise 'Açık', A=2 ise 'Hata' döner
        """
        try:
            val = int(val)
            # key_value_pairs'i (key, value) çiftlerine ayır
            for i in range(0, len(key_value_pairs), 2):
                if i + 1 < len(key_value_pairs):
                    key = int(key_value_pairs[i])
                    value = key_value_pairs[i + 1]
                    if val == key:
                        return value
            # Eşleşme bulunamazsa None döner (sensörü kaybetmeyelim)
            return None
        except (ValueError, TypeError, IndexError):
            # Parse hatası durumunda None döner
            return None

# Updated baglan() method to start KeepAliveThread
    def baglan(self, profil=None):
        """
        Evrensel ve Garantili Bağlantı Stratejisi
        """
        if self.ser and self.ser.is_open:
            self.ser.close()

        selected_port = port_secici()
        if not selected_port: return False

        print(f"🚀 Bağlantı Başlatılıyor: {selected_port}")

        try:
            if MOCK_AVAILABLE:
                self.ser = MockSerial(port=selected_port, baudrate=38400, timeout=2.0)
            else:
                self.ser = serial.Serial(selected_port, 38400, timeout=2.0)
                self.ser.reset_input_buffer()

            # V200: SerialIOThread başlat
            if self.io_worker:
                self.io_worker.stop()
            self.io_worker = SerialIOThread(self.ser, timeout=2.0)
            self.io_worker.start()

            self._init_elm327(profil)

            # V200: Keep-Alive timer başlat
            self._start_keep_alive_timer()
            self.test_start_time = time.time()
            return True

        except (serial.SerialException, ValueError, IndexError, TypeError) as e:
            print(f"❌ Port Hatası: {e}")
            log_flush(f"[SERIAL_IO] Port açma/başlatma hatası: {e}")
            return False

    def _init_elm327(self, profil=None):
        print("🔧 Cihaz Parametreleri Ayarlaniyor...")
        if self.protocol_id:
            komutlar = ["ATZ", "ATE0", "ATL0", "ATS0", "AT H1", f"AT SP {self.protocol_id}", "AT ST FF", "ATAT1", "0100"]
            log_flush(f"Protokol kilidi kullaniliyor: {self.protocol_id}")
        else:
            komutlar = ["ATZ", "ATE0", "ATL0", "ATS0", "AT H1", "AT SP 0", "AT ST FF", "ATAT1", "0100"]

        for k in komutlar:
            self.komut_gonder(k, timeout=2.0)
            time.sleep(0.1)
            
        # V200: AT DPN kullan (AT DP yerine) - Kesin Protokol Tespiti
        res = self.komut_gonder("AT DPN", timeout=1.0)
        protocol_str = "".join(res).upper()
        
        # AT DPN yanıtı sayısal ID döndürür (örn: 6, A6 vb.)
        # Sayıyı parse et ve PROTO_MAP ile protokolü belirle
        protocol_id = None
        try:
            # Yanıttan sayı çıkar (hex veya decimal olabilir)
            hex_match = re.search(r'([0-9A-F]{1,2})', protocol_str)
            if hex_match:
                protocol_id = int(hex_match.group(1), 16)
                log_flush(f"AT DPN Yanıtı: {hex_match.group(1)} → Protokol ID: {protocol_id}")
        except ValueError as e:
            log_flush(f"[PROTO_ERROR] Protokol ID parse hatası: {e}")
            protocol_id = None

        # PROTO_MAP ile protokol özelliklerini belirle
        if protocol_id and protocol_id in PROTO_MAP:
            proto_info = PROTO_MAP[protocol_id]
            self.is_can = proto_info["is_can"]
            self.is_slow_protocol = proto_info["is_slow"]
            print(f"📡 Tespit Edilen Protokol: {proto_info['name']} (ID: {protocol_id})")
            log_flush(f"Protokol: {proto_info['name']}")
            
            # Protokol kilidi kilidi (tekrar bağlantıda hızlı başlama için)
            self.protocol_id = str(protocol_id)
        else:
            # Fallback: AT DP ile eski yöntemi dene
            log_flush(f"[PROTO_WARN] PROTO_MAP'te bulunamadı, fallback AT DP")
            res = self.komut_gonder("AT DP", timeout=1.0)
            protocol_str = "".join(res).upper()
            self.is_can = "CAN" in protocol_str
            self.is_slow_protocol = any(x in protocol_str for x in ["ISO", "KWP"])
            print(f"📡 Tespit Edilen Protokol (Fallback): {protocol_str}")

        self.csv_pids_yukle()
        self.pid_taramasi_yap()

    def _start_keep_alive_timer(self):
        """V200+: Keep-Alive artık ecu_sessions içindeki TÜM açık session'ları dolaşır"""
        def keep_alive_loop():
            while self.io_worker and self.io_worker.running:
                try:
                    now = time.time()
                    for header in list(self.ecu_sessions.keys()):
                        if now - self.ecu_sessions[header] < 2.5:
                            continue  # yakın zamanda zaten kullanıldı, gereksiz trafik yapma

                        if self.current_header != header:
                            self.komut_gonder(f"AT SH {header}", timeout=0.5)
                            self.current_header = header

                        req_id = self.io_worker.enqueue("3E 00", timeout=0.5, priority=PRIORITY_KEEPALIVE)
                        response = None
                        wait_start = time.time()
                        while (time.time() - wait_start) < 0.6:
                            response = self.io_worker.get_response(req_id)
                            if response is not None:
                                break
                            time.sleep(0.02)

                        res_str = "".join(response).upper() if response else ""
                        if "7E00" in res_str:
                            self.ecu_sessions[header] = time.time()
                        elif "7F3E" in res_str:
                            log_flush(f"[KEEPALIVE_REJECT] {header} '3E00' reddetti (NRC 7F3E), session düşürüldü.")
                            self.ecu_sessions.pop(header, None)
                        # response None ya da boşsa (timeout/no data): session'ı düşürmüyoruz,
                        # bir sonraki _ensure_session çağrısı zaten süresi dolmuşsa yeniden açacak.

                    time.sleep(3.0)
                except Exception as e:
                    log_flush(f"[KEEPALIVE_ERROR] Keep-alive timer hatası: {e}")

        self.keep_alive_timer = threading.Thread(target=keep_alive_loop, daemon=True)
        self.keep_alive_timer.start()

    def simulasyonu_sifirla(self):
        """V107: Simülasyon süresini sıfırla (mock_serial UART üzerinden dinler)"""
        if MOCK_AVAILABLE and self.ser:
            self.komut_gonder("AT RESET_SIM")
            print("🔄 Simülasyon süresi sıfırlandı.")

    def _hex_to_ascii_cleaned(self, hex_str):
        """
        V138: Hex dizesini ASCII'ye dönüştürür ve protokol byte'larını temizler.
        - Mode 09 (VIN) yanıtlarından 49 02 başlığını çıkarır
        - Mode 01 (PID) yanıtlarından 41 başlığını çıkarır
        - ISO-TP PCI byte'larını (10, 2x, vb.) çıkarır
        - Çift sayıda hex karakteri garantiler
        
        Returns:
            (ascii_metin, cleanli_hex_str) - Hem ASCII hem de temiz hex
        """
        try:
            # Çift sayıda hex char olmasını sağla
            if len(hex_str) % 2 != 0:
                hex_str = hex_str[:-1]
            
            # Basit protokol header temizliği (49 02 / 41 vs.)
            # Mode 09 (VIN): 49 02 XX ... → XX ...
            if hex_str.startswith('4902'):
                hex_str = hex_str[4:]  # 49 02 çıkar
            # Mode 01 (Standard PID): 41 ... → ...
            elif hex_str.startswith('41'):
                hex_str = hex_str[2:]  # 41 çıkar (optiyonel)
            
            # ISO-TP PCI Stripping (bazen mode 09 mode 01 öncesinde multi-frame gelir)
            # First Frame: 10 LL → LL çıkart ve kalanı al
            if hex_str.startswith('10'):
                # 10 LL XX XX XX XX XX XX → XX XX XX XX XX XX (ilk 7 byte payload)
                hex_str = hex_str[4:]
            
            # Consecutive Frame: 2N → 2N çıkart
            elif hex_str.startswith('2'):
                # 2N XX XX XX XX XX XX XX XX → XX XX XX XX XX XX XX XX (8 byte payload)
                hex_str = hex_str[2:]
            
            # ASCII'ye dönüştür (hata karakterleri yok say)
            ascii_metin = bytes.fromhex(hex_str).decode('ascii', errors='ignore')
            return ascii_metin, hex_str
        except Exception as e:
            log_flush(f"[HEX_ASCII_ERROR] Dönüştürme hatası: {e}")
            return "", hex_str

    def _multiframe_birlestir(self, satirlar):
        """
        V138: ISO-TP Multi-Frame Birleştirici (Mode 09, 01 dahil).
        ELM327'nin multi-frame yanıtlarını (0:, 1:, 2: ve 001, 002 formatları) birleştirir.
        
        Desteklenen Format:
        - "0: AABB..." (frame index: data)
        - "1: AABB..."
        - "49 02 01 ... " (direct CAN response)
        - "7E8 10 11 ..." (CAN header ile)
        - "7E9 21 ..." (consecutive frame)
        """
        frame_satirlar = {}
        diger_satirlar = []
        can_header_re = re.compile(r'^(7E[0-9A-Fa-f])')

        for satir in satirlar:
            temiz = satir.strip().replace(' ', '')
            
            # CAN header'ı temizle (7E8, 7E9, 7E0, 7E1, vb.)
            temiz = can_header_re.sub('', temiz)

            # Format 1: ELM327'nin multiframe formatı ("0: AABB...", "1: AABB...", vb.)
            eslesme = re.match(r'^([0-9A-Fa-f]+):([0-9A-Fa-f]+)$', temiz)
            if eslesme:
                try:
                    indeks = int(eslesme.group(1), 16)
                    payload = eslesme.group(2)
                    frame_satirlar[indeks] = payload
                    continue
                except ValueError:
                    pass
            
            # Format 2: Doğrudan ISO-TP formatı (49 02 01 ... veya 10 11 ... vb.)
            if re.match(r'^(10|2[0-9A-Fa-f]|49|41)[0-9A-Fa-f]+', temiz):
                # ISO-TP PCI byte'ı kontrol et
                if temiz.startswith('10'):  # First Frame
                    frame_satirlar[0] = temiz
                elif temiz.startswith('2'):  # Consecutive Frame
                    # 2N → indeks için N'i al
                    try:
                        pci_byte = int(temiz[0:2], 16)
                        indeks = pci_byte & 0x0F  # Alt 4 bit = frame numarası
                        frame_satirlar[indeks] = temiz
                    except ValueError:
                        diger_satirlar.append(temiz)
                else:  # Mode response (41, 49, vb.)
                    diger_satirlar.append(temiz)
            elif temiz:  # Diğer veri
                diger_satirlar.append(temiz)
        
        # Eğer frame'ler yoksa, normal yanıt olarak kabul et
        if not frame_satirlar:
            return ''.join(diger_satirlar).upper()

        full_payload = []
        data_len = -1 

        for i in sorted(frame_satirlar.keys()):
            payload = frame_satirlar[i]
            try:
                # First Frame (PCI: 10 LL)
                if i == 0 and payload.startswith('10'):
                    if len(payload) >= 4:
                        byte1_str = payload[0:2]
                        byte2_str = payload[2:4]
                        pci_type = int(byte1_str, 16) >> 4
                        
                        if pci_type == 1:  # First Frame (1xxx)
                            byte2 = int(byte2_str, 16)
                            length = ((int(byte1_str, 16) & 0x0F) << 8) | byte2
                            data_len = length
                            # İlk 7 byte veri (10 LL sonrasında 6 byte)
                            full_payload.append(payload[4:])
                        else:
                            full_payload.append(payload)
                    else:
                        full_payload.append(payload)
                
                # Consecutive Frame (PCI: 2N)
                elif i > 0 and payload.startswith('2'):
                    if len(payload) >= 2:
                        full_payload.append(payload[2:])  # PCI byte'ını çıkar
                    else:
                        full_payload.append(payload)
                else:
                    # Normal veri (Mode response gibi:  49 02 01 ...)
                    full_payload.append(payload)
            except (ValueError, IndexError) as e:
                log_flush(f"[ISOTP_ERROR] Çerçeve işlenemedi (index {i}): {payload} - Hata: {e}")
                full_payload.append(payload)

        birlesmis = "".join(full_payload)

        if data_len > 0:
            return birlesmis[:data_len * 2].upper()
            
        return birlesmis.upper()


    def pid_taramasi_yap(self):
        """V106: Blind Scan (Kör Tarama - Demir Yumruk Modu)"""
        print("   🔍 Sensörler Taranıyor (V106 - Gold Master Blind Scan)...")
        self.desteklenen_pidler = []
        
        # V106: Taramadan önce Max Timeout (Aveo/KWP için güvenli)
        self.komut_gonder("AT ST FF") 
        
        # V106+: Genişletilmiş Tarama Listesi (0xC0, 0xE0 eklendi — modern araç gizli sensörleri)
        start_pids = [0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0]
        
        for start in start_pids:
            cmd = f"01{start:02X}"
            
            # V99: İnatçı Retry
            res = []
            res_str = ""
            for attempt in range(3):
                res = self.komut_gonder(cmd, timeout=3.0)
                res_str = "".join(res).replace(" ", "")
                if res and "SEARCHING" not in res_str and len(res_str) > 4:
                    break
                if attempt < 2:
                    time.sleep(1.0)
            
            # V106: Her blok arası bekleme
            time.sleep(0.3)
            
            target = f"41{start:02X}"
            
            if res:
                for line in res:
                    # GÖREV 5: CAN Race Condition Fix - Her satırı tek tek parse et
                    # Birden fazla ECU yanıtı (TCM+ECM) tek string'de karışmaz
                    line_clean = line.replace(" ", "")
                    target_idx = line_clean.find(target)
                    if target_idx != -1:
                        try:
                            data_hex = line_clean[target_idx+4:]
                            if len(data_hex) < 8:
                                continue
                            val = int(data_hex[:8], 16)
                            for i in range(32):
                                if (val >> (31-i)) & 1:
                                    pid_num = start + i + 1
                                    pid_hex = f"01{pid_num:02X}"
                                    if pid_hex not in self.desteklenen_pidler:  # Duplicate önle
                                        self.desteklenen_pidler.append(pid_hex)
                        except Exception as e:
                            log_flush(f"[PID_SCAN_ERROR] PID tarama sırasında veri ayrıştırma hatası: {e}")
            
            # V106: Bloktan cevap gelmese bile BREAK YOK - Sonraki bloğu dene.
        
        # V106: Tarama bitti, eğer CAN protokolü ise Hızlı Moda (ST 32) geç
        if self.is_can:
             self.komut_gonder("AT ST 32")
        
        # V104: Zorunlu Sensörleri Koşulsuz Ekle (DPF ve EGR Eklendi)
        # + 0124 / 0134: Wideband O2 PID'leri (FSI/GDI motorlar için)
        mandatory = ["010C", "010D", "0105", "0111", "010B", "0106", "0107", "0104", "0101", "0114", "010F", "0110", "0123", "016A", "017F", "0124", "0134"]
        for p in mandatory:
            # Duplicate önle
            if p not in self.desteklenen_pidler: 
                self.desteklenen_pidler.append(p)

        print(f"   ✨ {len(self.desteklenen_pidler)} Sensör Başarıyla Keşfedildi!")
        log_flush(f"V100: Desteklenen PIDler ({len(self.desteklenen_pidler)}): {self.desteklenen_pidler}")
        
        # V111 FIX: Dizel Tespiti — Sadece dizel-has PID'lere güven
        # 0123 = Fuel Rail Pressure (yüksek basınç → dizel common-rail)
        # 016D = Fuel Pressure Control Solenoid (dizel has)
        # 0110 (MAF) KULLANILMAMALI — benzinlilerde de bulunur
        if "0123" in self.desteklenen_pidler or "016D" in self.desteklenen_pidler:
            self.fuel_hint = "DIZEL"
        else:
            self.fuel_hint = "BENZIN"
        
        # V101: VIN Okuma (0902)
        # motor.py içindeki print satırı revizyonu
        print(f"   ✨ Aracın Yanıt Verdiği {len(self.desteklenen_pidler)} Sensör Analize Alındı!") #
        self.vin_oku()

    
    def vin_oku(self):
        """
        V138: ISO-TP Multi-Frame Birlestirme + Temiz Hex-to-ASCII Conversion + Esnek VIN Regex
        
        Desteklenen VIN Prefixed:
        - W0L (Opel Insignia, Astra, etc.)
        - WVW (Volkswagen)
        - WF0 (Ford)
        - JT (Toyota)
        - KL, KM (Hyundai/Kia)
        - VF1, VF3 (Renault/Peugeot)
        - ZFA (Fiat)
        """
        try:
            res = self.komut_gonder("0902", timeout=2.0)
            if not res:
                log_flush("[VIN_ERROR] 0902 komutu yanıt vermedi")
                return

            # Mode 09 multi-frame yanıtını birleştir
            hex_str = self._multiframe_birlestir(res)
            
            try:
                # Hex'i ASCII'ye dönüştür (protokol header'larını temizle)
                ascii_metin, clean_hex = self._hex_to_ascii_cleaned(hex_str)
                
                if not ascii_metin:
                    log_flush(f"[VIN_ERROR] Hex'ten ASCII'ye dönüştürme başarısız")
                    return
                
                # Esnek VIN Regex: 17 haneli, I/O/Q harf içermeyen
                # VIN format: WMI (3) + Vehicle Descriptor (6) + Check Digit (1) + Year (1) + Plant (1) + Serial (5)
                # Örnek: W0L0000000000000000 (Opel) veya WVW0000000000000000 (VW) vs.
                
                # Çeşitli VIN pattern'leri:
                vin_patterns = [
                    # Uzun match: ilk 3 karakterin bilinen WMI prefixleri
                    r'(W0L|WVW|WF0|ZFA|VF1|VF3|KL|KM|JT|JM)[A-HJ-NPR-Z0-9]{14}',  # Uzun prefix (3 harf)
                    # Kısa match: 2 haneli prefix + 15 karakter
                    r'(WF|JT|JM|KL|KM|VF|ZF)[A-HJ-NPR-Z0-9]{15}',
                    # Fallback: 17 karakter (herhangi bir konumda başlayabilir)
                    r'[A-HJ-NPR-Z0-9]{17}'
                ]
                
                eslesme = None
                for pattern in vin_patterns:
                    eslesme = re.search(pattern, ascii_metin)
                    if eslesme:
                        break
                
                if eslesme:
                    self.vin = eslesme.group(0)
                    self.ecu_info["VIN"] = self.vin
                    print(f"   🔑 VIN: {self.vin}")
                    log_flush(f"VIN Okundu: {self.vin}")
                    self.vehicle_hint = self._vehicle_hint_from_vin(self.vin)
                    self.csv_pids_yukle()
                    
                    # Mode 09'un diğer PID'leri de oku
                    self._mode9_oku("0904", "CalibrationID")
                    self._mode9_oku("090A", "ECUName")
                else:
                    # Debug: tüm ASCII çıktısını logla
                    ascii_clean = ''.join(c for c in ascii_metin if 0x20 <= ord(c) <= 0x7E)
                    log_flush(f"[VIN_ERROR] VIN ham ASCII'de bulunamadı. İçerik: {ascii_clean[:50]}")
                    log_flush(f"[VIN_DEBUG] Toplam hex: {clean_hex[:40]} (kesik)")
            except Exception as e:
                log_flush(f"[VIN_ERROR] VIN ASCII parse hatası: {e}")

        except Exception as e:
            log_flush(f"[VIN_ERROR] VIN okuma sırasında genel hata: {e}")

    def _vehicle_hint_from_vin(self, vin: str) -> str:
        vin_upper = (vin or "").upper()
        for prefix, brand in VIN_MAP.items():
            if vin_upper.startswith(prefix):
                return brand.lower()
        return ""
    
    # GÖREV 2: V92 simulasyonu_sifirla kaldırıldı — V107 versiyonu (satır 225) geçerli

    def komut_gonder(self, komut, timeout=1.0):
        """
        V200: Priority Queue I/O Worker ile komut gönder
        Tüm komutlar SerialIOThread'in kuyruğuna eklenir, gerçek I/O thread-safe şekilde yapılır.
        """
        if not self.ser or not self.ser.is_open:
            self.last_response_status = STATUS_NO_CONNECTION
            return []

        if not self.io_worker or not self.io_worker.running:
            log_flush("[KOMUT_ERROR] SerialIOThread çalışmıyor")
            self.last_response_status = STATUS_WORKER_DOWN
            return []

        if self.is_slow_protocol:
            timeout = max(timeout, 3.0)
        else:
            timeout = max(timeout, 0.5)

        request_id = self.io_worker.enqueue(komut, timeout=timeout, priority=PRIORITY_NORMAL)

        start_wait = time.time()
        while (time.time() - start_wait) < timeout:
            response = self.io_worker.get_response(request_id)
            if response is not None:
                with self.io_worker.response_lock:
                    self.last_response_status = getattr(self.io_worker, "last_raw_status", STATUS_VALID)
                return response
            time.sleep(0.02)

        log_flush(f"[KOMUT_TIMEOUT] {komut} komutu timeout oldu ({timeout}s)")
        self.last_response_status = STATUS_TIMEOUT
        return []

    def _check_physical_plausibility(self, name: str, value) -> str:
        """
        Phase C-3: Tekil sensör fiziksel plausibility kontrolü.
        Değerin geniş fiziksel sınırlar (PHYSICAL_LIMITS) içinde olup olmadığını belirler.
        """
        if name not in PHYSICAL_LIMITS:
            return PHYSICS_UNKNOWN

        # Güvenli sayısal kontrol (bool tipleri int alt sınıfı olduğundan hariç tutulur)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return PHYSICS_UNKNOWN

        min_val, max_val = PHYSICAL_LIMITS[name]

        if value < min_val:
            return PHYSICS_IMPLAUSIBLE_LOW
        elif value > max_val:
            return PHYSICS_IMPLAUSIBLE_HIGH
        else:
            return PHYSICS_PLAUSIBLE

    def _check_temporal_plausibility(self, name: str, value, timestamp: float = None) -> str:
        """
        Phase C-4: Tekil sensör zamansal plausibility (rate-of-change) kontrolü.
        En son güvenilir geçmiş ölçümüne (self.sensor_history) göre değişim hızını denetler.
        """
        if name not in TEMPORAL_LIMITS:
            return TEMPORAL_UNKNOWN

        # Güvenli sayısal kontrol (bool tipleri hariç)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return TEMPORAL_UNKNOWN

        hist = self.sensor_history.get(name)
        if not hist:
            return TEMPORAL_UNKNOWN

        prev_entry = hist[-1]
        prev_val = prev_entry.get("val")
        prev_time = prev_entry.get("time")

        if isinstance(prev_val, bool) or not isinstance(prev_val, (int, float)):
            return TEMPORAL_UNKNOWN

        if not isinstance(prev_time, (int, float)):
            return TEMPORAL_UNKNOWN

        current_time = timestamp if timestamp is not None else time.time()
        dt = current_time - prev_time

        if dt <= 0:
            return TEMPORAL_UNKNOWN

        delta = abs(value - prev_val)
        rate = delta / dt
        max_rate = TEMPORAL_LIMITS[name]

        if rate > max_rate:
            return TEMPORAL_SUSPECT
        else:
            return TEMPORAL_PLAUSIBLE

    def _check_vehicle_envelope(self, name: str, value, profile=None) -> str:
        """
        Phase C-6: Araca özel işletim zarfı (VehicleProfile) kontrolü.
        Örn: Redline üstü devirleri tespit eder.
        Genel fiziksel plausibility (C-3) veya zamansal plausibility (C-4) ile karıştırılmaz.
        """
        prof = profile if profile is not None else getattr(self, "vehicle_profile", None)
        if prof is None:
            return ENVELOPE_UNKNOWN

        # Güvenli sayısal kontrol (bool tipleri hariç)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return ENVELOPE_UNKNOWN

        # RULE 1: RPM vs Redline
        if name == "RPM":
            redline = getattr(prof, "redline", None)
            if isinstance(redline, (int, float)) and not isinstance(redline, bool) and redline > 0:
                if value > redline:
                    return ENVELOPE_OUT_OF_RANGE_HIGH
                elif value >= 0:
                    return ENVELOPE_NORMAL
                else:
                    return ENVELOPE_OUT_OF_RANGE_LOW
            return ENVELOPE_UNKNOWN

        return ENVELOPE_UNKNOWN

    def _update_sensor_cache(self, name: str, value, status: str = STATUS_VALID, quality: str = None, timestamp: float = None, source: str = None) -> dict:
        """
        V204 (Phase C-1/C-2/C-3/C-4/C-6): Sensor verisini zaman damgası, kalite, fiziksel & zamansal plausibility, araca özel zarf ve geçmiş takibiyle kaydeder.
        Mevcut 'val' ve 'time' yapısını %100 korur, bounded history'e sadece güvenilir geçerli ölçümleri ekler.
        """
        ts = timestamp if timestamp is not None else time.time()
        q = quality if quality is not None else derive_quality_from_status(status)

        physics_status = None
        temporal_status = None
        envelope_status = None

        if status == STATUS_VALID and value is not None:
            # 1. Zamansal plausibility (mevcut trusted history'ye göre hesaplanır, ekleme öncesi)
            temporal_status = self._check_temporal_plausibility(name, value, timestamp=ts)
            # 2. Fiziksel plausibility
            physics_status = self._check_physical_plausibility(name, value)
            # 3. Araca özel işletim zarfı (Phase C-6)
            envelope_status = self._check_vehicle_envelope(name, value)

            # Öncelik hiyerarşisi: Fiziksel İmplausibility > Zamansal Şüphe > Normal Kalite
            if physics_status in (PHYSICS_IMPLAUSIBLE_LOW, PHYSICS_IMPLAUSIBLE_HIGH):
                q = QUALITY_IMPLAUSIBLE
            elif temporal_status == TEMPORAL_SUSPECT:
                q = QUALITY_SUSPECT

        entry = {
            "val": value,
            "time": ts,
            "status": status,
            "quality": q,
        }
        if source:
            entry["source"] = source
        if physics_status is not None:
            entry["physics_status"] = physics_status
        if temporal_status is not None:
            entry["temporal_status"] = temporal_status
        if envelope_status is not None:
            entry["envelope_status"] = envelope_status

        self.data_cache[name] = entry
        self.sensor_cache[name] = value

        # Sadece STATUS_VALID, QUALITY_GOOD ve geçerli değer üretilmişse güvenilir geçmişe kaydet
        if status == STATUS_VALID and q == QUALITY_GOOD and value is not None:
            if name not in self.sensor_history:
                self.sensor_history[name] = deque(maxlen=self.history_max_len)
            self.sensor_history[name].append(dict(entry))

        return entry

    def _get_sensor_age(self, name: str) -> float | None:
        """Sensörün son geçerli edinilme zamanından bu yana geçen süreyi (saniye) döner."""
        entry = self.data_cache.get(name)
        if isinstance(entry, dict) and "time" in entry and entry["time"] > 0:
            return time.time() - entry["time"]
        return None

    def _is_sensor_fresh(self, name: str, max_age: float = 2.0) -> bool:
        """Sensörün en son edinilen değerinin max_age (varsayılan 2.0s) içinde olup olmadığını kontrol eder."""
        age = self._get_sensor_age(name)
        if age is None:
            return False
        return age <= max_age

    def _get_sensor_history(self, name: str, limit: int = None) -> list:
        """Sensörün geçmiş geçerli ölçümlerinin bir kopyasını döner (en eskiden en yeniye)."""
        hist = self.sensor_history.get(name)
        if not hist:
            return []
        items = list(hist)
        if limit is not None and limit > 0:
            return items[-limit:]
        return items

    def _get_trusted_sensor_value(self, name: str) -> float | None:
        """
        Phase C-5: Sadece STATUS_VALID, QUALITY_GOOD, taze ve sayısal olan sensör değerini döner.
        IMPLAUSIBLE, SUSPECT, STALE, INVALID veya ERROR durumundaki veriler güvenilmezdir (None döner).
        """
        entry = self.data_cache.get(name)
        if not isinstance(entry, dict):
            return None

        if entry.get("status") != STATUS_VALID:
            return None

        if entry.get("quality") != QUALITY_GOOD:
            return None

        if not self._is_sensor_fresh(name):
            return None

        val = entry.get("val")
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return None

        return float(val)

    def _check_cross_sensor_correlations(self) -> list:
        """
        Phase C-5: Anlık geçerli ve taze sensör verileri arasındaki çapraz tutarlılığı kontrol eder.
        Sensör kalitelerini veya cache değerlerini ASLA mutasyona uğratmaz; yapılandırılmış kanıt döner.
        """
        results = []

        # RULE 1: RPM vs SPEED at Standstill (RPM_VSS)
        rpm_val = self._get_trusted_sensor_value("RPM")
        speed_val = self._get_trusted_sensor_value("SPEED")
        if rpm_val is None or speed_val is None:
            results.append({
                "rule": "RPM_VSS",
                "status": CORRELATION_UNKNOWN,
                "sensors": ["RPM", "SPEED"],
                "details": "Eksik veya güvenilmez RPM/SPEED verisi"
            })
        elif rpm_val <= CORRELATION_THRESHOLDS["RPM_STANDSTILL_MAX"] and speed_val >= CORRELATION_THRESHOLDS["SPEED_MOVING_MIN"]:
            results.append({
                "rule": "RPM_VSS",
                "status": CORRELATION_INCONSISTENT,
                "sensors": ["RPM", "SPEED"],
                "details": f"Motor duruyor (RPM={rpm_val}) ancak araç hareket halinde (SPEED={speed_val} km/h)"
            })
        else:
            results.append({
                "rule": "RPM_VSS",
                "status": CORRELATION_COHERENT,
                "sensors": ["RPM", "SPEED"],
                "details": "RPM ve SPEED tutarlı"
            })

        # RULE 2: TPS vs RPM Response (TPS_RPM)
        tps_val = self._get_trusted_sensor_value("TPS")
        if tps_val is None or rpm_val is None:
            results.append({
                "rule": "TPS_RPM",
                "status": CORRELATION_UNKNOWN,
                "sensors": ["TPS", "RPM"],
                "details": "Eksik veya güvenilmez TPS/RPM verisi"
            })
        elif tps_val >= CORRELATION_THRESHOLDS["TPS_HIGH"] and rpm_val <= CORRELATION_THRESHOLDS["RPM_LOW"]:
            results.append({
                "rule": "TPS_RPM",
                "status": CORRELATION_INCONSISTENT,
                "sensors": ["TPS", "RPM"],
                "details": f"Yüksek gaz kelebeği (TPS={tps_val}%) ancak düşük motor devri (RPM={rpm_val})"
            })
        else:
            results.append({
                "rule": "TPS_RPM",
                "status": CORRELATION_COHERENT,
                "sensors": ["TPS", "RPM"],
                "details": "TPS ve RPM tutarlı"
            })

        # RULE 3: TPS vs MAP Airflow/Load Consistency (TPS_MAP)
        map_val = self._get_trusted_sensor_value("MAP")
        if tps_val is None or rpm_val is None or map_val is None:
            results.append({
                "rule": "TPS_MAP",
                "status": CORRELATION_UNKNOWN,
                "sensors": ["TPS", "RPM", "MAP"],
                "details": "Eksik veya güvenilmez TPS/RPM/MAP verisi"
            })
        elif (tps_val >= CORRELATION_THRESHOLDS["TPS_HIGH"] and 
              rpm_val >= CORRELATION_THRESHOLDS["RPM_RUNNING"] and 
              map_val <= CORRELATION_THRESHOLDS["MAP_EXTREMELY_LOW"]):
            results.append({
                "rule": "TPS_MAP",
                "status": CORRELATION_INCONSISTENT,
                "sensors": ["TPS", "RPM", "MAP"],
                "details": f"Yüksek gaz kelebeği (TPS={tps_val}%) ve çalışan motorda (RPM={rpm_val}) aşırı düşük emme basıncı (MAP={map_val} kPa)"
            })
        else:
            results.append({
                "rule": "TPS_MAP",
                "status": CORRELATION_COHERENT,
                "sensors": ["TPS", "RPM", "MAP"],
                "details": "TPS, RPM ve MAP tutarlı"
            })

        self.last_correlation_results = results
        return results

    def _collect_diagnostic_evidence(self) -> list:
        """
        Phase D-1: Güvenilir C-katmanı ölçüm ve metaverilerini yapılandırılmış teşhis kanıtlarına dönüştürür.
        Arıza teşhisi yapmaz, olasılık/puan üretmez, alt katmanları mutasyona uğratmaz.
        """
        evidence_list = []
        seen_ids = set()

        def add_evidence(ev_id: str, status: str, severity: str, sensors: list, observations: dict, reason: str, source: str):
            if ev_id in seen_ids:
                return
            seen_ids.add(ev_id)
            evidence_list.append({
                "id": ev_id,
                "status": status,
                "severity": severity,
                "sensors": sensors,
                "observations": observations,
                "reason": reason,
                "source": source
            })

        # RULE 1: Engine State (RPM)
        rpm_val = self._get_trusted_sensor_value("RPM")
        if rpm_val is not None:
            if rpm_val > 400:
                add_evidence(
                    ev_id="ENGINE_RUNNING",
                    status=EVIDENCE_SUPPORTED,
                    severity=EVIDENCE_INFO,
                    sensors=["RPM"],
                    observations={"RPM": rpm_val},
                    reason="Motor çalışıyor (RPM > 400)",
                    source=SOURCE_DIRECT
                )
            else:
                add_evidence(
                    ev_id="ENGINE_NOT_RUNNING",
                    status=EVIDENCE_SUPPORTED,
                    severity=EVIDENCE_INFO,
                    sensors=["RPM"],
                    observations={"RPM": rpm_val},
                    reason="Motor çalışmıyor veya marş devrinde (RPM <= 400)",
                    source=SOURCE_DIRECT
                )
        else:
            add_evidence(
                ev_id="ENGINE_RUNNING",
                status=EVIDENCE_UNKNOWN,
                severity=EVIDENCE_INFO,
                sensors=["RPM"],
                observations={},
                reason="RPM verisi eksik veya güvenilmez",
                source=SOURCE_DIRECT
            )

        # RULE 2: Coolant Temperature (ECT vs Vehicle Profile Target)
        ect_val = self._get_trusted_sensor_value("ECT")
        prof = getattr(self, "vehicle_profile", None)
        hedef_ect = getattr(prof, "hedef_ect", None) if prof is not None else None

        if ect_val is not None and isinstance(hedef_ect, (int, float)) and not isinstance(hedef_ect, bool) and hedef_ect > 0:
            if rpm_val is not None and rpm_val > 400:
                if ect_val < (hedef_ect - 25):  # örn. 90°C hedefte 65°C altı
                    add_evidence(
                        ev_id="ECT_TOO_COLD",
                        status=EVIDENCE_SUPPORTED,
                        severity=EVIDENCE_WARNING,
                        sensors=["ECT"],
                        observations={"ECT": ect_val, "target_ect": hedef_ect},
                        reason=f"Soğutma suyu sıcaklığı hedef değerin ({hedef_ect}°C) belirgin altında ({ect_val}°C)",
                        source=SOURCE_VEHICLE_PROFILE
                    )
                elif ect_val > 115:
                    add_evidence(
                        ev_id="ECT_TOO_HOT",
                        status=EVIDENCE_SUPPORTED,
                        severity=EVIDENCE_WARNING,
                        sensors=["ECT"],
                        observations={"ECT": ect_val, "target_ect": hedef_ect},
                        reason=f"Soğutma suyu sıcaklığı aşırı yüksek ({ect_val}°C)",
                        source=SOURCE_DIRECT
                    )
        elif ect_val is None and prof is not None and isinstance(hedef_ect, (int, float)) and hedef_ect > 0:
            add_evidence(
                ev_id="ECT_TOO_COLD",
                status=EVIDENCE_UNKNOWN,
                severity=EVIDENCE_INFO,
                sensors=["ECT"],
                observations={},
                reason="ECT verisi eksik veya güvenilmez",
                source=SOURCE_VEHICLE_PROFILE
            )

        # RULE 3: Fuel Trim / Mixture (STFT & LTFT)
        stft_val = self._get_trusted_sensor_value("STFT")
        ltft_val = self._get_trusted_sensor_value("LTFT")
        trim_obs = {}
        trim_sensors = []
        if stft_val is not None:
            trim_obs["STFT"] = stft_val
            trim_sensors.append("STFT")
        if ltft_val is not None:
            trim_obs["LTFT"] = ltft_val
            trim_sensors.append("LTFT")

        if trim_sensors:
            is_pos = (stft_val is not None and stft_val >= 15.0) or (ltft_val is not None and ltft_val >= 15.0)
            is_neg = (stft_val is not None and stft_val <= -15.0) or (ltft_val is not None and ltft_val <= -15.0)

            if is_pos:
                add_evidence(
                    ev_id="FUEL_TRIM_POSITIVE",
                    status=EVIDENCE_SUPPORTED,
                    severity=EVIDENCE_WARNING,
                    sensors=trim_sensors,
                    observations=trim_obs,
                    reason="Yakıt trim düzeltmesi belirgin pozitif (zenginleştirme ihtiyacı)",
                    source=SOURCE_DIRECT
                )
            elif is_neg:
                add_evidence(
                    ev_id="FUEL_TRIM_NEGATIVE",
                    status=EVIDENCE_SUPPORTED,
                    severity=EVIDENCE_WARNING,
                    sensors=trim_sensors,
                    observations=trim_obs,
                    reason="Yakıt trim düzeltmesi belirgin negatif (fakirleştirme ihtiyacı)",
                    source=SOURCE_DIRECT
                )

        # RULE 4: Airflow / Load (MAF)
        maf_val = self._get_trusted_sensor_value("MAF")
        if maf_val is not None and rpm_val is not None and rpm_val >= 1000:
            if maf_val <= 0.5:
                add_evidence(
                    ev_id="AIRFLOW_LOW",
                    status=EVIDENCE_SUPPORTED,
                    severity=EVIDENCE_WARNING,
                    sensors=["MAF", "RPM"],
                    observations={"MAF": maf_val, "RPM": rpm_val},
                    reason="Motor çalışırken hava akış ölçümü (MAF) sıfıra yakın",
                    source=SOURCE_DIRECT
                )

        # RULE 5: Sensor Agreement (C-5 Cross-Sensor Correlation reuse)
        corr_results = getattr(self, "last_correlation_results", [])
        if not corr_results:
            corr_results = self._check_cross_sensor_correlations()

        for r in corr_results:
            if r.get("status") == CORRELATION_INCONSISTENT:
                add_evidence(
                    ev_id="SENSOR_CORRELATION_INCONSISTENT",
                    status=EVIDENCE_SUPPORTED,
                    severity=EVIDENCE_WARNING,
                    sensors=r.get("sensors", []),
                    observations={"rule": r.get("rule")},
                    reason=r.get("details", "Sensörler arası tutarsızlık tespit edildi"),
                    source=SOURCE_CROSS_SENSOR
                )

        # RULE 6: Vehicle Operating Envelope (C-6)
        for s_name in ("RPM", "SPEED", "ECT", "MAP", "TPS"):
            s_entry = self.data_cache.get(s_name)
            if isinstance(s_entry, dict) and s_entry.get("status") == STATUS_VALID and s_entry.get("quality") == QUALITY_GOOD:
                env_status = s_entry.get("envelope_status")
                if env_status in (ENVELOPE_OUT_OF_RANGE_HIGH, ENVELOPE_OUT_OF_RANGE_LOW):
                    add_evidence(
                        ev_id="VEHICLE_ENVELOPE_EXCEEDED",
                        status=EVIDENCE_SUPPORTED,
                        severity=EVIDENCE_WARNING,
                        sensors=[s_name],
                        observations={s_name: s_entry.get("val"), "envelope_status": env_status},
                        reason=f"{s_name} sensör değeri ({s_entry.get('val')}) araca özel çalışma zarfını aştı ({env_status})",
                        source=SOURCE_VEHICLE_PROFILE
                    )

        # RULE 7: Sensor Reliability Meta-Evidence (optional C-3/C-4 meta-evidence)
        for s_name, s_entry in self.data_cache.items():
            if isinstance(s_entry, dict):
                q = s_entry.get("quality")
                if q == QUALITY_IMPLAUSIBLE:
                    add_evidence(
                        ev_id="SENSOR_PHYSICAL_IMPLAUSIBLE",
                        status=EVIDENCE_SUPPORTED,
                        severity=EVIDENCE_WARNING,
                        sensors=[s_name],
                        observations={s_name: s_entry.get("val"), "physics_status": s_entry.get("physics_status")},
                        reason=f"{s_name} sensörü fiziksel sınırların dışında ölçüm üretiyor",
                        source=SOURCE_PHYSICAL
                    )
                elif q == QUALITY_SUSPECT:
                    add_evidence(
                        ev_id="SENSOR_TEMPORAL_SUSPECT",
                        status=EVIDENCE_SUPPORTED,
                        severity=EVIDENCE_WARNING,
                        sensors=[s_name],
                        observations={s_name: s_entry.get("val"), "temporal_status": s_entry.get("temporal_status")},
                        reason=f"{s_name} sensöründe şüpheli zamansal değişim hızı tespit edildi",
                        source=SOURCE_TEMPORAL
                    )

        self.last_evidence_results = evidence_list
        return evidence_list

    def _infer_fault_hypotheses(self, evidence=None) -> list:
        """
        Phase D-2: Yapılandırılmış D-1 teşhis kanıtlarından deterministik arıza hipotezleri üretir.
        Kesin arıza teşhisi koymaz, onarım tavsiyesi vermez (next_step=None), olasılık puanı üretmez.
        """
        ev_list = evidence if evidence is not None else self._collect_diagnostic_evidence()

        # Kanıtları ID'lerine ve durumlarına göre indeksle
        supported_ev_ids = {ev["id"] for ev in ev_list if isinstance(ev, dict) and ev.get("status") == EVIDENCE_SUPPORTED}
        all_ev_ids = {ev["id"] for ev in ev_list if isinstance(ev, dict)}

        # Minimal tanımsal bağlam (context)
        prof = getattr(self, "vehicle_profile", None)
        motor_kodu = getattr(prof, "motor_kodu", "UNKNOWN") if prof is not None else "UNKNOWN"
        yakit_tipi = getattr(prof, "yakit_tipi", "UNKNOWN") if prof is not None else "UNKNOWN"

        engine_state = "UNKNOWN"
        if "ENGINE_RUNNING" in supported_ev_ids:
            engine_state = "RUNNING"
        elif "ENGINE_NOT_RUNNING" in supported_ev_ids:
            engine_state = "NOT_RUNNING"

        ctx = {
            "engine_state": engine_state,
            "profile": motor_kodu,
            "fuel_type": yakit_tipi
        }

        hypotheses = []

        # 1. HYPOTHESIS: FUEL_SYSTEM_LEAN
        lean_supporting = []
        lean_contradicting = []
        lean_missing = []

        if "FUEL_TRIM_NEGATIVE" in supported_ev_ids:
            lean_contradicting.append("FUEL_TRIM_NEGATIVE")
        if "FUEL_TRIM_POSITIVE" in supported_ev_ids:
            lean_supporting.append("FUEL_TRIM_POSITIVE")
        if "AIRFLOW_LOW" in supported_ev_ids:
            lean_supporting.append("AIRFLOW_LOW")
        if "ENGINE_RUNNING" in supported_ev_ids:
            lean_supporting.append("ENGINE_RUNNING")
        elif "ENGINE_RUNNING" not in all_ev_ids or (any(ev.get("id") == "ENGINE_RUNNING" and ev.get("status") == EVIDENCE_UNKNOWN for ev in ev_list)):
            lean_missing.append("ENGINE_RUNNING")

        if lean_contradicting and ("FUEL_TRIM_POSITIVE" not in supported_ev_ids):
            lean_status = HYPOTHESIS_CONTRADICTED
            lean_reason = "Negatif yakıt trim kanıtı karışımın fakir olduğu hipoteziyle çelişiyor"
        elif "FUEL_TRIM_POSITIVE" in supported_ev_ids:
            if len(lean_supporting) >= 2 and not lean_contradicting:
                lean_status = HYPOTHESIS_SUPPORTED
                lean_reason = "Pozitif yakıt trim düzeltmesi ve çalışma koşulları fakir karışım hipotezini destekliyor"
            else:
                lean_status = HYPOTHESIS_POSSIBLE
                lean_reason = "Pozitif yakıt trim kanıtı mevcut ancak ek doğrulayıcı kanıtlar sınırlı"
        else:
            lean_status = HYPOTHESIS_INSUFFICIENT
            lean_reason = "Fakir karışım hipotezini değerlendirmek için yeterli kanıt yok"

        lean_supporting = list(dict.fromkeys(lean_supporting))
        lean_contradicting = list(dict.fromkeys(lean_contradicting))
        lean_missing = list(dict.fromkeys(lean_missing))

        hypotheses.append({
            "id": "FUEL_SYSTEM_LEAN",
            "status": lean_status,
            "severity": HYPOTHESIS_WARNING,
            "title": "Fuel mixture appears lean",
            "supporting_evidence": lean_supporting,
            "contradicting_evidence": lean_contradicting,
            "missing_evidence": lean_missing,
            "reason": lean_reason,
            "context": ctx,
            "next_step": None
        })

        # 2. HYPOTHESIS: FUEL_SYSTEM_RICH
        rich_supporting = []
        rich_contradicting = []
        rich_missing = []

        if "FUEL_TRIM_POSITIVE" in supported_ev_ids:
            rich_contradicting.append("FUEL_TRIM_POSITIVE")
        if "FUEL_TRIM_NEGATIVE" in supported_ev_ids:
            rich_supporting.append("FUEL_TRIM_NEGATIVE")
        if "AIRFLOW_HIGH" in supported_ev_ids:
            rich_supporting.append("AIRFLOW_HIGH")
        if "ENGINE_RUNNING" in supported_ev_ids:
            rich_supporting.append("ENGINE_RUNNING")
        elif "ENGINE_RUNNING" not in all_ev_ids or (any(ev.get("id") == "ENGINE_RUNNING" and ev.get("status") == EVIDENCE_UNKNOWN for ev in ev_list)):
            rich_missing.append("ENGINE_RUNNING")

        if rich_contradicting and ("FUEL_TRIM_NEGATIVE" not in supported_ev_ids):
            rich_status = HYPOTHESIS_CONTRADICTED
            rich_reason = "Pozitif yakıt trim kanıtı karışımın zengin olduğu hipoteziyle çelişiyor"
        elif "FUEL_TRIM_NEGATIVE" in supported_ev_ids:
            if len(rich_supporting) >= 2 and not rich_contradicting:
                rich_status = HYPOTHESIS_SUPPORTED
                rich_reason = "Negatif yakıt trim düzeltmesi ve çalışma koşulları zengin karışım hipotezini destekliyor"
            else:
                rich_status = HYPOTHESIS_POSSIBLE
                rich_reason = "Negatif yakıt trim kanıtı mevcut ancak ek doğrulayıcı kanıtlar sınırlı"
        else:
            rich_status = HYPOTHESIS_INSUFFICIENT
            rich_reason = "Zengin karışım hipotezini değerlendirmek için yeterli kanıt yok"

        rich_supporting = list(dict.fromkeys(rich_supporting))
        rich_contradicting = list(dict.fromkeys(rich_contradicting))
        rich_missing = list(dict.fromkeys(rich_missing))

        hypotheses.append({
            "id": "FUEL_SYSTEM_RICH",
            "status": rich_status,
            "severity": HYPOTHESIS_WARNING,
            "title": "Fuel mixture appears rich",
            "supporting_evidence": rich_supporting,
            "contradicting_evidence": rich_contradicting,
            "missing_evidence": rich_missing,
            "reason": rich_reason,
            "context": ctx,
            "next_step": None
        })

        # 3. HYPOTHESIS: AIRFLOW_MEASUREMENT_ISSUE
        air_supporting = []
        air_contradicting = []
        air_missing = []

        if "AIRFLOW_LOW" in supported_ev_ids:
            air_supporting.append("AIRFLOW_LOW")
        if "AIRFLOW_HIGH" in supported_ev_ids:
            air_supporting.append("AIRFLOW_HIGH")
        if "SENSOR_CORRELATION_INCONSISTENT" in supported_ev_ids:
            air_supporting.append("SENSOR_CORRELATION_INCONSISTENT")
        if "ENGINE_RUNNING" in supported_ev_ids:
            air_supporting.append("ENGINE_RUNNING")

        if "AIRFLOW_LOW" in supported_ev_ids or "AIRFLOW_HIGH" in supported_ev_ids:
            if ("ENGINE_RUNNING" in supported_ev_ids) or ("SENSOR_CORRELATION_INCONSISTENT" in supported_ev_ids):
                air_status = HYPOTHESIS_SUPPORTED
                air_reason = "Motor çalışırken hava akış ölçümündeki anormallik hava ölçüm tutarsızlığı hipotezini destekliyor"
            else:
                air_status = HYPOTHESIS_POSSIBLE
                air_reason = "Hava akış anormalliği tespit edildi ancak motor çalışma durumu tam doğrulanamadı"
        else:
            air_status = HYPOTHESIS_INSUFFICIENT
            air_reason = "Hava akış ölçümüyle ilgili bir anormallik kanıtı bulunmuyor"

        air_supporting = list(dict.fromkeys(air_supporting))
        air_contradicting = list(dict.fromkeys(air_contradicting))
        air_missing = list(dict.fromkeys(air_missing))

        hypotheses.append({
            "id": "AIRFLOW_MEASUREMENT_ISSUE",
            "status": air_status,
            "severity": HYPOTHESIS_WARNING,
            "title": "Airflow measurement or airflow estimation appears inconsistent",
            "supporting_evidence": air_supporting,
            "contradicting_evidence": air_contradicting,
            "missing_evidence": air_missing,
            "reason": air_reason,
            "context": ctx,
            "next_step": None
        })

        # 4. HYPOTHESIS: COOLING_SYSTEM_ISSUE
        cool_supporting = []
        cool_contradicting = []
        cool_missing = []

        if "ECT_TOO_COLD" in supported_ev_ids:
            cool_supporting.append("ECT_TOO_COLD")
        if "ECT_TOO_HOT" in supported_ev_ids:
            cool_supporting.append("ECT_TOO_HOT")
        if "ENGINE_RUNNING" in supported_ev_ids:
            cool_supporting.append("ENGINE_RUNNING")

        if "ECT_TOO_COLD" in supported_ev_ids or "ECT_TOO_HOT" in supported_ev_ids:
            if "ENGINE_RUNNING" in supported_ev_ids:
                cool_status = HYPOTHESIS_SUPPORTED
                cool_reason = "Motor çalışırken soğutma sıvısı sıcaklığındaki sapma soğutma sistemi anormalliği hipotezini destekliyor"
            else:
                cool_status = HYPOTHESIS_POSSIBLE
                cool_reason = "Sıcaklık sapması tespit edildi ancak motor çalışma doğrulaması eksik"
        else:
            cool_status = HYPOTHESIS_INSUFFICIENT
            cool_reason = "Soğutma sıvısı sıcaklığı anormalliği kanıtı bulunmuyor"

        cool_supporting = list(dict.fromkeys(cool_supporting))
        cool_contradicting = list(dict.fromkeys(cool_contradicting))
        cool_missing = list(dict.fromkeys(cool_missing))

        hypotheses.append({
            "id": "COOLING_SYSTEM_ISSUE",
            "status": cool_status,
            "severity": HYPOTHESIS_WARNING,
            "title": "Engine coolant temperature behavior is abnormal",
            "supporting_evidence": cool_supporting,
            "contradicting_evidence": cool_contradicting,
            "missing_evidence": cool_missing,
            "reason": cool_reason,
            "context": ctx,
            "next_step": None
        })

        # 5. HYPOTHESIS: SENSOR_CORRELATION_ISSUE
        corr_supporting = []
        corr_contradicting = []
        corr_missing = []

        if "SENSOR_CORRELATION_INCONSISTENT" in supported_ev_ids:
            corr_supporting.append("SENSOR_CORRELATION_INCONSISTENT")
            corr_status = HYPOTHESIS_SUPPORTED
            corr_reason = "Çoklu sensör çapraz tutarlılık kontrolünde fiziksel/çalışma tutarsızlığı tespit edildi"
        else:
            corr_status = HYPOTHESIS_INSUFFICIENT
            corr_reason = "Sensörler arası belirgin bir tutarsızlık kanıtı bulunmuyor"

        corr_supporting = list(dict.fromkeys(corr_supporting))
        corr_contradicting = list(dict.fromkeys(corr_contradicting))
        corr_missing = list(dict.fromkeys(corr_missing))

        hypotheses.append({
            "id": "SENSOR_CORRELATION_ISSUE",
            "status": corr_status,
            "severity": HYPOTHESIS_WARNING,
            "title": "Multi-sensor correlation inconsistency detected",
            "supporting_evidence": corr_supporting,
            "contradicting_evidence": corr_contradicting,
            "missing_evidence": corr_missing,
            "reason": corr_reason,
            "context": ctx,
            "next_step": None
        })

        self.last_hypothesis_results = hypotheses
        return hypotheses

    def _recommend_diagnostic_tests(self, hypotheses=None) -> list:
        """
        Phase D-3: Aktif arıza hipotezleri ve eksik kanıtlardan deterministik test önerileri üretir.
        Onarım/parça değişimi tavsiyesi vermez, aktüatör çalıştırmaz, UDS/CAN yazma komutu üretmez.
        """
        hyp_list = hypotheses if hypotheses is not None else self._infer_fault_hypotheses()

        # İlgili hipotez durumlarını haritalandır
        hyp_by_id = {h["id"]: h for h in hyp_list if isinstance(h, dict)}
        supported_hyp_ids = {h["id"] for h in hyp_list if isinstance(h, dict) and h.get("status") == HYPOTHESIS_SUPPORTED}
        possible_hyp_ids = {h["id"] for h in hyp_list if isinstance(h, dict) and h.get("status") == HYPOTHESIS_POSSIBLE}

        # Eksik kanıtları topla
        all_missing_evidence = set()
        for h in hyp_list:
            if isinstance(h, dict):
                all_missing_evidence.update(h.get("missing_evidence", []))

        # Test havuzu (test catalog)
        test_candidates = {}

        def register_candidate(t_id: str, priority: str, safety: str, title: str, purpose: str, 
                               hyp_id: str, required_inputs: list, procedure: list, 
                               expected: str, interpretation: str, prerequisites: list = None,
                               is_optional: bool = False):
            if t_id not in test_candidates:
                test_candidates[t_id] = {
                    "id": t_id,
                    "status": TEST_OPTIONAL if is_optional else TEST_RECOMMENDED,
                    "priority": priority,
                    "safety": safety,
                    "title": title,
                    "purpose": purpose,
                    "hypotheses": [hyp_id] if hyp_id else [],
                    "required_inputs": list(required_inputs),
                    "procedure": list(procedure),
                    "expected_observation": expected,
                    "interpretation": interpretation,
                    "prerequisites": list(prerequisites) if prerequisites else [],
                    "blocking_reason": None,
                    "result": None
                }
            else:
                # Hipotezi birleştir (deduplication)
                if hyp_id and hyp_id not in test_candidates[t_id]["hypotheses"]:
                    test_candidates[t_id]["hypotheses"].append(hyp_id)
                # Önceliği yükselt (HIGH > MEDIUM > LOW)
                priority_ranks = {TEST_PRIORITY_HIGH: 1, TEST_PRIORITY_MEDIUM: 2, TEST_PRIORITY_LOW: 3}
                if priority_ranks.get(priority, 3) < priority_ranks.get(test_candidates[t_id]["priority"], 3):
                    test_candidates[t_id]["priority"] = priority
                if not is_optional:
                    test_candidates[t_id]["status"] = TEST_RECOMMENDED

        # 1. FUEL_SYSTEM_LEAN & FUEL_SYSTEM_RICH -> CHECK_FUEL_TRIM
        for h_id in ("FUEL_SYSTEM_LEAN", "FUEL_SYSTEM_RICH"):
            if h_id in supported_hyp_ids or h_id in possible_hyp_ids:
                is_supp = h_id in supported_hyp_ids
                register_candidate(
                    t_id="CHECK_FUEL_TRIM",
                    priority=TEST_PRIORITY_HIGH if is_supp else TEST_PRIORITY_MEDIUM,
                    safety=TEST_SAFE_READ,
                    title="Kısa ve uzun vadeli yakıt trimlerini yeniden gözlemle",
                    purpose="Yakıt trim düzeltmesinin rölanti ve sürüş koşullarında kalıcı olup olmadığını belirlemek.",
                    hyp_id=h_id,
                    required_inputs=["STFT", "LTFT", "ECT", "RPM"],
                    procedure=[
                        "Motorun normal çalışma sıcaklığına ulaşmasını sağlayın",
                        "Rölantide STFT ve LTFT değerlerini gözlemleyin",
                        "Sabit hızda (cruise) STFT ve LTFT değerlerini gözlemleyin"
                    ],
                    expected="Kalıcı pozitif veya negatif trim hipotezi destekler; trimlerin normale dönmesi şüpheyi azaltır.",
                    interpretation="Geçici yakıt adaptasyonunu kalıcı karışım probleminden ayırt etmeye yarar.",
                    prerequisites=["Motor çalışır durumda olmalı"],
                    is_optional=not is_supp
                )

        # 2. AIRFLOW_MEASUREMENT_ISSUE / LEAN / RICH -> CHECK_MAF_AIRFLOW_CORRELATION
        for h_id in ("AIRFLOW_MEASUREMENT_ISSUE", "FUEL_SYSTEM_LEAN", "FUEL_SYSTEM_RICH"):
            if h_id in supported_hyp_ids or h_id in possible_hyp_ids:
                is_air_supp = ("AIRFLOW_MEASUREMENT_ISSUE" in supported_hyp_ids)
                register_candidate(
                    t_id="CHECK_MAF_AIRFLOW_CORRELATION",
                    priority=TEST_PRIORITY_HIGH if is_air_supp else TEST_PRIORITY_MEDIUM,
                    safety=TEST_GUIDED_DRIVER,
                    title="MAF hava akış ölçümünü motor devri ve manifold basıncıyla karşılaştır",
                    purpose="Hava akış ölçümünün farklı devir ve yük şartlarında tutarlı tepki verip vermediğini belirlemek.",
                    hyp_id=h_id,
                    required_inputs=["MAF", "RPM", "MAP"],
                    procedure=[
                        "Rölantiden kademeli olarak 2500 RPM'e kadar devri artırın",
                        "MAF hava kütle akışındaki artışın gaz pedalı ve devirle uyumunu gözlemleyin"
                    ],
                    expected="Devir artışıyla uyumlu lineer MAF artışı hava ölçüm tutarlılığını gösterir.",
                    interpretation="Hava ölçüm sapması ile mekanik vakum/basınç problemlerini ayırt etmeye yardım eder.",
                    prerequisites=["MAF sensörü mevcut ve çalışır olmalı"],
                    is_optional=(not is_air_supp and h_id not in supported_hyp_ids)
                )

        # 3. MISSING EVIDENCE -> CHECK_ENGINE_STATE_AND_TEMPERATURE
        if "ENGINE_RUNNING" in all_missing_evidence or "ECT" in all_missing_evidence:
            register_candidate(
                t_id="CHECK_ENGINE_STATE_AND_TEMPERATURE",
                priority=TEST_PRIORITY_MEDIUM,
                safety=TEST_SAFE_READ,
                title="Motor çalışma durumunu ve sıcaklık kararlılığını doğrula",
                purpose="Tanısal çıkarımların sağlıklı yapılabilmesi için motorun çalıştığını ve işletim sıcaklığına ulaştığını doğrulamak.",
                hyp_id="",
                required_inputs=["RPM", "ECT"],
                procedure=[
                    "Motor devrinin rölanti bandında kararlı olduğunu teyit edin",
                    "Soğutma suyu sıcaklığının hedef işletim aralığına ulaştığını gözlemleyin"
                ],
                expected="Motorun kararlı rölantide ve hedef çalışma sıcaklığında olması.",
                interpretation="Eksik çalışma bağlamını tamamlar.",
                prerequisites=[],
                is_optional=False
            )

        # 4. AIRFLOW_MEASUREMENT_ISSUE -> CHECK_MAP_RESPONSE
        if "AIRFLOW_MEASUREMENT_ISSUE" in supported_hyp_ids or "AIRFLOW_MEASUREMENT_ISSUE" in possible_hyp_ids:
            register_candidate(
                t_id="CHECK_MAP_RESPONSE",
                priority=TEST_PRIORITY_MEDIUM,
                safety=TEST_GUIDED_DRIVER,
                title="Manifold mutlak basınç (MAP) tepkisini gözlemle",
                purpose="Gaz kelebeği hareketlerinde manifold vakum/basınç değişiminin tutarlılığını test etmek.",
                hyp_id="AIRFLOW_MEASUREMENT_ISSUE",
                required_inputs=["MAP", "TPS", "RPM"],
                procedure=[
                    "Farklı gaz kelebeği açılarında MAP değerinin değişimini izleyin"
                ],
                expected="Gaz açıldığında MAP basıncının atmosferik basınca yaklaşması beklenir.",
                interpretation="Manifold basınç sensörü tepkisini doğrular.",
                prerequisites=["MAP sensörü mevcut olmalı"],
                is_optional="AIRFLOW_MEASUREMENT_ISSUE" not in supported_hyp_ids
            )

        # 5. COOLING_SYSTEM_ISSUE -> CHECK_ECT_WARMUP & CHECK_ECT_STABILITY
        if "COOLING_SYSTEM_ISSUE" in supported_hyp_ids or "COOLING_SYSTEM_ISSUE" in possible_hyp_ids:
            is_cool_supp = "COOLING_SYSTEM_ISSUE" in supported_hyp_ids
            register_candidate(
                t_id="CHECK_ECT_WARMUP",
                priority=TEST_PRIORITY_HIGH if is_cool_supp else TEST_PRIORITY_MEDIUM,
                safety=TEST_SAFE_READ,
                title="Soğutma suyu sıcaklık ısınma eğrisini gözlemle",
                purpose="Motorun soğuk çalışmadan hedef sıcaklığa ulaşma süresini ve termal kararlılığını izlemek.",
                hyp_id="COOLING_SYSTEM_ISSUE",
                required_inputs=["ECT", "RPM"],
                procedure=[
                    "Motoru çalıştırarak ECT değerinin hedef sıcaklığa yükselişini izleyin"
                ],
                expected="Düzenli ve kademeli sıcaklık artışı ile hedef sıcaklıkta kararlı kalması beklenir.",
                interpretation="Termal döngü anormalliklerini belirler.",
                prerequisites=["Motor çalışır durumda olmalı"],
                is_optional=not is_cool_supp
            )
            register_candidate(
                t_id="CHECK_ECT_STABILITY",
                priority=TEST_PRIORITY_MEDIUM,
                safety=TEST_SAFE_READ,
                title="Çalışma sıcaklığında ECT kararlılığını doğrula",
                purpose="Motor sıcakken ECT dalgalanması veya aşırı soğuma olup olmadığını belirlemek.",
                hyp_id="COOLING_SYSTEM_ISSUE",
                required_inputs=["ECT"],
                procedure=[
                    "Çalışma sıcaklığına ulaşmış motorda sürüş ve dur-kalk esnasında ECT stabilitesini izleyin"
                ],
                expected="ECT değerinin hedef sıcaklık etrafında dar bir tolerans bandında kalması.",
                interpretation="Aşırı soğuma veya aşırı ısınma eğilimlerini ayırt eder.",
                prerequisites=[],
                is_optional=not is_cool_supp
            )

        # 6. SENSOR_CORRELATION_ISSUE -> CHECK_SENSOR_REPEATABILITY
        if "SENSOR_CORRELATION_ISSUE" in supported_hyp_ids or "SENSOR_CORRELATION_ISSUE" in possible_hyp_ids:
            is_corr_supp = "SENSOR_CORRELATION_ISSUE" in supported_hyp_ids
            register_candidate(
                t_id="CHECK_SENSOR_REPEATABILITY",
                priority=TEST_PRIORITY_HIGH if is_corr_supp else TEST_PRIORITY_MEDIUM,
                safety=TEST_SAFE_READ,
                title="Sensör çapraz tutarlılığını aynı koşulda tekrar test et",
                purpose="Algılanan sensör uyumsuzluğunun geçici bir anomali mi yoksa kalıcı bir sinyal hatası mı olduğunu teyit etmek.",
                hyp_id="SENSOR_CORRELATION_ISSUE",
                required_inputs=["RPM", "SPEED"],
                procedure=[
                    "Uyumsuzluğun gerçekleştiği sürüş/durma koşulunu güvenli şekilde tekrarlayın",
                    "Sensör ölçümlerinin eşzamanlı tutarlılığını izleyin"
                ],
                expected="Koşul tekrarında aynı uyumsuzluğun tekrarlanması kalıcı sinyal tutarsızlığını doğrular.",
                interpretation="Anlık veri sıçramaları ile gerçek sinyal uyumsuzluklarını ayırt eder.",
                prerequisites=[],
                is_optional=not is_cool_supp if 'is_cool_supp' in locals() else False
            )

        # Prerequisite / Girdi Geçerlilik Kontrolü (TEST_BLOCKED denetimi)
        final_recommendations = []
        for t_id, item in test_candidates.items():
            blocked = False
            blocking_reason = None
            for req_sensor in item["required_inputs"]:
                s_entry = self.data_cache.get(req_sensor)
                if not isinstance(s_entry, dict):
                    blocked = True
                    blocking_reason = f"Gerekli {req_sensor} verisi önbellekte bulunmuyor"
                    break
                if s_entry.get("status") != STATUS_VALID or s_entry.get("quality") in (QUALITY_ERROR, QUALITY_INVALID, QUALITY_IMPLAUSIBLE):
                    blocked = True
                    blocking_reason = f"Güvenilir {req_sensor} verisi mevcut değil ({s_entry.get('quality')})"
                    break

            if blocked:
                item["status"] = TEST_BLOCKED
                item["blocking_reason"] = blocking_reason
            else:
                item["blocking_reason"] = None

            final_recommendations.append(item)

        # Sıralama: Güvenlik Seviyesi (SAFE_READ -> GUIDED_DRIVER -> WORKSHOP) -> Öncelik (HIGH -> MEDIUM -> LOW) -> Test ID
        safety_order = {TEST_SAFE_READ: 1, TEST_GUIDED_DRIVER: 2, TEST_WORKSHOP: 3, TEST_ACTUATION: 4}
        priority_order = {TEST_PRIORITY_HIGH: 1, TEST_PRIORITY_MEDIUM: 2, TEST_PRIORITY_LOW: 3}

        final_recommendations.sort(key=lambda x: (
            safety_order.get(x["safety"], 99),
            priority_order.get(x["priority"], 99),
            x["id"]
        ))

        self.last_test_recommendations = final_recommendations
        return final_recommendations

    def tek_veri_oku(self, target_list=None, phase="UNKNOWN"):
        """
        V106: Heartbeat & Freshness Report
        Returns: (data_dict, fresh_count)
        """
        self._loop_counter += 1
        
        # Freshness Counter
        fresh_count = 0

        if not self.ser or not self.ser.is_open:
            if not self.baglanti_kontrol(): 
               return self._bos_veri_dondur(), 0

        # V91: ZERO DROP CACHING — Zaman damgalı cache'den "taze" değerleri oku
        # V111: Stale Cache Koruma — 2 saniyeden eski veriler None olarak döner
        _stale_limit = 2.0
        _now = time.time()
        data = {}
        for key, entry in self.data_cache.items():
            if isinstance(entry, dict):
                age = _now - entry.get("time", 0.0)
                if age <= _stale_limit or entry["time"] == 0.0:
                    # Taze veri (veya hiç gelmemiş → None zaten)
                    data[key] = entry["val"]
                else:
                    # Bayat veri: None döndür, önbelleği kirletme
                    data[key] = None
            else:
                # Eski format uyumluluğu (geçiş dönemi koruması)
                data[key] = entry

        # V111: Watchdog — V112: Sabit 5s yerine protokole göre adaptif self.watchdog_limit
        _now = time.time()
        limit = self.watchdog_limit
        if self.test_start_time > 0 and (_now - self.test_start_time) < 30:
            limit = 45.0  # İlk 30 saniye boyunca 45 saniye tolerans

        if (_now - self.last_valid_data_time) > limit:
            log_flush(f"WATCHDOG: {limit:.1f}s veri yok — baglanti_kontrol tetiklendi")
            print(f"[WATCHDOG] ELM327 donmus olabilir, port yeniden baslatiliyor... (Limit: {limit:.1f}s)")
            self.baglanti_kontrol()
            self.last_valid_data_time = time.time()  # Döngüyü resetle
        
        if self._loop_counter % 20 == 0:
            res = self.komut_gonder("AT RV")
            if res and "V" in res[0]:
                try: 
                    volt = float(res[0].replace("V",""))
                    data["Voltaj"] = volt
                    # V111/V204: Timestamp & Quality ile kaydet
                    self._update_sensor_cache("Voltaj", volt, status=STATUS_VALID, source="ATRV")
                except Exception as e:
                    log_flush(f"[DATA_READ_ERROR] Voltaj degeri ('AT RV') parse edilemedi: {e}")

        # Dinamik CSV PID'leri statik sözlüğe ekle (mevcut PID'ler öncelikli)
        pids = {**self.csv_pids, **{
            "0104": ("LOAD", lambda x: x[0] * 100 / 255),
            "0105": ("ECT", lambda x: x[0] - 40),
            "0106": ("STFT", lambda x: (x[0] - 128) * 100 / 128),
            "0107": ("LTFT", lambda x: (x[0] - 128) * 100 / 128),
            "010B": ("MAP", lambda x: x[0]),
            "010C": ("RPM", lambda x: (x[0]*256 + x[1]) / 4),
            "010D": ("SPEED", lambda x: x[0]),
            "010E": ("TIMING_ADV", lambda x: (x[0] / 2) - 64), 
            "010F": ("IAT", lambda x: x[0] - 40),
            "0110": ("MAF", lambda x: (x[0]*256 + x[1]) / 100),
            "0111": ("TPS", lambda x: x[0] * 100 / 255),
            "0101": ("MONITORS", _decode_0101),
            "011C": ("OBD_STD", lambda x: "OBD-II" if x[0]==1 else ("EOBD" if x[0]==6 else ("JOBD" if x[0]==8 else f"STD:{x[0]}"))),
            "0151": ("FUEL_TYPE", lambda x: "Gasoline" if x[0]==1 else ("Diesel" if x[0]==4 else ("LPG" if x[0]==5 else ("Hybrid" if x[0] in [8,9,22,23] else f"TYPE:{x[0]}")))),
            "0114": ("O2_B1S1_V", lambda x: x[0] * 0.005 if len(x)>0 else None),
            "0115": ("O2_B1S2_V", lambda x: x[0] * 0.005 if len(x)>0 else None),
            # --- GÖREV 2: Wideband O2 Formül Güncellemesi (SAE J1979) ---
            # 0124: Hem Lambda (Equivalence Ratio) hem de Voltaj döndüren yapı
            "0124": ("O2_WR_B1S1", lambda x: {"lambda": (x[0] * 256 + x[1]) / 32768.0, "voltage": (x[2] * 256 + x[3]) * 8.0 / 65535.0} if len(x) >= 4 else None),
            # 0134: Hem Lambda hem de Akım (mA) döndüren yapı
            "0134": ("O2_WR_B1S1_I", lambda x: {"lambda": (x[0] * 256 + x[1]) / 32768.0, "current_ma": ((x[2] * 256 + x[3]) / 256.0) - 128.0} if len(x) >= 4 else None),
            "011F": ("RUN_TIME", lambda x: (x[0]*256 + x[1])), 
            "0121": ("DIST_Travel", lambda x: (x[0]*256 + x[1])), 
            "0123": ("FUEL_RAIL_PRESS", lambda x: (x[0]*256 + x[1]) * 10), 
            "012C": ("EGR_CMD", lambda x: x[0] * 100 / 255), 
            "012D": ("EGR_ERROR", lambda x: (x[0] - 128) * 100 / 128), 
            "0133": ("BARO", lambda x: x[0]), 
            "013C": ("CAT_TEMP_B1S1", lambda x: ((x[0]*256 + x[1]) / 10) - 40), 
            "0142": ("MODULE_VOLT", lambda x: (x[0]*256 + x[1]) / 1000), 
            "0146": ("AMBIENT_TEMP", lambda x: x[0] - 40), 
            "015C": ("ENGINE_OIL_TEMP", lambda x: x[0] - 40),             # SAE J1979 — Motor Yağ Sıcaklığı
            "015E": ("ENGINE_FUEL_RATE", lambda x: (x[0]*256 + x[1]) / 20), # SAE J1979 — Anlık Yakıt Debisi (L/h)
            "01A6": ("ODOMETER", lambda x: (x[0]*(2**24) + x[1]*(2**16) + x[2]*(2**8) + x[3]) / 10), # SAE J1979 — Kilometre (km)
            "0163": ("TORQUE", lambda x: (x[0]*256 + x[1])), 
            "017F": ("EGR_SYSTEM", lambda x: x[0]), # Placeholder
            "0170": ("BOOST_CMD", lambda x: (x[0]*256 + x[1]) * 0.03125), 
            "017A": ("DPF_DELTA_PRESS", lambda x: (x[0]*256 + x[1]) * 0.1), 
            "0178": ("DPF_TEMP", lambda x: ((x[0]*256 + x[1]) / 10) - 40), 
            "0183": ("NOx_SENSOR", lambda x: (x[0]*256 + x[1])), 
        }}

        # V97: Hayalet Sensör Yakalayıcı (Ghost Sensor Catcher)
        # Listede olup FAST veya MEDIUM içinde olmayanları buraya al
        SLOW_PIDS = [p for p in self.desteklenen_pidler if p not in self.FAST and p not in self.MEDIUM]

        target_list_final = []
        
        if target_list:
             target_list_final = target_list
        elif self.is_slow_protocol:
            if phase == "CRANKING":
                target_list_final = ["010C"] 
            elif phase == "LOAD":
                if self._loop_counter % 5 == 0:
                    target_list_final = [p for p in self.desteklenen_pidler if p in self.FAST or p in self.MEDIUM]
                else:
                    target_list_final = [p for p in self.desteklenen_pidler if p in self.FAST]
            else:
                # V97: Yavaş Protokol Döngüsü (Slow Loop)
                if self._loop_counter % 20 == 0:
                     # 20 döngüde bir "Her Şeyi" oku (SLOW_PIDS dahil)
                     target_list_final = [p for p in self.desteklenen_pidler if p in self.FAST or p in self.MEDIUM or p in SLOW_PIDS]
                elif self._loop_counter % 4 == 0:
                    target_list_final = [p for p in self.desteklenen_pidler if p in self.FAST or p in self.MEDIUM]
                else:
                    target_list_final = [p for p in self.desteklenen_pidler if p in self.FAST]
        else:
            # CAN Protokolü (Hızlı)
            if self._loop_counter % 20 == 0:
                target_list_final = self.desteklenen_pidler # Hepsini oku
            else:
                target_list_final = [p for p in self.desteklenen_pidler if p in self.FAST or p in self.MEDIUM]
        
        # V99.5 / Madde 3: 3-Strike Blacklist — Başarısız sensörler kalıcı olarak çıkarılır
        # Immunity: RPM (010C), ECT (0105), MAP (010B) asla listeden çıkmaz
        immune_pids = ["010C", "0105", "010B"]
        to_remove = [
            p for p in target_list_final
            if p not in immune_pids and self.failed_pids.get(p, 0) >= 10
        ]
        if to_remove:
            # Kalıcı olarak desteklenen_pidler listesinden de çıkar
            for p in to_remove:
                if p in self.desteklenen_pidler:
                    self.desteklenen_pidler.remove(p)
                    log_flush(f"BLACKLIST-PERM: {p} kalıcı olarak kara listeye alındı.")
        target_list_final = [p for p in target_list_final if p not in to_remove]
        
        for pid in target_list_final:
            if pid not in pids: continue
            
            # KWP Hız Optimizasyonu
            if self.is_slow_protocol: time.sleep(0.20)

            # V114: Multi-Mode Extended PID tespiti (Mode 21, 22, 2C)
            # 21: Genel Extended Mfr, 22: SAE J2190 Mfr Specific, 2C: Defined-by-Memory PIDs
            is_extended_mode = len(pid) >= 4 and pid.upper()[:2] in ["21", "22", "2C"]
            if is_extended_mode:
                self._ensure_session(self.current_header)
                t_out = (1.0 if self.is_can else 5.0) * 2  # Extended modlar: 2x timeout
            else:
                t_out = 0.5 if self.is_can else 2.5  # Standart Mode 01 timeout
            cmd_result = self.komut_gonder(pid, timeout=t_out)
            time.sleep(0.03 if self.is_can else 0.1)
            if is_extended_mode:
                self._classify_nrc(cmd_result, context_pid=pid)
            
            # V99.5: Boş veya hatalı yanıt kontrolü
            if not cmd_result or len(cmd_result) == 0:
                self.failed_pids[pid] = self.failed_pids.get(pid, 0) + 1
                fail_count = self.failed_pids[pid]
                if fail_count >= 10 and pid not in immune_pids:
                    log_flush(f"STRIKEOUT: {pid} {fail_count} kez hata verdi, kara listeye alınıyor.")
                continue
            
            # Geçerli veri döndü: None kontrolü de yap (boş parse)
            # Tam None dönüşü de strikeout sayılır
            parsed_any = False
            
            pid_response_ok = False
            for l in cmd_result:
                # V92: O2 & Parser Hardening
                if any(x in l for x in ["SEARCHING", "BUS INIT", "STOPPED", "NO DATA"]): continue 
                
                # V106: Freshness Check (Hex Response Validation)
                # 41 + PID veya CAN header ile
                if "41" in l or (len(l) > 4 and l != pid):
                    pid_response_ok = True

                try:
                    val = self.parse_pid_line(l, pid, pids[pid])
                    if val is not None:
                         name = pids[pid][0]
                         if name == "RPM" and val > 16000: pass
                         elif name == "MONITORS":
                             data["MONITORS"] = val
                             data["MIL"] = val.get("MIL", False)
                             self._update_sensor_cache("MIL", data["MIL"], status=STATUS_VALID, source="MODE01")
                             self._update_sensor_cache("MONITORS", val, status=STATUS_VALID, source="MODE01")
                             self.failed_pids[pid] = 0
                             parsed_any = True
                         else:
                             data[name] = val
                             # V111/V204: Timestamp & Quality ile cache'e yaz
                             self._update_sensor_cache(name, val, status=STATUS_VALID, source="MODE01")
                             # Başarılı okuma, strikeout sıfırla
                             self.failed_pids[pid] = 0
                             parsed_any = True
                except Exception as e:
                    log_flush(f"[DATA_READ_ERROR] PID parse hatası (pid={pid}): {e}")
            
            # Madde 3: Geçerli cevap geldi ama parse hiç sonuç vermedi = None sayar
            if pid_response_ok and not parsed_any:
                self.failed_pids[pid] = self.failed_pids.get(pid, 0) + 1
            
            if pid_response_ok:
                fresh_count += 1

        # --- GÖREV 3: ÖZEL PID POLLING ---
        self.custom_pid_counter += 1
        if self.custom_pids and self.custom_pid_counter % 5 == 0:
            for mode_pid, info in self.custom_pids.items():
                name = info["isim"]
                formula = info["formul"]
                header = info["header"]
                
                # V135.1 + Multi-ECU Session: Header değiştir VE o header için session garanti et
                if self.current_header != header:
                    self.komut_gonder(f"AT SH {header}")
                    self.current_header = header
                self._ensure_session(header)

                res = self.komut_gonder(mode_pid)
                res_str = "".join(res).upper()
                self._classify_nrc(res, context_pid=mode_pid)
                
                if res and self.last_response_status != STATUS_NRC and "NO DATA" not in res_str:
                    payload_str = res_str
                    for hdr in ("7E8", "7E9", "7EA", "7EB", "7EC", "7ED", "7EE", "7EF", "7E0", "7E1", "7E2", "7E3", "7E4", "7E5", "7E6", "7E7", "7DF"):
                        if payload_str.startswith(hdr):
                            payload_str = payload_str[len(hdr):]
                            break

                    # 62 + PID (4 hane) = 6 hane (3 byte) prefix.
                    # Örn: 22336A -> 62336A
                    prefix = f"62{mode_pid[2:]}"
                    if payload_str.startswith(prefix):
                        try:
                            data_hex = payload_str[len(prefix):]
                            d = [int(data_hex[i:i+2], 16) for i in range(0, len(data_hex), 2)]
                            
                            # V136: Security Upgrade - SAFE PARSER (No eval)
                            context = {
                                "d": d, "BIT": self.safe_parser.functions["BIT"],
                                "SIGNED": self.safe_parser.functions["SIGNED"]
                            }
                            # Map A,B,C to d[0],d[1],d[2] in context
                            for i, val in enumerate(d):
                                if i < 26: context[chr(65+i)] = val
                                
                            hesaplanan = self.safe_parser.evaluate(formula, context)
                            
                            if hesaplanan is not None:
                                data[name] = hesaplanan
                                self._update_sensor_cache(name, hesaplanan, status=STATUS_VALID, quality=QUALITY_GOOD, source="MODE22")
                                self.last_did_match_info = None
                                log_flush(f"Custom PID OK: {name}={hesaplanan}")
                            else:
                                log_flush(f"Custom PID Math Error ({name}): Formula failed safety check or calculation")
                        except Exception as e:
                            log_flush(f"[CUSTOM_PID_ERROR] Özel PID hatası ({name}): {e}")
                    elif prefix in payload_str:
                        fallback_idx = payload_str.find(prefix)
                        self.last_did_match_info = {
                            "expected": prefix,
                            "found_at": fallback_idx,
                            "reason": "not_at_start"
                        }
                        self.last_response_status = STATUS_DID_MISMATCH
                        log_flush(f"[DID_MISMATCH] Custom PID={mode_pid} beklenen='{prefix}' konumda değil (found_at={fallback_idx}), reddedildi")
            
            # Polling sonrası header'ı standart Broadcast moduna geri al
            if self.current_header != "7DF":
                self.komut_gonder("AT SH 7DF")
                self.current_header = "7DF" # V136.1: Sync Fix

        # V111: Watchdog güncelle — en az 1 fresh veri geldiyse sayacı sıfırla
        if fresh_count > 0:
            self.last_valid_data_time = time.time()

        # --- WIDEBAND (FSI/GDI) O2 FALLBACK: A Planı → B Planı (GÜNCELLENDİ) ---
        # Eğer standart O2 sensör voltajı (0114) okunmadıysa, Wideband sensörleri dene
        _cache_o2 = self.data_cache.get("O2_B1S1_V")
        _cache_o2_val = _cache_o2["val"] if isinstance(_cache_o2, dict) else _cache_o2
        if data.get("O2_B1S1_V") is None and _cache_o2_val is None:
            for wb_pid in ["0124", "0134"]:
                if self.failed_pids.get(wb_pid, 0) >= 10: continue
                if wb_pid not in pids: continue
                
                t_out = 0.5 if self.is_can else 2.5
                wb_result = self.komut_gonder(wb_pid, timeout=t_out)
                if not wb_result:
                    self.failed_pids[wb_pid] = self.failed_pids.get(wb_pid, 0) + 1
                    continue

                wb_parsed = False
                for wb_line in wb_result:
                    if any(x in wb_line for x in ["SEARCHING", "BUS INIT", "STOPPED", "NO DATA"]): continue
                    try:
                        wb_val = self.parse_pid_line(wb_line, wb_pid, pids[wb_pid])
                        if wb_val is not None:
                            # Her iki durumda da yeni, zengin veri yapısını tam olarak kaydet
                            pid_name = pids[wb_pid][0]
                            data[pid_name] = wb_val
                            self._update_sensor_cache(pid_name, wb_val, status=STATUS_VALID, source="MODE01")
                            
                            # Eski sistemlerle uyumluluk için O2_B1S1_V'ye bir değer ata
                            display_val = 0.0
                            if 'voltage' in wb_val:
                                display_val = wb_val['voltage']
                                data["O2_B1S1_V"] = display_val
                                self._update_sensor_cache("O2_B1S1_V", display_val, status=STATUS_VALID, source="MODE01")
                            
                            log_flush(f"WB-FALLBACK: {pid_name} okundu. Uyumlu değer: {display_val:.3f}V")
                            self.failed_pids[wb_pid] = 0
                            wb_parsed = True
                            break 
                    except Exception as e:
                        log_flush(f"[DATA_READ_ERROR] Wideband O2 fallback hatası (pid={wb_pid}): {e}")
                        pass
                
                if wb_parsed:
                    break
                else:
                    self.failed_pids[wb_pid] = self.failed_pids.get(wb_pid, 0) + 1

        return data, fresh_count

    def parse_pid_line(self, line, pid, pid_info):
        """
        V111: Unified PID Parser — Mode 01 (41xx) ve Mode 22 (62xx) destekler.
        V111 EK: Multi-ECU Karışması Filtresi — 7E9/7EA şanzıman/yardımcı modül
        yanıtları Mode 01 sorgularında Motor ECU verisini bozar → yoksayılır.
        Sadece Motor ECU (7E8) veya header'sız standart 41xx yanıtları kabul edilir.
        """
        try:
             name, func = pid_info
             hex_str = line.replace(" ", "").upper()
             
             if hex_str.startswith(('7E0', '7E1', '7E8', '7E9')): hex_str = hex_str[3:]

             # V114: Multi-ECU Filtresi — Yalnızca standart (Mode 01) sorgularında uygula
             # 7E9 = TCM (Transmission), 7EA = Hybrid/Yardımcı modül
             # Bu başlıklar standart OBD2 Motor verisini kirletir
             _is_extended_mode = len(pid) >= 4 and pid.upper()[:2] in ["21", "22", "2C"]
             if not _is_extended_mode:
                 _REJECTED_HEADERS = ("7E9", "7EA")
                 for rh in _REJECTED_HEADERS:
                     if hex_str.startswith(rh):
                         logging.info(f"MULTI-ECU-FILTER: {rh} kaynagından gelen yanıt reddedildi (pid={pid})")
                         return None

             # V115: Aveo / Sirius D42 Block Parser (Mode 21 02)
             # Yanıt 61 02 ile başlıyorsa özel block parser devreye girer
             if _is_extended_mode and hex_str.find("6102") != -1:
                 # block_parser otomatik data atar, bu yüzden None döner (tek değer değil)
                 self.block_parser(hex_str)
                 return None

             # V114: Evrensel Multi-Mode Parser (Mode 21→61, 22→62, 2C→6C)
             # Kural: ECU'nun olumlu yanıt prefix'i = sorgu modu + 0x40
             # Örn: 21→61, 22→62, 2C→6C
             if _is_extended_mode:
                 # Dinamik target oluştur: respond_mode_hex + pid'in PID kısmı
                 target = f"{hex(int(pid[:2], 16) + 0x40)[2:].upper()}{pid[2:4].upper()}"

                 # V201: Anchored match — target, hex_str'in EN BAŞINDA olmalı (header zaten strip edildi).
                 # Eskisi gibi serbest find() yerine, beklenen konumda gerçekten var mı diye bakılır.
                 if hex_str.startswith(target):
                     idx = 0
                 else:
                     # Beklenen konumda yok — belki NRC ya da bozuk frame. Serbest arama ile
                     # teşhis amaçlı konumunu bul (parse ETMEYECEĞİZ, sadece loglayacağız).
                     fallback_idx = hex_str.find(target)
                     self.last_did_match_info = {
                         "expected": target,
                         "found_at": fallback_idx if fallback_idx != -1 else None,
                         "reason": "not_at_start" if fallback_idx != -1 else "not_found",
                     }
                     if fallback_idx == -1:
                         return None
                     # Beklenen DID string'i var ama başta değil — güvenilir değil, reddet.
                     log_flush(f"[DID_MISMATCH] pid={pid} beklenen='{target}' konumda değil (found_at={fallback_idx}), reddedildi")
                     self.last_response_status = STATUS_DID_MISMATCH
                     return None

                 self.last_did_match_info = None  # Başarılı anchored match, önceki teşhisi temizle
                 # idx'den sona tüm hex'i byte listesine dök
                 full_payload_hex = hex_str[idx:]  # '61/62/6CXXYYZZ...' formatı
                 all_bytes = []
                 for i in range(0, len(full_payload_hex), 2):
                     try:
                         all_bytes.append(int(full_payload_hex[i:i+2], 16))
                     except Exception as e:
                         log_flush(f"[PID_PARSE_ERROR] Multi-mode byte parse hatası: {e}")
                 # İlk 3 byte = servis yanıt kodu (1) + PID iki byte (2) → atla
                 # Gerçek veri byte'ları [3:] ile alınır
                 bytes_val = all_bytes[3:]
                 if bytes_val:
                     return func(bytes_val)
             else:
                 # Standart Mode 01 parser (41 + pid son 2 hex) — KESİNLİKLE DOKUNULMAZ
                 target = f"41{pid[2:]}"
                 idx = hex_str.find(target)
                 if idx != -1:
                     data_hex = hex_str[idx+4:]
                     bytes_val = []
                     for i in range(0, len(data_hex), 2):
                         try:
                             bytes_val.append(int(data_hex[i:i+2], 16))
                         except Exception as e:
                             log_flush(f"[PID_PARSE_ERROR] Standart mode byte parse hatası: {e}")
                     if len(bytes_val) > 0:
                         return func(bytes_val)
        except Exception as e:
            log_flush(f"[PID_PARSE_ERROR] Genel ayrıştırma hatası (pid={pid}): {e}")
            return None
        return None

    def _classify_nrc(self, response_lines: list, context_pid: str = "") -> str | None:
        """
        komut_gonder() dönüşünü tarar, UDS negative response (7F <service> <NRC>) var mı bakar.
        Context PID/service ile 3-byte yapıyı doğrular, payload verisi içindeki 0x7F byte'larını
        yanlışlıkla NRC olarak sınıflandırmaz.
        Varsa NRC kodunu ayrıştırıp dbCSV/nrc_log.csv'ye yazar, kodu string olarak döner.
        Yoksa None döner (pozitif yanıt / cevap yok / tanınmayan format).
        """
        if not response_lines:
            return None

        expected_service = None
        if context_pid:
            cleaned_ctx = context_pid.strip().replace(" ", "").upper()
            if cleaned_ctx.startswith("0X"):
                cleaned_ctx = cleaned_ctx[2:]
            if len(cleaned_ctx) >= 2 and all(c in "0123456789ABCDEF" for c in cleaned_ctx[:2]):
                expected_service = cleaned_ctx[:2]

        for line in response_lines:
            s = line.replace(" ", "").upper()
            # 11-bit CAN header strip (7E8..7EF, 7E0..7E7, 7DF)
            for hdr in ("7E8", "7E9", "7EA", "7EB", "7EC", "7ED", "7EE", "7EF", "7E0", "7E1", "7E2", "7E3", "7E4", "7E5", "7E6", "7E7", "7DF"):
                if s.startswith(hdr):
                    s = s[len(hdr):]
                    break

            # ISO-TP Single Frame length byte strip (örn: 037F2231 -> 7F2231)
            if len(s) >= 8 and s[:2] in ("03", "04", "05", "06", "07") and s[2:4] == "7F":
                s = s[2:]

            if s.startswith("7F") and len(s) >= 6:
                resp_service = s[2:4]
                nrc_code = s[4:6]
                if expected_service and resp_service != expected_service:
                    continue
                if nrc_code in NRC_MAP or (len(nrc_code) == 2 and all(c in "0123456789ABCDEF" for c in nrc_code)):
                    nrc_desc = NRC_MAP.get(nrc_code, f"Unknown NRC 0x{nrc_code}")
                    self.last_response_status = STATUS_NRC

                    did_name = context_pid
                    if hasattr(self, "csv_pids") and context_pid in self.csv_pids:
                        did_name = self.csv_pids[context_pid][0]

                    log_flush(f"[NRC] header={self.current_header} pid={context_pid} ({did_name}) -> 0x{nrc_code} {nrc_desc}")
                    self._log_nrc_to_csv(context_pid, did_name, nrc_code, nrc_desc)
                    return nrc_code

        return None

    def _log_nrc_to_csv(self, pid, did_name, nrc_code, nrc_desc):
        """NRC olaylarini dbCSV/nrc_log.csv dosyasina append eder (reverse-engineering kaydı)."""
        try:
            log_path = os.path.join(DBCSV_DIR, "nrc_log.csv")
            file_exists = os.path.exists(log_path)
            os.makedirs(DBCSV_DIR, exist_ok=True)
            with open(log_path, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["timestamp", "header", "pid", "did_name", "nrc_code", "nrc_description"])
                writer.writerow([time.ctime(), self.current_header, pid, did_name, nrc_code, nrc_desc])
        except Exception as e:
            log_flush(f"[NRC_LOG_ERROR] CSV yazma hatasi: {e}")

    def _ensure_session(self, header: str) -> bool:
        """
        Verilen header için UDS Extended Diagnostic Session (1003) açık mı kontrol eder,
        değilse açar veya süresi dolduysa yeniler. Mode 22/21/2C okumalarından önce çağrılmalı.
        Returns True if the session is (now) considered open, False if it was refused/ambiguous.
        """
        header = header.strip().upper()
        now = time.time()

        if header in self.ecu_sessions and (now - self.ecu_sessions[header]) <= self.session_timeout:
            # Session zaten taze, sadece dokunma (wire trafiği yok)
            self.ecu_sessions[header] = now
            return True

        if self.current_header != header:
            self.komut_gonder(f"AT SH {header}", timeout=1.0)
            self.current_header = header

        res = self.komut_gonder("1003", timeout=1.0)
        res_str = "".join(res).upper()

        if "7F10" in res_str:
            log_flush(f"[SESSION_FAIL] {header} '1003' reddetti (NRC 7F10): {res_str}")
            self.ecu_sessions.pop(header, None)
            return False
        elif "5003" in res_str:
            self.ecu_sessions[header] = now
            log_flush(f"V200: ExtendedDiagSession (1003) açıldı/yenilendi -> header={header}")
            return True
        else:
            log_flush(f"[SESSION_FAIL] {header} '1003' belirsiz cevap: {res_str}")
            self.ecu_sessions.pop(header, None)
            return False

    def header_set(self, header_id: str):
        """
        V110: Mode 22 için CAN Header Ayarlayıcı.
        'AT SH <header_id>' komutu gönderir.
        Örn: header_set('7E1') → şanzımana yönlendir
             header_set('7DF') → standart broadcast moduna dön
        """
        cmd = f"AT SH {header_id.strip().upper()}"
        self.komut_gonder(cmd, timeout=1.0)
        self.current_header = header_id.strip().upper()  # V135.1: Update tracking
        log_flush(f"V110 Header Set: {header_id}")

    def manual_did_probe(self, did: str, header: str = None, formula: str = None) -> dict:
        """
        V203: Manual DID Probe (DID Teşhis ve Doğrulama Aracı)
        Belirtilen DID ve ECU header'ına UDS Mode 22 sorgusu gönderir,
        yanıtı analiz eder, NRC / DID_MISMATCH / VALID durumlarını ayıklar
        ve opsiyonel olarak formül ile çözer.
        """
        # 1. Input Normalization & Validation
        raw_did = str(did).strip().replace(" ", "").upper()
        if raw_did.startswith("0X"):
            raw_did = raw_did[2:]
        if raw_did.startswith("22") and len(raw_did) == 6:
            raw_did = raw_did[2:]

        if len(raw_did) != 4 or not all(c in "0123456789ABCDEF" for c in raw_did):
            log_flush(f"[MANUAL_DID_PROBE] Geçersiz DID formatı: '{did}' (4 haneli hex bekleniyor)")
            return {
                "ok": False,
                "status": "INVALID_INPUT",
                "request": None,
                "did": raw_did,
                "header": header,
                "response": None,
                "payload_hex": None,
                "payload_bytes": [],
                "decoded_value": None,
                "nrc": None,
                "nrc_desc": None,
                "error": f"Geçersiz DID formatı: '{did}'. 4 basamaklı onaltılık (hex) değer giriniz (örn: '1640').",
            }

        target_did = raw_did
        cmd = f"22{target_did}"

        # 2. Header & Session Handling
        initial_header = self.current_header
        target_header = header.strip().upper() if header else (self.current_header if self.current_header != "7DF" else "7E0")
        switched_header = False

        result = {
            "ok": False,
            "status": self.last_response_status,
            "request": cmd,
            "did": target_did,
            "header": target_header,
            "response": None,
            "payload_hex": None,
            "payload_bytes": [],
            "decoded_value": None,
            "nrc": None,
            "nrc_desc": None,
        }

        try:
            if self.current_header != target_header:
                self.komut_gonder(f"AT SH {target_header}", timeout=1.0)
                self.current_header = target_header
                switched_header = True

            self._ensure_session(target_header)

            # 3. Send Request
            res = self.komut_gonder(cmd, timeout=2.0)
            res_str = "".join(res).upper() if res else ""
            result["response"] = res_str
            result["status"] = self.last_response_status

            # Reassemble multi-frame if multiple lines / ISO-TP frames present
            if res and len(res) > 1:
                payload_str = self._multiframe_birlestir(res)
            else:
                payload_str = res_str
                for hdr in ("7E8", "7E9", "7EA", "7EB", "7EC", "7ED", "7EE", "7EF", "7E0", "7E1", "7E2", "7E3", "7E4", "7E5", "7E6", "7E7", "7DF"):
                    if payload_str.startswith(hdr):
                        payload_str = payload_str[len(hdr):]
                        break

            # 4. Analyze Response
            target_prefix = f"62{target_did}"

            if payload_str.startswith(target_prefix):
                payload_hex = payload_str[len(target_prefix):]
                payload_bytes = []
                for i in range(0, len(payload_hex), 2):
                    try:
                        payload_bytes.append(int(payload_hex[i:i+2], 16))
                    except ValueError:
                        break

                decoded_val = None
                if formula and payload_bytes:
                    try:
                        context = {"x": payload_bytes, "d": payload_bytes}
                        for i, val in enumerate(payload_bytes):
                            if i < 26:
                                context[chr(65 + i)] = val
                        decoded_val = self.safe_parser.evaluate(formula, context)
                    except Exception as e:
                        log_flush(f"[MANUAL_DID_PROBE] Formül hesaplama hatası ({formula}): {e}")

                result.update({
                    "ok": True,
                    "status": STATUS_VALID,
                    "payload_hex": payload_hex,
                    "payload_bytes": payload_bytes,
                    "decoded_value": decoded_val,
            else:
                nrc_code = self._classify_nrc(res, context_pid=cmd)
                if nrc_code or self.last_response_status == STATUS_NRC:
                    nrc_desc = NRC_MAP.get(nrc_code, f"Unknown NRC 0x{nrc_code}") if nrc_code else None
                    result.update({
                        "ok": False,
                        "status": STATUS_NRC,
                        "nrc": nrc_code,
                        "nrc_desc": nrc_desc,
                    })
                elif target_prefix in payload_str:
                    fallback_idx = payload_str.find(target_prefix)
                    log_flush(f"[DID_MISMATCH] manual_did_probe: {cmd} beklenen='{target_prefix}' başta değil (idx={fallback_idx})")
                    self.last_response_status = STATUS_DID_MISMATCH
                    result.update({
                        "ok": False,
                        "status": STATUS_DID_MISMATCH,
                    })

        except Exception as e:
            log_flush(f"[MANUAL_DID_PROBE_ERROR] Hata: {e}")
            result.update({
                "ok": False,
                "status": STATUS_SERIAL_ERROR,
                "error": str(e),
            })
        finally:
            # 5. Restore Header to initial state if switched
            if switched_header and self.current_header != initial_header:
                self.komut_gonder(f"AT SH {initial_header}", timeout=1.0)
                self.current_header = initial_header

        return result

    def baglanti_kontrol(self):
        """Otomatik Reconnect"""
        print("⚠️ Bağlantı koptu, tekrar deneniyor...")
        # V92: Cache silme kaldırıldı
        return self.baglan()

    def _bos_veri_dondur(self):
        # GÖREV 3: Bağlantı koptuğunda None dön — 0.0 sahte skor üretir
        return {
            "RPM": 0, "SPEED": 0, "Voltaj": 0.0,
            "ECT": None, "TPS": None, "MAP": None,
            "STFT": None, "LTFT": None, "LOAD": None,
            "MIL": False, "DTC_List": []
        }


    def kurulum_yap(self):
        print("Araç Hazırlanıyor...")
        self.ariza_kodlarini_coz()

    def ariza_kodlarini_coz(self):
        """GÖREV 1 (Production): Gerçek DTC Decode — ISO-TP Multi-Frame Destekli (P/C/B/U)
        Madde 4: Count-byte kayması düzeltmesi: 43 sonrası ilk byte DTC sayısı olabilir,
        bu durumda skip edilerek gerçek DTC çiftleri okunur.
        """
        self.ariza_kodlari = []
        self.ariza_detaylari = []
        res = self.komut_gonder("03", timeout=3.0)
        if not res:
            return

        # Multi-frame yanıtı birleştir (uzun DTC listeleri için)
        birlesmis_hex = self._multiframe_birlestir(res)

        dtc_type_map = {0: 'P', 1: 'C', 2: 'B', 3: 'U'}

        # Birleştirilmiş hex üzerinde tüm "43" bloklarını tara
        idx = 0
        while idx < len(birlesmis_hex) - 1:
            pos_43 = birlesmis_hex.find("43", idx)
            if pos_43 == -1:
                break
            dtc_hex = birlesmis_hex[pos_43+2:]  # "43" sonrası payload

            # Madde 4: Count-byte kayması düzeltmesi
            # Bazı ECU'lar "43" sonrasına önce DTC sayısını (1 byte) ekler.
            # Eğer ilk byte 0x01–0x1F arasındaysa ve sonraki byte geçerli DTC tipi ise,
            # bu byte bir adet belirteci (count byte)dir → atla.
            parse_offset = 0
            try:
                if len(dtc_hex) >= 2:
                    first_byte = int(dtc_hex[0:2], 16)
                    # Count byte aralığı: 0x01–0x1F (1-31 DTC), AND sonraki çiftin
                    # üst 2 biti geçerli DTC tipi (0x00-0x03 aralığında) olmalı
                    if 0x01 <= first_byte <= 0x1F and len(dtc_hex) >= 4:
                        second_b1 = int(dtc_hex[2:4], 16)
                        dtc_type_nibble = (second_b1 >> 6) & 0x03
                        # 0=P, 1=C, 2=B, 3=U — hepsi geçerli
                        # Ama first_byte'ın kendisi DTC type olup olamayacağını da kontrol et:
                        # DTC ilk byte'ının üst 2 biti 0x00-0x03 olmalı
                        first_type_nibble = (first_byte >> 6) & 0x03
                        # first_byte'ın P/C/B/U değil, sadece sayı gibi küçük bir değer olması
                        # yüksek olasılıkla count byte demektir
                        if first_byte <= 0x0F or (first_type_nibble == 0 and first_byte < 0x04):
                            parse_offset = 2  # 1 byte (2 hex char) atla
            except Exception as e:
                log_flush(f"[DTC_ERROR] DTC sayım byte kontrol hatası: {e}")
                parse_offset = 0

            # Her DTC 4 hex karakter (2 byte)
            for i in range(parse_offset, len(dtc_hex) - 3, 4):
                try:
                    b1 = int(dtc_hex[i:i+2], 16)
                    b2 = int(dtc_hex[i+2:i+4], 16)
                    # Padding byte'larını atla: 0x00, 0xAA, 0x55, 0xCC
                    if b1 == 0 and b2 == 0: continue
                    if b1 in (0xAA, 0x55, 0xCC) and b2 in (0xAA, 0x55, 0xCC): continue
                    if b1 in (0xAA, 0x55, 0xCC) or b2 in (0xAA, 0x55, 0xCC): continue
                    dtc_type = dtc_type_map[(b1 >> 6) & 0x03]
                    dtc_num = ((b1 & 0x3F) << 8) | b2
                    dtc_str = f"{dtc_type}{dtc_num:04X}"
                    if dtc_str not in self.ariza_kodlari:  # Duplicate önle
                        self.ariza_kodlari.append(dtc_str)
                        self.ariza_detaylari.append({
                            "kod": dtc_str,
                            "aciklama": self.dtc_lookup_get(dtc_str)
                        })
                        log_flush(f"DTC Tespit: {dtc_str}")
                except Exception as e:
                    log_flush(f"[DTC_ERROR] DTC parse hatası: {e}")
            # Sonraki "43" bloğunu ara (bazı ECU'lar birden fazla frame gönderir)
            idx = pos_43 + 2

    def dtc_lookup_get(self, dtc_code: str) -> str:
        code = (dtc_code or "").strip().upper()
        return self.dtc_lookup.get(code) or DTC_DB_CSV.get(code) or "Açıklama bulunamadı"

    def sanziman_ara(self):
        pass 

    def arizalari_sil(self):
        self.komut_gonder("04")
        return True

    def _mode9_oku(self, cmd, label):
        """V115: Akıllı ECU Parmak İzi Okuyucu"""
        try:
            res = self.komut_gonder(cmd, timeout=2.0)
            if not res: return
            hex_str = self._multiframe_birlestir(res)
            target = f"49{cmd[2:]}"
            idx = hex_str.find(target)
            if idx != -1:
                # Payload'u al (ID ve Count byte atla)
                payload_hex = hex_str[idx+6:]
                text = ""
                for i in range(0, len(payload_hex)-1, 2):
                    try:
                        char_code = int(payload_hex[i:i+2], 16)
                        if 32 <= char_code <= 126:  # Basılabilir ASCII
                            text += chr(char_code)
                    except Exception as e:
                        log_flush(f"[MODE9_ERROR] Mode 09 ASCII parse hatası: {e}")
                if len(text.strip()) > 2:
                    self.ecu_info[label] = text.strip()
                    log_flush(f"Mode 09 {label}: {text.strip()}")
        except Exception as e:
            log_flush(f"[MODE9_ERROR] Mode 09 genel hata (cmd={cmd}): {e}")

    def csv_pids_yukle(self):
        """V115: Dinamik CSV PID Yükleyici (Hata Toleranslı)"""
        print("   📂 CSV Veritabanı Yükleniyor...")
        self.csv_pids = {}
        
        # 1. Standart Service 01 CSV (obd2-pid-table-service-01.csv)
        csv_s01 = os.path.join(CSV_DIR, "obd2-pid-table-service-01.csv")
        try:
            if os.path.exists(csv_s01):
                count_01 = 0
                with open(csv_s01, mode='r', encoding='utf-8-sig', errors='replace') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        pid_hex = row.get('PID (hex)', '').strip().upper()
                        scale_str = row.get('Scale', '').strip()
                        offset_str = row.get('Offset', '').strip()
                        name = row.get('Name', '').strip()
                        
                        # Eğer Scale matematiksel işlem ise es geç (eval güvensiz), veya string parse et
                        if pid_hex and scale_str and offset_str and '(' not in scale_str and '/' not in scale_str:
                            try:
                                scale = float(scale_str)
                                offset = float(offset_str)
                                pid_key = f"01{pid_hex}"
                                # Dinamik lambda oluştur (closure hatasını önlemek için default arg kullanıyoruz)
                                self.csv_pids[pid_key] = (name, lambda x, s=scale, o=offset: x[0]*s + o)
                                count_01 += 1
                            except ValueError as e:
                                log_flush(f"[CSV_LOAD_ERROR] Mode 01 CSV satır işleme hatası: {e}")
                print(f"      ✅ {count_01} Adet Mode 01 PID yüklendi.")
        except Exception as e:
            log_flush(f"[CSV_LOAD_ERROR] Mode 01 CSV okuma hatası: {e}")

        # 2. Mode 22 Extended CSV (legacy + dbCSV/Extended_PIDs dinamik)
        self.derin_tarama_ek_pidler = []
        legacy_files = [os.path.join(CSV_DIR, n) for n in ["voltpids.csv", "exportedPIDs.csv", "exported-PIDs-20221207.csv"]]
        dynamic_files = [str(p) for p in self.pid_manager.load_for_vehicle(self.vehicle_hint)]
        for csv_yol in legacy_files + dynamic_files:
            try:
                if os.path.exists(csv_yol):
                    count_csv = 0
                    with open(csv_yol, mode='r', encoding='utf-8-sig', errors='replace') as f:
                        reader = csv.DictReader(f)
                        reader.fieldnames = [str(col).strip(' "') for col in reader.fieldnames]
                        for row_raw in reader:
                            row = {}
                            for k, v in row_raw.items():
                                if k: row[str(k).strip()] = str(v).strip()
                            
                            def s(keys):
                                for x in keys:
                                    if x in row: return row[x]
                                return ""

                            isim = s(["ShortName", "Name"])
                            pid_raw = s(["ModeAndPID"]).upper()
                            header = s(["OBD Header", "Header"])
                            if not header:
                                header = "7E0"
                            else:
                                # V202: Header format doğrulama — bozuk Excel export'larını (örn. "7,00E+00") yakala
                                header_clean = header.strip().upper()
                                if not re.fullmatch(r'7E[0-9A-F]', header_clean) and not re.fullmatch(r'7D[0-9A-F]', header_clean):
                                    log_flush(f"[CSV_HEADER_CORRUPT] {os.path.basename(csv_yol)} - PID={pid_raw} - bozuk header degeri atlandi: '{header}'")
                                    continue
                                header = header_clean
                            denklem = s(["Equation"])
                            
                            if len(pid_raw) >= 4 and pid_raw.startswith(("21", "22", "2C")):
                                ext = denklem
                                if ext:
                                    try:
                                        def make_func(f_str):
                                            # V136: Security Upgrade - AST Based Safe Calculation
                                            def safe_calc(x):
                                                context = {"x": x, "d": x}
                                                for i, val in enumerate(x):
                                                    if i < 26: context[chr(65+i)] = val
                                                return self.safe_parser.evaluate(f_str, context)
                                            return safe_calc
                                        fonksiyon = make_func(ext)
                                    except Exception as e:
                                        log_flush(f"[PARSER_ERROR] Formula hesaplama hatasi: {e}")
                                        fonksiyon = lambda x: x[0]
                                    
                                    self.derin_tarama_ek_pidler.append({
                                        "isim": isim,
                                        "pid": pid_raw,
                                        "header": header,
                                        "formula": fonksiyon
                                    })
                                    count_csv += 1
                                    # V202: derin_tarama_ek_pidler'daki veriyi ayrıca custom_pids'e de yaz
                                    # (tek_veri_oku'daki GÖREV 3 polling döngüsü custom_pids'i okuyor, formul STRING bekliyor)
                                    self.custom_pids[pid_raw] = {
                                        "isim": isim,
                                        "header": header,
                                        "formul": ext,  # ham formül string'i (safe_parser.evaluate bunu bekliyor)
                                    }
                    if count_csv > 0:
                        print(f"      ✅ {count_csv} Adet Extended PID algılandı ({os.path.basename(csv_yol)}).")
            except Exception as e:
                log_flush(f"[CSV_LOAD_ERROR] Extended PID CSV okuma hatası ({os.path.basename(csv_yol)}): {e}")

    def block_parser(self, hex_response):
        """V115: Aveo / Sirius D42 Çoklu Veri Ayrıştırıcı"""
        # 6102 format: [CAN/Header] 61 02 [A] [B] [C] ... 
        target = "6102"
        idx = hex_response.find(target)
        if idx == -1: return
        
        payload_hex = hex_response[idx+4:]
        bytes_list = []
        for i in range(0, len(payload_hex)-1, 2):
            try:
                bytes_list.append(int(payload_hex[i:i+2], 16))
            except Exception as e:
                log_flush(f"[BLOCK_PARSE_ERROR] Sirius D42 byte parse hatası: {e}")
            
        SIRIUS_D42_TEMPLATE = {
            "ECT":   (0, 0.753, -49),   # A
            "IAT":   (1, 0.753, -49),   # B
            "TPS":   (2,  0.392, 0),    # C
            "RPM":   ([5, 6], "256", 0), # F*256+G (Index 5, 6)
            "MAP":   (9,  0.466, 0),    # J
            "SPEED": (4,  1,     0),    # E (Index 4)
        }
        
        # Parse & Populate Cache
        _now = time.time()
        for field, config in SIRIUS_D42_TEMPLATE.items():
            try:
                if isinstance(config[0], list): # Multiple bytes (e.g RPM)
                    idx1, idx2 = config[0]
                    if idx2 < len(bytes_list):
                        val = (bytes_list[idx1] * 256 + bytes_list[idx2]) / 4 # Sirius RPM bölü 4
                        self._update_sensor_cache(field, val, status=STATUS_VALID, timestamp=_now, source="MODE21")
                else: # Single byte
                    byte_idx, scale, offset = config
                    if byte_idx < len(bytes_list):
                        val = (bytes_list[byte_idx] * scale) + offset
                        self._update_sensor_cache(field, val, status=STATUS_VALID, timestamp=_now, source="MODE21")
            except Exception as e:
                log_flush(f"[BLOCK_PARSE_ERROR] Sirius D42 hesaplama hatası ({field}): {e}")

# V200: Priority Queue I/O Worker ve AT DPN adaptasyonu tamamlandı