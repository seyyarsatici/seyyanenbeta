"""
Seyyanen Diagnostic Engine — Phase F-6: Live Diagnostic UI / Presentation
========================================================================
Responsive, technician-focused live presentation layer built with PyQt6.
Strictly acts as a consumer of Phase F-1 through F-5 architectures:
- F-1: Live Acquisition Runtime (live_runtime.py)
- F-2: Real-Time Data Quality (live_quality.py)
- F-3: Live Diagnostic Intelligence (live_intelligence.py)
- F-4: Fault & DTC Lifecycle (live_dtc_lifecycle.py)
- F-5: Runtime Safety & Recovery (live_safety.py)

HARD ARCHITECTURAL BOUNDARIES:
- ZERO diagnostic decision making in the UI.
- ZERO direct serial I/O or raw AT/OBD/UDS command dispatching.
- ZERO destructive operations (No Mode 04, No automatic ECU clearing).
- Safe GUI thread boundary: Worker thread NEVER mutates PyQt widgets directly.
"""

import sys
import time
import collections
from typing import Optional, Dict, List, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel, QHeaderView,
    QAbstractItemView, QFrame, QTabWidget, QSplitter, QMessageBox,
    QProgressBar, QButtonGroup
)
from PyQt6.QtGui import QFont, QColor, QPalette
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread

try:
    from pyqtgraph import PlotWidget, mkPen
    PYQTGRAPH_AVAILABLE = True
except ImportError:
    PYQTGRAPH_AVAILABLE = False
    PlotWidget = None
    mkPen = None

from live_runtime import (
    LiveAcquisitionRuntime,
    LIVE_IDLE,
    LIVE_STARTING,
    LIVE_RUNNING,
    LIVE_DEGRADED,
    LIVE_STOPPING,
    LIVE_STOPPED,
    LIVE_ERROR,
    DEFAULT_PID_CATALOG,
    STATUS_VALID,
    STATUS_TIMEOUT,
    STATUS_NO_DATA,
    STATUS_EMPTY_RESPONSE,
    STATUS_NO_CONNECTION,
    STATUS_WORKER_DOWN,
    STATUS_SERIAL_ERROR,
    STATUS_NRC,
)
from live_quality import (
    QUALITY_GOOD,
    QUALITY_SUSPECT,
    QUALITY_STALE,
    QUALITY_INVALID,
    QUALITY_ERROR,
)
QUALITY_UNKNOWN = "UNKNOWN"
from live_intelligence import (
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SEVERITY_INFO,
    CONFIDENCE_HIGH,
    CONFIDENCE_MODERATE,
    CONFIDENCE_LOW,
)
from live_dtc_lifecycle import (
    DTC_NEW,
    DTC_ACTIVE,
    DTC_PERSISTING,
    DTC_INTERMITTENT,
    DTC_RECOVERING,
    DTC_RESOLVED,
    DTC_REAPPEARED,
)
from live_safety import (
    CIRCUIT_CLOSED,
    CIRCUIT_HALF_OPEN,
    CIRCUIT_OPEN,
)


# =====================================================================
# 1. PRESENTATION VIEW-MODEL & FORMATTING HELPERS
# =====================================================================

class LivePresentationModel:
    """
    Encapsulates presentation transformations and formatting.
    Guarantees consistent, non-deceptive representation of live data.
    """

    @staticmethod
    def format_pid_value(value: Optional[float], unit: str, status: str, quality: str) -> str:
        """Formats sensor value. Never replaces unknown/failed with fake zeros."""
        if quality in (QUALITY_INVALID, QUALITY_ERROR) or status != STATUS_VALID:
            if status == STATUS_TIMEOUT:
                return "ZAMAN AŞIMI"
            elif status == STATUS_NO_DATA:
                return "VERİ YOK"
            elif status == STATUS_NO_CONNECTION:
                return "BAĞLANTI YOK"
            elif value is None:
                return "---"
            return f"GEÇERSİZ ({value:.1f})"
        
        if value is None:
            return "---"
        
        # Round according to standard display rules
        if abs(value) >= 100:
            return f"{value:.1f} {unit}".strip()
        elif abs(value) >= 10:
            return f"{value:.2f} {unit}".strip()
        else:
            return f"{value:.3f} {unit}".strip()

    @staticmethod
    def format_age(timestamp: float) -> str:
        """Formats relative age since timestamp."""
        if not timestamp or timestamp <= 0:
            return "---"
        delta = time.time() - timestamp
        if delta < 0:
            return "0 ms"
        if delta < 1.0:
            return f"{int(delta * 1000)} ms"
        elif delta < 60.0:
            return f"{delta:.1f} s"
        else:
            return f"{int(delta // 60)} dk"

    @staticmethod
    def format_runtime_stats(stats: Dict[str, Any]) -> str:
        """Formats session statistics safely adhering to canonical contract."""
        cycle = stats.get("cycle_count", 0)
        rate = stats.get("effective_sample_rate", stats.get("sample_rate_sps", 0.0))
        elapsed = stats.get("elapsed_time", stats.get("elapsed_time_sec", 0.0))
        return f"Döngü: {cycle} | Hız: {rate:.1f} sps | Süre: {elapsed:.1f}s"

    @staticmethod
    def get_quality_badge(quality: str) -> Dict[str, str]:
        """Maps quality state to text and color palette."""
        mapping = {
            QUALITY_GOOD: {"text": "GÜVENİLİR (GOOD)", "bg": "#D4EDDA", "fg": "#155724", "border": "#C3E6CB"},
            QUALITY_SUSPECT: {"text": "ŞÜPHELİ (SUSPECT)", "bg": "#FFF3CD", "fg": "#856404", "border": "#FFEEBA"},
            QUALITY_STALE: {"text": "BAYAT (STALE)", "bg": "#E2E3E5", "fg": "#383D41", "border": "#D6D8DB"},
            QUALITY_INVALID: {"text": "GEÇERSİZ (INVALID)", "bg": "#F8D7DA", "fg": "#721C24", "border": "#F5C6CB"},
            QUALITY_ERROR: {"text": "HATA (ERROR)", "bg": "#F8D7DA", "fg": "#721C24", "border": "#F5C6CB"},
            QUALITY_UNKNOWN: {"text": "BİLİNMİYOR (UNKNOWN)", "bg": "#E3E1D9", "fg": "#2C3E50", "border": "#C7C8CC"},
        }
        return mapping.get(quality, mapping[QUALITY_UNKNOWN])

    @staticmethod
    def get_severity_badge(severity: str) -> Dict[str, str]:
        """Maps diagnostic severity to text and color palette."""
        mapping = {
            SEVERITY_CRITICAL: {"text": "KRİTİK", "bg": "#E74C3C", "fg": "#FFFFFF"},
            SEVERITY_WARNING: {"text": "UYARI", "bg": "#F39C12", "fg": "#FFFFFF"},
            SEVERITY_INFO: {"text": "BİLGİ", "bg": "#95A5A6", "fg": "#FFFFFF"},
        }
        return mapping.get(severity, mapping[SEVERITY_INFO])

    @staticmethod
    def get_dtc_state_badge(state: str) -> Dict[str, str]:
        """Maps DTC lifecycle states. Strictly distinguishes recovery/resolved from physical repair."""
        mapping = {
            DTC_NEW: {"text": "YENİ TESPİT", "bg": "#F39C12", "fg": "#FFFFFF"},
            DTC_ACTIVE: {"text": "AKTİF ARIZA", "bg": "#E74C3C", "fg": "#FFFFFF"},
            DTC_PERSISTING: {"text": "SÜREKLİ AKTİF", "bg": "#C0392B", "fg": "#FFFFFF"},
            DTC_INTERMITTENT: {"text": "KESİNTİLİ (GEÇİCİ)", "bg": "#9B59B6", "fg": "#FFFFFF"},
            DTC_RECOVERING: {"text": "KAYBOLMA İZLEMEDE", "bg": "#F1C40F", "fg": "#2C3E50"},
            DTC_RESOLVED: {"text": "GÖZLEMLE ÇÖZÜLDÜ (ECU'da Yok)", "bg": "#27AE60", "fg": "#FFFFFF"},
            DTC_REAPPEARED: {"text": "YENİDEN OLUŞTU", "bg": "#D35400", "fg": "#FFFFFF"},
        }
        return mapping.get(state, {"text": state, "bg": "#BDC3C7", "fg": "#2C3E50"})

    @staticmethod
    def get_connection_info(
        runtime_state: str,
        is_serial_open: bool,
        failure_count: int = 0,
        connection_state: Optional[str] = None,
        is_simulation: bool = False,
        port: Optional[str] = None,
    ) -> Dict[str, str]:
        """Computes top-level connection badge and status description."""
        conn_str = str(connection_state).upper() if connection_state else ""
        if "CONNECTING" in conn_str:
            return {"status": "BAĞLANIYOR...", "bg": "#F1C40F", "fg": "#2C3E50", "detail": "Adaptör başlatılıyor ve ECU aranıyor..."}
        if "FAILED" in conn_str or "ERROR" in conn_str:
            return {"status": "BAĞLANTI HATASI", "bg": "#E74C3C", "fg": "#FFFFFF", "detail": "Adaptör veya seri port bağlantısı kurulamadı"}
        if not is_serial_open:
            return {"status": "BAĞLANTI YOK", "bg": "#E74C3C", "fg": "#FFFFFF", "detail": "Seri port kapalı veya kablo takılı değil"}
        if is_simulation:
            port_label = f" ({port})" if port else ""
            return {"status": f"SİMÜLASYON{port_label}", "bg": "#8E44AD", "fg": "#FFFFFF", "detail": "MockSerial test ortamı devrede"}
        port_label = f": {port}" if port and port not in ("AUTO", "COM_MOCK") else ""
        if runtime_state == LIVE_ERROR:
            return {"status": "SİSTEM HATASI", "bg": "#C0392B", "fg": "#FFFFFF", "detail": "Çalışma zamanında kritik hata oluştu"}
        if runtime_state == LIVE_DEGRADED:
            return {"status": f"KISITLI{port_label}", "bg": "#E67E22", "fg": "#FFFFFF", "detail": f"Kısmi veri kaybı / {failure_count} başarısız sorgu"}
        if runtime_state in (LIVE_RUNNING, LIVE_STARTING):
            status_text = f"BAĞLI{port_label}" if port_label else "BAĞLI VE AKTİF"
            return {"status": status_text, "bg": "#2ECC71", "fg": "#FFFFFF", "detail": f"ECU canlı veri akışı aktif ({port or 'OBD'})"}
        if runtime_state == LIVE_STOPPING:
            return {"status": "DURDURULUYOR", "bg": "#F39C12", "fg": "#FFFFFF", "detail": "İş parçacığı kapatılıyor"}
        return {"status": "HAZIR (DURDU)", "bg": "#34495E", "fg": "#FFFFFF", "detail": "Canlı okuma durduruldu"}


# =====================================================================
# 2. REAL-TIME SIGNAL TREND WIDGET
# =====================================================================

class LiveTrendWidget(QWidget):
    """
    Lightweight, bounded real-time signal graph.
    Visualizes current PID waveform without memory growth.
    """

    def __init__(self, max_points: int = 100, parent=None):
        super().__init__(parent)
        self.max_points = max_points
        self.current_pid = "010C"
        self.history_x = collections.deque(maxlen=self.max_points)
        self.history_y = collections.deque(maxlen=self.max_points)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        if PYQTGRAPH_AVAILABLE and PlotWidget is not None:
            self.plot_widget = PlotWidget()
            self.plot_widget.setBackground("#F2EFE5")
            self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
            self.plot_curve = self.plot_widget.plot(pen=mkPen(color="#2980B9", width=2))
            layout.addWidget(self.plot_widget)
        else:
            self.fallback_label = QLabel("Trend grafiği (pyqtgraph) mevcut değil.")
            self.fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.fallback_label)
            self.plot_widget = None

    def set_pid(self, pid: str, name: str = "", unit: str = ""):
        """Switches signal being plotted."""
        if self.current_pid != pid:
            self.current_pid = pid
            self.history_x.clear()
            self.history_y.clear()
            if self.plot_widget:
                title = f"{name} ({pid}) [{unit}] Canlı Trend" if name else f"{pid} Canlı Trend"
                self.plot_widget.setTitle(title, color="#2C3E50", size="10pt")
                self.plot_curve.setData([], [])

    def add_sample(self, value: Optional[float], is_valid: bool = True):
        """Pushes sample to ring buffer and updates plot."""
        if not self.plot_widget or value is None or not is_valid:
            return
        
        idx = len(self.history_x)
        self.history_x.append(idx)
        self.history_y.append(float(value))
        
        x_data = list(range(len(self.history_y)))
        self.plot_curve.setData(x_data, list(self.history_y))

    def clear(self):
        """Clears trend buffer."""
        self.history_x.clear()
        self.history_y.clear()
        if self.plot_widget:
            self.plot_curve.setData([], [])


# =====================================================================
# 2.5 ASYNCHRONOUS GUI BACKGROUND WORKERS (NON-BLOCKING SERIAL I/O)
# =====================================================================

class LiveConnectWorker(QThread):
    """
    Dedicated background worker for non-blocking serial/adapter initial connection.
    Executes adapter initialization, baudrate detection, and handshake off the GUI thread.
    """
    connect_finished = pyqtSignal(bool, str)

    def __init__(self, runtime: LiveAcquisitionRuntime, timeout: float = 5.0):
        super().__init__()
        self.runtime = runtime
        self.timeout = timeout

    def run(self):
        try:
            ok = self.runtime.connect(timeout=self.timeout)
            port_str = getattr(getattr(self.runtime, "adapter", None), "port", None) or "OBD"
            if ok:
                if getattr(self.runtime, "simulation", False):
                    msg = f"Simülasyon bağlantısı aktif ({port_str})."
                else:
                    msg = f"ELM327 adaptörü ({port_str}) başarıyla bağlandı."
            else:
                if getattr(self.runtime, "simulation", False):
                    msg = "Simülasyon bağlantısı kurulamadı."
                else:
                    msg = "Kullanılabilir COM portlarında uyumlu ELM327 adaptörü bulunamadı. Port ve Bluetooth bağlantılarını kontrol edin."
            self.connect_finished.emit(ok, msg)
        except Exception as e:
            self.connect_finished.emit(False, f"Bağlantı hatası: {e}")


class LiveReconnectWorker(QThread):
    """
    Dedicated background worker for non-blocking serial reconnection.
    Executes connection retries, backoff, and probe verification without freezing the Qt event loop.
    """
    reconnect_finished = pyqtSignal(bool, str)

    def __init__(self, runtime: LiveAcquisitionRuntime, max_attempts: int = 3, timeout: float = 1.5):
        super().__init__()
        self.runtime = runtime
        self.max_attempts = max_attempts
        self.timeout = timeout

    def run(self):
        try:
            ok = self.runtime.reconnect(max_attempts=self.max_attempts, timeout=self.timeout)
            msg = "ECU bağlantısı başarıyla yeniden kuruldu ve doğrulandı." if ok else "Yeniden bağlanma başarısız oldu. Port ve kablo bağlantılarını kontrol edin."
            self.reconnect_finished.emit(ok, msg)
        except Exception as e:
            self.reconnect_finished.emit(False, f"Yeniden bağlanma hatası: {e}")


class LiveDTCPollWorker(QThread):
    """
    Dedicated background worker for non-blocking Mode 03 DTC polling.
    Safely executes vehicle DTC query and lifecycle processing off the GUI thread.
    """
    dtc_poll_finished = pyqtSignal(dict)
    dtc_poll_error = pyqtSignal(str)

    def __init__(self, runtime: LiveAcquisitionRuntime, header: Optional[str] = None):
        super().__init__()
        self.runtime = runtime
        self.header = header

    def run(self):
        try:
            res = self.runtime.poll_dtcs(header=self.header)
            self.dtc_poll_finished.emit(res)
        except Exception as e:
            self.dtc_poll_error.emit(str(e))


# =====================================================================
# 3. MAIN LIVE DIAGNOSTIC WIDGET
# =====================================================================

class LiveDiagnosticWidget(QWidget):
    """
    Comprehensive Live Diagnostic Presentation Layer.
    Consumes F-1 through F-5 via safe, scheduled UI snapshots.
    """

    # Signals for thread-safe cross-thread event dispatching
    state_changed = pyqtSignal(str)
    sample_received = pyqtSignal(dict)
    health_updated = pyqtSignal(dict)

    def __init__(self, runtime: Optional[LiveAcquisitionRuntime] = None, parent=None):
        super().__init__(parent)
        self.runtime = runtime
        self._owns_runtime = False
        self._connect_worker: Optional[LiveConnectWorker] = None
        self._reconnect_worker: Optional[LiveReconnectWorker] = None
        self._dtc_worker: Optional[LiveDTCPollWorker] = None
        
        # Categorized PID catalog for filtering
        self.categories = {
            "TÜMÜ": ["010C", "010D", "0105", "010B", "0111", "0104", "010F", "0110", "0106", "0107", "0114"],
            "TEMEL MOTOR": ["010C", "010D", "0105", "0104"],
            "HAVA & YAKIT": ["010B", "0111", "0110", "0106", "0107"],
            "ELEKTRİK & SENSÖR": ["0114", "010F"],
        }
        self.active_category = "TÜMÜ"
        self.selected_pid = "010C"
        
        # UI Refresh Timer (Qt GUI Event Loop — strictly non-blocking)
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(90)  # ~11 fps safe refresh
        self.update_timer.timeout.connect(self.update_ui_state)

        # Track previous states to avoid redundant widget churn
        self._prev_state = None
        self._prev_active_events_count = -1
        self._prev_dtc_count = -1
        self._prev_failure_count = -1
        
        self.setup_ui()
        self.apply_theme()
        
        # Start GUI update polling
        self.update_timer.start()

    def set_runtime(self, runtime: LiveAcquisitionRuntime):
        """Binds or rebinds runtime to presentation widget."""
        self.runtime = runtime
        self.update_ui_state()

    def setup_ui(self):
        """Builds responsive layout."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # -------------------------------------------------------------
        # 1. TOP BAR: Connection, Runtime State, Action Controls & Stats
        # -------------------------------------------------------------
        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 8, 10, 8)
        top_layout.setSpacing(12)

        # Connection badge
        self.badge_connection = QLabel("BAĞLANTI BEKLENİYOR")
        self.badge_connection.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.badge_connection.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_connection.setFixedSize(170, 34)
        top_layout.addWidget(self.badge_connection)

        # Runtime State badge
        self.badge_state = QLabel(LIVE_IDLE)
        self.badge_state.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.badge_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_state.setFixedSize(140, 34)
        top_layout.addWidget(self.badge_state)

        # Stats info label
        self.lbl_stats = QLabel("Döngü: 0 | Hız: 0.0 sps | Süre: 0.0s")
        self.lbl_stats.setFont(QFont("Segoe UI", 9))
        top_layout.addWidget(self.lbl_stats)

        top_layout.addStretch()

        # Action Buttons
        self.btn_start = QPushButton("▶ Canlı Başlat")
        self.btn_start.setFixedSize(130, 36)
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.clicked.connect(self.on_start_clicked)
        top_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹ Durdur")
        self.btn_stop.setFixedSize(110, 36)
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        top_layout.addWidget(self.btn_stop)

        self.btn_reconnect = QPushButton("🔄 Yeniden Bağlan")
        self.btn_reconnect.setFixedSize(150, 36)
        self.btn_reconnect.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reconnect.clicked.connect(self.on_reconnect_clicked)
        top_layout.addWidget(self.btn_reconnect)

        main_layout.addWidget(top_bar)

        # -------------------------------------------------------------
        # 2. CENTRAL SPLITTER: Left (Live PIDs) | Right (Trend + Tabs)
        # -------------------------------------------------------------
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # === LEFT PANEL: Live PID Table & Category Filters ===
        left_panel = QFrame()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(8)

        # Filter buttons
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(6)
        self.btn_filters = {}
        for cat in self.categories.keys():
            b = QPushButton(cat)
            b.setCheckable(True)
            if cat == "TÜMÜ":
                b.setChecked(True)
            b.clicked.connect(lambda checked, c=cat: self.on_filter_changed(c))
            self.btn_filters[cat] = b
            filter_layout.addWidget(b)
        left_layout.addLayout(filter_layout)

        # Live PID Table
        self.table_pids = QTableWidget()
        self.table_pids.setColumnCount(6)
        self.table_pids.setHorizontalHeaderLabels(["PID", "Sensör Adı", "Değer", "Birim", "Gecikme", "Veri Kalitesi"])
        self.table_pids.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_pids.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_pids.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_pids.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_pids.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table_pids.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table_pids.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_pids.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_pids.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_pids.cellClicked.connect(self.on_pid_row_selected)
        left_layout.addWidget(self.table_pids)

        splitter.addWidget(left_panel)

        # === RIGHT PANEL: Real-time Signal Trend & Diagnostic Tabs ===
        right_panel = QFrame()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(8)

        # Live Trend graph widget
        self.trend_widget = LiveTrendWidget(max_points=100)
        self.trend_widget.setMinimumHeight(180)
        right_layout.addWidget(self.trend_widget, 2)

        # Multi-tab diagnostics & health
        self.tab_widget = QTabWidget()

        # Tab 1: F-3 Live Diagnostic Intelligence Events
        tab_intel = QWidget()
        tab_intel_layout = QVBoxLayout(tab_intel)
        tab_intel_layout.setContentsMargins(4, 4, 4, 4)
        self.table_events = QTableWidget()
        self.table_events.setColumnCount(5)
        self.table_events.setHorizontalHeaderLabels(["Zaman", "Önem Derecesi", "Olay Tipi", "Sensör / PID", "Teşhis Açıklaması"])
        self.table_events.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_events.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_events.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_events.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_events.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table_events.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_events.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tab_intel_layout.addWidget(self.table_events)
        self.tab_widget.addTab(tab_intel, "🚨 Canlı Teşhis Olayları (F-3)")

        # Tab 2: F-4 DTC Lifecycle Management
        tab_dtc = QWidget()
        tab_dtc_layout = QVBoxLayout(tab_dtc)
        tab_dtc_layout.setContentsMargins(4, 4, 4, 4)
        
        dtc_bar = QHBoxLayout()
        self.lbl_dtc_summary = QLabel("Aktif DTC: 0 | İzlenen: 0 | Çözülen: 0")
        self.lbl_dtc_summary.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        dtc_bar.addWidget(self.lbl_dtc_summary)
        dtc_bar.addStretch()
        
        self.btn_poll_dtc = QPushButton("🔍 DTC Sorgula (Mode 03)")
        self.btn_poll_dtc.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_poll_dtc.clicked.connect(self.on_poll_dtc_clicked)
        dtc_bar.addWidget(self.btn_poll_dtc)
        tab_dtc_layout.addLayout(dtc_bar)

        self.table_dtcs = QTableWidget()
        self.table_dtcs.setColumnCount(6)
        self.table_dtcs.setHorizontalHeaderLabels(["DTC Kodu", "Açıklama", "Yaşam Döngüsü Durumu", "İlk Görülme", "Son Görülme", "Canlı Kanıt"])
        self.table_dtcs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_dtcs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_dtcs.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_dtcs.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_dtcs.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table_dtcs.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table_dtcs.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_dtcs.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tab_dtc_layout.addWidget(self.table_dtcs)
        self.tab_widget.addTab(tab_dtc, "⚡ Arıza & DTC Yaşam Döngüsü (F-4)")

        # Tab 3: F-5 Runtime Safety & Recovery Health Panel
        tab_safety = QWidget()
        tab_safety_layout = QVBoxLayout(tab_safety)
        tab_safety_layout.setContentsMargins(4, 4, 4, 4)
        
        safety_top_bar = QHBoxLayout()
        self.lbl_safety_summary = QLabel("Devre Kesici Durumu: Kapalı (Normal) | Toplam Hata: 0")
        self.lbl_safety_summary.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        safety_top_bar.addWidget(self.lbl_safety_summary)
        safety_top_bar.addStretch()

        self.btn_reset_faults = QPushButton("🛡️ Güvenlik Hatalarını Sıfırla")
        self.btn_reset_faults.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset_faults.clicked.connect(self.on_reset_faults_clicked)
        safety_top_bar.addWidget(self.btn_reset_faults)
        tab_safety_layout.addLayout(safety_top_bar)

        self.table_failures = QTableWidget()
        self.table_failures.setColumnCount(4)
        self.table_failures.setHorizontalHeaderLabels(["Zaman", "Hata Sınıfı", "İlgili PID", "Hata Açıklaması"])
        self.table_failures.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_failures.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_failures.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_failures.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table_failures.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_failures.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tab_safety_layout.addWidget(self.table_failures)
        self.tab_widget.addTab(tab_safety, "🛡️ Güvenlik & Kurtarma (F-5)")

        right_layout.addWidget(self.tab_widget, 3)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)

        main_layout.addWidget(splitter)

    # -----------------------------------------------------------------
    # THEME & STYLING
    # -----------------------------------------------------------------

    def apply_theme(self):
        """Applies consistent Industrial Titanium palette matching main_ui."""
        stylesheet = """
            LiveDiagnosticWidget, QFrame#TopBar {
                background-color: #F2EFE5;
            }
            QFrame {
                background-color: #E3E1D9;
                border: 2px solid #C7C8CC;
                border-radius: 6px;
            }
            QLabel {
                color: #2C3E50;
            }
            QPushButton {
                background-color: #B4B4B8;
                color: #2C3E50;
                border: 2px solid #C7C8CC;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #A0A0A4;
            }
            QPushButton:pressed {
                background-color: #909094;
            }
            QPushButton:disabled {
                background-color: #D6D8DB;
                color: #7F8C8D;
                border-color: #BDC3C7;
            }
            QPushButton:checked {
                background-color: #2C3E50;
                color: #FFFFFF;
                border-color: #1A252F;
            }
            QTableWidget {
                background-color: #FFFFFF;
                alternate-background-color: #F8F9FA;
                gridline-color: #E3E1D9;
                border: 1px solid #C7C8CC;
                border-radius: 4px;
                color: #2C3E50;
            }
            QTableWidget::item:selected {
                background-color: #D6EAF8;
                color: #1B4F72;
            }
            QHeaderView::section {
                background-color: #B4B4B8;
                color: #2C3E50;
                padding: 6px;
                border: 1px solid #C7C8CC;
                font-weight: bold;
            }
            QTabWidget::pane {
                border: 2px solid #C7C8CC;
                background-color: #FFFFFF;
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: #B4B4B8;
                color: #2C3E50;
                padding: 6px 14px;
                border: 1px solid #C7C8CC;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background-color: #FFFFFF;
                border-bottom-color: #FFFFFF;
            }
        """
        self.setStyleSheet(stylesheet)

    # -----------------------------------------------------------------
    # GUI TIMED UPDATE LOOP (STRICTLY ON QT EVENT LOOP)
    # -----------------------------------------------------------------

    def update_ui_state(self):
        """
        Scheduled periodic update. Safe, incremental, and defensive.
        Polls thread-safe snapshots from runtime without blocking the GUI.
        """
        if self.runtime is None:
            self._render_empty_state()
            return

        try:
            # 1. Update Connection & Runtime State
            state = self.runtime.get_state()
            is_serial_alive = False
            if hasattr(self.runtime, "is_connected"):
                is_serial_alive = self.runtime.is_connected()
            elif hasattr(self.runtime.engine, "ser") and self.runtime.engine.ser is not None:
                is_serial_alive = getattr(self.runtime.engine.ser, "is_open", False)

            conn_state = None
            if hasattr(self.runtime, "connection_state"):
                conn_state = self.runtime.connection_state
            if self._connect_worker and self._connect_worker.isRunning():
                conn_state = "CONNECTING"

            # Failure count from safety manager
            health = self.runtime.get_runtime_health()
            fail_count = health.get("failure_counts", {}).get("total", 0)

            is_sim = getattr(self.runtime, "simulation", False)
            active_port = getattr(getattr(self.runtime, "adapter", None), "port", None)
            conn_info = LivePresentationModel.get_connection_info(
                state,
                is_serial_alive,
                fail_count,
                connection_state=conn_state,
                is_simulation=is_sim,
                port=active_port,
            )
            self.badge_connection.setText(conn_info["status"])
            self.badge_connection.setStyleSheet(f"background-color: {conn_info['bg']}; color: {conn_info['fg']}; border-radius: 4px; padding: 4px;")
            self.badge_connection.setToolTip(conn_info["detail"])

            # Runtime State Badge
            self.badge_state.setText(state)
            if state == LIVE_RUNNING:
                self.badge_state.setStyleSheet("background-color: #2ECC71; color: #FFFFFF; border-radius: 4px;")
            elif state == LIVE_DEGRADED:
                self.badge_state.setStyleSheet("background-color: #E67E22; color: #FFFFFF; border-radius: 4px;")
            elif state == LIVE_ERROR:
                self.badge_state.setStyleSheet("background-color: #E74C3C; color: #FFFFFF; border-radius: 4px;")
            elif state == LIVE_STARTING:
                self.badge_state.setStyleSheet("background-color: #F1C40F; color: #2C3E50; border-radius: 4px;")
            elif state == LIVE_STOPPING:
                self.badge_state.setStyleSheet("background-color: #E67E22; color: #FFFFFF; border-radius: 4px;")
            else:
                self.badge_state.setStyleSheet("background-color: #95A5A6; color: #FFFFFF; border-radius: 4px;")

            # Button States strictly derived from backend state
            is_connecting = bool(self._connect_worker and self._connect_worker.isRunning())
            is_reconnecting = bool(self._reconnect_worker and self._reconnect_worker.isRunning())
            if is_connecting or is_reconnecting:
                self.btn_start.setEnabled(False)
                self.btn_stop.setEnabled(False)
                self.btn_reconnect.setEnabled(False)
            else:
                self.btn_start.setEnabled(state in (LIVE_IDLE, LIVE_STOPPED))
                self.btn_stop.setEnabled(state in (LIVE_RUNNING, LIVE_DEGRADED, LIVE_STARTING))
                self.btn_reconnect.setEnabled(state in (LIVE_ERROR, LIVE_DEGRADED, LIVE_STOPPED, LIVE_IDLE))

            # Runtime stats
            stats = self.runtime.get_runtime_stats()
            self.lbl_stats.setText(LivePresentationModel.format_runtime_stats(stats))

            # 2. Update Live PID Table
            self._update_live_table()

            # 3. Update Intelligence Events Tab (F-3)
            self._update_intelligence_tab()

            # 4. Update DTC Lifecycle Tab (F-4)
            self._update_dtc_tab()

            # 5. Update Safety & Recovery Tab (F-5)
            self._update_safety_tab(health)

        except Exception as e:
            # Defensive isolation: GUI error must NEVER kill acquisition
            print(f"[UI_WARN] update_ui_state exception: {e}")

    def _render_empty_state(self):
        """Renders explicit empty/disconnected state when no runtime exists."""
        self.badge_connection.setText("BAĞLANTI YOK")
        self.badge_connection.setStyleSheet("background-color: #E74C3C; color: #FFFFFF; border-radius: 4px;")
        self.badge_state.setText(LIVE_IDLE)
        self.badge_state.setStyleSheet("background-color: #95A5A6; color: #FFFFFF; border-radius: 4px;")
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_reconnect.setEnabled(False)
        self.lbl_stats.setText("Oturum başlatılmadı.")

    def _update_live_table(self):
        """Updates live PID table rows efficiently."""
        pids_to_show = [p for p in self.categories.get(self.active_category, []) if p in self.runtime.pids]
        if not pids_to_show:
            pids_to_show = self.runtime.pids

        # Ensure correct row count
        if self.table_pids.rowCount() != len(pids_to_show):
            self.table_pids.setRowCount(len(pids_to_show))

        quality_snapshot = self.runtime.get_quality_snapshot()
        all_qualities = self.runtime.get_quality() if hasattr(self.runtime, "get_quality") else {}
        quality_details = quality_snapshot.get("details", {}) if isinstance(quality_snapshot, dict) else {}

        for row, pid in enumerate(pids_to_show):
            meta = DEFAULT_PID_CATALOG.get(pid, {"name": pid, "unit": ""})
            name = meta.get("name", pid)
            unit = meta.get("unit", "")
            
            sample = self.runtime.get_latest_sample(pid)
            val = sample.get("value") if sample else None
            status = sample.get("status") if sample else STATUS_NO_DATA
            ts = sample.get("timestamp") if sample else 0.0

            quality = QUALITY_UNKNOWN
            if isinstance(all_qualities, dict) and pid in all_qualities:
                q_rec = all_qualities[pid]
                quality = q_rec.get("quality", QUALITY_UNKNOWN) if isinstance(q_rec, dict) else str(q_rec)
            elif pid in quality_details:
                quality = quality_details[pid]

            formatted_val = LivePresentationModel.format_pid_value(val, unit, status, quality)
            age_str = LivePresentationModel.format_age(ts)
            badge = LivePresentationModel.get_quality_badge(quality)

            # Sütun 0: PID
            self._set_table_item(self.table_pids, row, 0, pid, align=Qt.AlignmentFlag.AlignCenter)
            # Sütun 1: Sensör Adı
            self._set_table_item(self.table_pids, row, 1, name)
            # Sütun 2: Değer
            self._set_table_item(self.table_pids, row, 2, formatted_val, bold=True, align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            # Sütun 3: Birim
            self._set_table_item(self.table_pids, row, 3, unit, align=Qt.AlignmentFlag.AlignCenter)
            # Sütun 4: Gecikme
            self._set_table_item(self.table_pids, row, 4, age_str, align=Qt.AlignmentFlag.AlignCenter)
            # Sütun 5: Veri Kalitesi (Badge)
            item_q = self._set_table_item(self.table_pids, row, 5, badge["text"], bold=True, align=Qt.AlignmentFlag.AlignCenter)
            item_q.setBackground(QColor(badge["bg"]))
            item_q.setForeground(QColor(badge["fg"]))

            # Update selected trend if this PID is active
            if pid == self.selected_pid:
                is_valid = (quality in (QUALITY_GOOD, QUALITY_SUSPECT)) and (val is not None)
                self.trend_widget.set_pid(pid, name, unit)
                if val is not None:
                    self.trend_widget.add_sample(val, is_valid=is_valid)

    def _update_intelligence_tab(self):
        """Updates F-3 diagnostic events table."""
        events = self.runtime.get_recent_events(limit=30)
        if len(events) != self.table_events.rowCount():
            self.table_events.setRowCount(len(events))

        for row, ev in enumerate(events):
            ts_str = time.strftime("%H:%M:%S", time.localtime(ev.get("timestamp", time.time())))
            sev = ev.get("severity", SEVERITY_INFO)
            ev_type = ev.get("event_type", "EVENT")
            pids = ", ".join(ev.get("pids", []))
            reason = ev.get("reason", "")
            badge = LivePresentationModel.get_severity_badge(sev)

            self._set_table_item(self.table_events, row, 0, ts_str, align=Qt.AlignmentFlag.AlignCenter)
            
            sev_item = self._set_table_item(self.table_events, row, 1, badge["text"], bold=True, align=Qt.AlignmentFlag.AlignCenter)
            sev_item.setBackground(QColor(badge["bg"]))
            sev_item.setForeground(QColor(badge["fg"]))

            self._set_table_item(self.table_events, row, 2, ev_type)
            self._set_table_item(self.table_events, row, 3, pids, align=Qt.AlignmentFlag.AlignCenter)
            self._set_table_item(self.table_events, row, 4, reason)

    def _update_dtc_tab(self):
        """Updates F-4 DTC lifecycle table."""
        summary = self.runtime.get_dtc_lifecycle_summary()
        self.lbl_dtc_summary.setText(
            f"Aktif DTC: {summary.get('active_count', 0)} | İzlenen (Kaybolan): {summary.get('recovering_count', 0)} | Çözülen (Gözlemle): {summary.get('resolved_count', 0)}"
        )

        all_states = self.runtime.get_all_dtc_states()
        dtc_list = list(all_states.values())
        
        if len(dtc_list) != self.table_dtcs.rowCount():
            self.table_dtcs.setRowCount(len(dtc_list))

        for row, dtc in enumerate(dtc_list):
            code = dtc.get("code", "")
            desc = dtc.get("description", "")
            state = dtc.get("lifecycle_state") or dtc.get("state", DTC_ACTIVE)
            badge = LivePresentationModel.get_dtc_state_badge(state)

            first_seen = dtc.get("first_seen", 0.0)
            last_seen = dtc.get("last_seen", 0.0)
            first_str = time.strftime("%H:%M:%S", time.localtime(first_seen)) if first_seen else "---"
            last_str = time.strftime("%H:%M:%S", time.localtime(last_seen)) if last_seen else "---"
            
            evidence = dtc.get("associated_evidence", [])
            ev_str = "; ".join([e.get("summary", "") for e in evidence]) if evidence else "---"

            self._set_table_item(self.table_dtcs, row, 0, code, bold=True, align=Qt.AlignmentFlag.AlignCenter)
            self._set_table_item(self.table_dtcs, row, 1, desc)
            
            state_item = self._set_table_item(self.table_dtcs, row, 2, badge["text"], bold=True, align=Qt.AlignmentFlag.AlignCenter)
            state_item.setBackground(QColor(badge["bg"]))
            state_item.setForeground(QColor(badge["fg"]))

            self._set_table_item(self.table_dtcs, row, 3, first_str, align=Qt.AlignmentFlag.AlignCenter)
            self._set_table_item(self.table_dtcs, row, 4, last_str, align=Qt.AlignmentFlag.AlignCenter)
            self._set_table_item(self.table_dtcs, row, 5, ev_str)

    def _update_safety_tab(self, health: Dict[str, Any]):
        """Updates F-5 runtime safety and failure history table."""
        fail_counts = health.get("failure_counts", {})
        total_fail = fail_counts.get("total", 0)
        open_cbs = health.get("open_circuit_breakers", [])
        cb_str = f"Devre Kesici AÇIK: {', '.join(open_cbs)}" if open_cbs else "Devre Kesiciler: KAPALI (Normal)"
        
        self.lbl_safety_summary.setText(f"{cb_str} | Toplam Hata: {total_fail}")

        failures = self.runtime.get_failure_history(limit=25)
        if len(failures) != self.table_failures.rowCount():
            self.table_failures.setRowCount(len(failures))

        for row, fail in enumerate(failures):
            ts = fail.get("timestamp", time.time())
            ts_str = time.strftime("%H:%M:%S", time.localtime(ts))
            f_class = fail.get("category") or fail.get("failure_class", "FAILURE")
            pid = fail.get("component") or fail.get("pid") or "---"
            msg = fail.get("reason") or fail.get("message", "")

            self._set_table_item(self.table_failures, row, 0, ts_str, align=Qt.AlignmentFlag.AlignCenter)
            self._set_table_item(self.table_failures, row, 1, f_class, bold=True, align=Qt.AlignmentFlag.AlignCenter)
            self._set_table_item(self.table_failures, row, 2, pid, align=Qt.AlignmentFlag.AlignCenter)
            self._set_table_item(self.table_failures, row, 3, msg)

    def _set_table_item(self, table: QTableWidget, row: int, col: int, text: str, bold: bool = False, align=None) -> QTableWidgetItem:
        """Helper to create or update existing table item without allocating new memory."""
        item = table.item(row, col)
        if item is None:
            item = QTableWidgetItem(str(text))
            table.setItem(row, col, item)
        else:
            if item.text() != str(text):
                item.setText(str(text))
        
        if bold:
            item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        if align is not None:
            item.setTextAlignment(align)
        return item

    # -----------------------------------------------------------------
    # USER INTERACTIONS & SAFE DELEGATIONS
    # -----------------------------------------------------------------

    def on_start_clicked(self):
        """Starts live acquisition via runtime asynchronously without blocking GUI event loop."""
        if not self.runtime:
            return

        # Prevent duplicate concurrent workers
        if self._connect_worker and self._connect_worker.isRunning():
            return
        if self._reconnect_worker and self._reconnect_worker.isRunning():
            return

        # If not connected yet, initiate non-blocking background connection
        if not self.runtime.is_connected():
            self.badge_connection.setText("BAĞLANIYOR...")
            self.badge_connection.setStyleSheet("background-color: #F1C40F; color: #2C3E50; border-radius: 4px; padding: 4px;")
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(False)
            self.btn_reconnect.setEnabled(False)

            self._connect_worker = LiveConnectWorker(self.runtime, timeout=5.0)
            self._connect_worker.connect_finished.connect(self._on_connect_completed)
            self._connect_worker.start()
            return

        # Already connected, start acquisition immediately
        ok = self.runtime.start()
        if not ok:
            QMessageBox.warning(self, "Uyarı", "Canlı veri başlatılamadı. Seri bağlantıyı ve araç durumunu kontrol edin.")
        self.update_ui_state()

    def _on_connect_completed(self, ok: bool, msg: str):
        """Slot invoked safely on Qt GUI thread when initial connection finishes."""
        if ok:
            start_ok = self.runtime.start()
            if not start_ok:
                QMessageBox.warning(self, "Uyarı", "Bağlantı kuruldu fakat canlı veri akışı başlatılamadı.")
        else:
            QMessageBox.critical(self, "Bağlantı Hatası", msg)
        self.update_ui_state()

    def on_stop_clicked(self):
        """Stops live acquisition cleanly."""
        if self.runtime:
            self.runtime.stop(timeout=1.5)
            self.update_ui_state()

    def on_reconnect_clicked(self):
        """Triggers safe bounded reconnect asynchronously without blocking GUI event loop."""
        if not self.runtime:
            return
        if self._connect_worker and self._connect_worker.isRunning():
            return
        if self._reconnect_worker and self._reconnect_worker.isRunning():
            return  # Prevent duplicate reconnect workers / reconnect storms

        self.badge_connection.setText("YENİDEN BAĞLANIYOR...")
        self.badge_connection.setStyleSheet("background-color: #F1C40F; color: #2C3E50; border-radius: 4px; padding: 4px;")
        self.btn_reconnect.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(False)

        self._reconnect_worker = LiveReconnectWorker(self.runtime, max_attempts=3, timeout=1.5)
        self._reconnect_worker.reconnect_finished.connect(self._on_reconnect_completed)
        self._reconnect_worker.start()

    def _on_reconnect_completed(self, ok: bool, msg: str):
        """Slot invoked safely on Qt GUI thread when reconnect finishes."""
        if ok:
            QMessageBox.information(self, "Bağlantı Başarılı", msg)
        else:
            QMessageBox.critical(self, "Bağlantı Hatası", msg)
        self.update_ui_state()

    def on_filter_changed(self, category: str):
        """Changes active PID filter category."""
        self.active_category = category
        for cat, btn in self.btn_filters.items():
            btn.setChecked(cat == category)
        self.update_ui_state()

    def on_pid_row_selected(self, row: int, col: int):
        """Selects PID for live waveform trend display."""
        item = self.table_pids.item(row, 0)
        if item:
            pid = item.text()
            self.selected_pid = pid
            meta = DEFAULT_PID_CATALOG.get(pid, {"name": pid, "unit": ""})
            self.trend_widget.set_pid(pid, meta.get("name", pid), meta.get("unit", ""))

    def on_poll_dtc_clicked(self):
        """Polls DTCs safely via Mode 03 asynchronously using LiveDTCPollWorker."""
        if not self.runtime:
            return
        if self._dtc_worker and self._dtc_worker.isRunning():
            return  # Prevent rapid repeated clicks

        self.btn_poll_dtc.setEnabled(False)
        self.btn_poll_dtc.setText("Sorgulanıyor...")

        self._dtc_worker = LiveDTCPollWorker(self.runtime)
        self._dtc_worker.dtc_poll_finished.connect(self._on_dtc_poll_completed)
        self._dtc_worker.dtc_poll_error.connect(self._on_dtc_poll_error)
        self._dtc_worker.start()

    def _on_dtc_poll_completed(self, res: dict):
        """Slot invoked on Qt GUI thread when DTC poll finishes successfully."""
        try:
            active = res.get("active_dtcs", [])
            is_valid = res.get("is_valid_acquisition", True)
            if not is_valid:
                err_msg = res.get("error", "İletişim hatası")
                QMessageBox.warning(self, "DTC Okunamadı", f"DTC sorgusu başarısız oldu:\n{err_msg}")
            elif active:
                codes_list = [d["code"] if isinstance(d, dict) else str(d) for d in active]
                QMessageBox.warning(self, "DTC Bulundu", f"{len(active)} adet aktif arıza kodu tespit edildi:\n" + ", ".join(codes_list))
            else:
                QMessageBox.information(self, "DTC Sonucu", "ECU üzerinde aktif arıza kodu tespit edilmedi (Temiz).")
        finally:
            self.btn_poll_dtc.setEnabled(True)
            self.btn_poll_dtc.setText("🔍 DTC Sorgula (Mode 03)")
            self.update_ui_state()

    def _on_dtc_poll_error(self, err_msg: str):
        """Slot invoked on Qt GUI thread if DTC poll raised an unexpected exception."""
        try:
            QMessageBox.critical(self, "Hata", f"DTC sorgulama sırasında hata: {err_msg}")
        finally:
            self.btn_poll_dtc.setEnabled(True)
            self.btn_poll_dtc.setText("🔍 DTC Sorgula (Mode 03)")
            self.update_ui_state()

    def on_reset_faults_clicked(self):
        """Resets in-memory runtime safety faults. Strictly zero Mode 04."""
        if self.runtime:
            self.runtime.reset_runtime_faults()
            QMessageBox.information(self, "Sıfırlandı", "Yerel güvenlik hataları ve devre kesiciler sıfırlandı.\n(Not: Araç ECU hafızasına dokunulmadı)")
            self.update_ui_state()

    def closeEvent(self, event):
        """Clean shutdown of timer and background workers without orphan threads."""
        self.update_timer.stop()
        if self._connect_worker and self._connect_worker.isRunning():
            if self.runtime and hasattr(self.runtime, "adapter") and self.runtime.adapter:
                try:
                    self.runtime.adapter.disconnect()
                except Exception:
                    pass
            self._connect_worker.wait(1000)
        if self._reconnect_worker and self._reconnect_worker.isRunning():
            self._reconnect_worker.wait(1000)
        if self._dtc_worker and self._dtc_worker.isRunning():
            self._dtc_worker.wait(1000)
        super().closeEvent(event)


# =====================================================================
# 4. STANDALONE LIVE DIAGNOSTIC WINDOW
# =====================================================================

class LiveDiagnosticWindow(QMainWindow):
    """
    Standalone desktop window for live automotive diagnostics.
    Can be launched directly via `python live_ui.py`.
    """

    def __init__(self, runtime: Optional[LiveAcquisitionRuntime] = None):
        super().__init__()
        self.setWindowTitle("Seyyanen Canlı Teşhis ve Telemetri — Phase F-6")
        self.resize(1300, 850)
        self.live_widget = LiveDiagnosticWidget(runtime=runtime, parent=self)
        self.setCentralWidget(self.live_widget)

    def closeEvent(self, event):
        """Ensures background acquisition stops when window closes."""
        if self.live_widget.runtime and self.live_widget.runtime.is_running():
            self.live_widget.runtime.stop()
        super().closeEvent(event)


# =====================================================================
# 5. ENTRY POINT FOR STANDALONE LAUNCH
# =====================================================================

def main():
    """Launches standalone Live Diagnostic GUI."""
    app = QApplication(sys.argv)
    
    # Initialize engine & runtime
    from motor import AutoExpertEngine
    engine = AutoExpertEngine()
    engine.baglan()
    
    runtime = LiveAcquisitionRuntime(engine=engine)
    window = LiveDiagnosticWindow(runtime=runtime)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
