import sys
import os
import json
import subprocess
import glob
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path
import traceback
import ctypes

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QFileDialog,
    QStatusBar, QLabel, QHeaderView, QAbstractItemView, QScrollArea,
    QCheckBox, QSlider, QFrame, QMessageBox, QInputDialog, QProgressDialog,
    QStackedWidget
)
from PyQt6.QtGui import QFont, QColor, QIcon, QDesktopServices
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QObject, QThread, QUrl
from pyqtgraph import PlotWidget, InfiniteLine

# GÖREV 1: Kodları İçe Aktarma
try:
    import expert_system
    import raporlayici
    ANALYSIS_MODULES_AVAILABLE = True
except ImportError:
    ANALYSIS_MODULES_AVAILABLE = False
    print("UYARI: 'expert_system.py' veya 'raporlayici.py' bulunamadı. Rapor oluşturma devre dışı.")


class MainUI(QMainWindow):
    """Otomotiv Teşhis Cihazı - Masaüstü Arayüzü"""
    
    # Sinyal tanımlamaları
    file_analyzed = pyqtSignal(str)  # Dosya analizi başladığında
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Otomotiv Teşhis Cihazı - Ana Panel")
        self.setGeometry(100, 100, 1400, 900)
        self.base_dir = Path(__file__).resolve().parent
        
        # Veri saklama
        self.vehicle_info = {"marka": "Bilinmiyor", "model": "Bilinmiyor"}
        self.connection_status = {"port": "Bağlı Değil", "ecu": "ECU Yok"}
        self.history_file = self.base_dir / "history.json"
        
        # GÖREV 1: PDF klasörü oluştur
        self.pdf_folder = self.base_dir / "pdf"
        self.pdf_folder.mkdir(parents=True, exist_ok=True)
        print(f"[LOG] PDF klasörü: {self.pdf_folder}")
        
        # GÖREV 1-2: Satır indeksi -> (file_path, report_button) eşlemesi
        # self.row_data = {}  # Artık kullanılmıyor
        
        # UI'ı kur
        self.setup_ui()
        self.apply_light_theme()

        # GÖREV 6: Windows için Açık Tema Başlık Çubuğu (ctypes hatasını yakala)
        if sys.platform == "win32":
            try:
                # Pencerenin kimliğini (HWND) al ve int'e dönüştür
                hwnd = int(self.winId())
                # Windows 10/11'e "karanlık mod kullanma" sinyali gönder (0=Açık, 1=Koyu)
                # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(0)), ctypes.sizeof(ctypes.c_int))
            except Exception:
                # Başarısız olursa sessizce geç (hata mesajı yazdırma)
                pass
        
        # GÖREV 5: Dosya geçmişini yükle
        self.load_file_history()
        
        print("[LOG] Arayüz başarıyla hazırlandı, pencere açılıyor...")
        
    def setup_ui(self):
        """Ana kullanıcı arayüzünü oluştur"""
        # Ana container
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(15, 15, 15, 0)
        main_layout.setSpacing(15)
        
        # 1. ÜST BÖLÜM: 4 Buton (Yanyana)
        top_layout = QHBoxLayout()
        top_layout.setSpacing(10)
        
        self.btn_scan_vehicle = self.create_button("🔍 Araç Tara", 250, 60)
        self.btn_import_record = self.create_button("📂 Kayıt Ekle (İmport)", 250, 60)
        self.btn_obd_query = self.create_button("🔎 OBD Sorgu", 250, 60)
        self.btn_obd_connect = self.create_button("🔗 OBD Bağlan", 250, 60)
        self.btn_rename_file = self.create_button("✏️ İsim Düzenle", 250, 60)
        
        # Buton bağlantıları
        self.btn_import_record.clicked.connect(self.open_file_dialog)
        self.btn_scan_vehicle.clicked.connect(lambda: print("[LOG] Araç Tara Başladı..."))
        self.btn_obd_query.clicked.connect(lambda: print("[LOG] OBD Sorgu Başladı..."))
        self.btn_obd_connect.clicked.connect(lambda: print("[LOG] OBD Bağlantısı Deneniyor..."))
        self.btn_rename_file.clicked.connect(self.rename_selected_file)
        
        top_layout.addWidget(self.btn_scan_vehicle)
        top_layout.addWidget(self.btn_import_record)
        top_layout.addWidget(self.btn_obd_query)
        top_layout.addWidget(self.btn_obd_connect)
        top_layout.addWidget(self.btn_rename_file)
        
        main_layout.addLayout(top_layout)
        
        # 2. ORTA BÖLÜM: Tablo (Dosya Yönetimi)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Dosya Adı", "Tarih", "Boyut", "İşlem"])
        
        # Sütun genişlikleri
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        
        # Tablo stili
        self.table.setMinimumHeight(400)
        self.table.setAlternatingRowColors(True)
        
        # DÜZELTME 1: Hücreleri Read-Only yap
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        
        # GÖREV 3: Satır seçimini kesin yap ve Tab tuşu devre dışı
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setSortingEnabled(True)
        
        # GÖREV 4: İşlem sütununu (col 3) daha geniş yap
        self.table.setColumnWidth(3, 120)
        
        self.analysis_stack = QStackedWidget()
        self.analysis_placeholder = QLabel("Analiz paneli burada gorunecek.\nBir dosya secip 'Analiz' butonuna basin.")
        self.analysis_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.analysis_stack.addWidget(self.analysis_placeholder)
        self.analysis_panel = None

        content_layout = QHBoxLayout()
        content_layout.setSpacing(15)
        content_layout.addWidget(self.table, 1)
        content_layout.addWidget(self.analysis_stack, 2)
        main_layout.addLayout(content_layout)
        
        # 3. ALT BİLGİ ÇUBUĞU (Status Bar)
        status_bar = self.statusBar()
        status_bar.setMaximumHeight(40)
        
        # Sol taraf: Araç Bilgileri
        self.label_vehicle = QLabel("🚗 Araç: Bilinmiyor / Bilinmiyor")
        self.label_vehicle.setFont(QFont("Segoe UI", 10))
        
        # Sağ taraf: Bağlantı Durumu
        self.label_connection = QLabel("⚠️ Bağlantı: Port Yok | ECU Yok")
        self.label_connection.setFont(QFont("Segoe UI", 10))
        
        status_bar.addWidget(self.label_vehicle)
        status_bar.addPermanentWidget(self.label_connection)
        
        central_widget.setLayout(main_layout)
    
    def create_button(self, text: str, width: int = 150, height: int = 50) -> QPushButton:
        """Stilize butonu oluştur"""
        btn = QPushButton(text)
        btn.setFixedSize(width, height)
        btn.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn
    
    def apply_light_theme(self):
        """GÖREV 4: Endüstriyel renk paleti - Titanyum teması uygula"""
        stylesheet = """
            QMainWindow {
                background-color: #F2EFE5;  /* Titanyum arka plan */
            }
            
            QPushButton {
                background-color: #B4B4B8;  /* Titanyum panel */
                color: #2C3E50;
                border: 2px solid #C7C8CC;  /* Titanyum kenarlık */
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            
            QPushButton:hover {
                background-color: #A0A0A4;  /* Daha koyu titanyum */
            }
            
            QPushButton:pressed {
                background-color: #909094;  /* En koyu titanyum */
            }
            
            QTableWidget {
                background-color: #E3E1D9;  /* Titanyum tablo */
                alternate-background-color: #F2EFE5;  /* Titanyum arka plan */
                gridline-color: #C7C8CC;  /* Titanyum kenarlık */
                border: 2px solid #C7C8CC;  /* Titanyum kenarlık */
                border-radius: 6px;
                color: #2C3E50;
            }
            
            QTableWidget::item {
                padding: 8px;
                border: none;
                color: #2C3E50;
            }
            
            /* GÖREV 3: Tablo seçim stillemesi */
            QTableWidget::item:selected {
                background-color: #B4B4B8;
                color: #2C3E50;
            }
            
            QTableWidget {
                outline: none;
            }
            
            QHeaderView::section {
                background-color: #B4B4B8;  /* Titanyum panel */
                color: #2C3E50;
                padding: 8px;
                border: 1px solid #C7C8CC;  /* Titanyum kenarlık */
                font-weight: bold;
            }
            
            QStatusBar {
                background-color: #E3E1D9;  /* Titanyum tablo */
                color: #2C3E50;
                border-top: 2px solid #C7C8CC;  /* Titanyum kenarlık */
            }
            
            QStatusBar::item {
                border: none;
            }
            
            QLabel {
                color: #2C3E50;
                font-weight: bold;
            }
            /* GÖREV 4: Analiz butonunu responsive yapabileceği kadar esnekleştir */
            QTableWidget QPushButton { 
                margin: 2px; 
                background-color: #B4B4B8; 
                color: #2C3E50; 
                border-radius: 4px; 
                font-weight: bold; 
                padding: 4px 8px;
            }
            QTableWidget QPushButton:hover { background-color: #A0A0A4; }

            QMessageBox {
                background-color: #F2EFE5; /* Ana arka plan */
            }

            QMessageBox QLabel {
                color: #2C3E50; /* Koyu Gri Yazı */
                font-weight: normal; /* Normal font */
            }

            QMessageBox QPushButton { /* Standart buton stilini miras alır */
                min-width: 80px; /* Butonların çok küçük olmasını engelle */
            }
        """
        self.setStyleSheet(stylesheet)
    
    def open_file_dialog(self):
        """Dosya seçme diyalogunu aç (.csv, .json)"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Dosya Seç",
            "",
            "Desteklenen Dosyalar (*.csv *.json);;CSV Dosyaları (*.csv);;JSON Dosyaları (*.json)"
        )
        
        if file_path:
            self.add_file_to_table(file_path)
    
    def rename_selected_file(self):
        """GÖREV 1: Seçili dosyanın adını değiştir"""
        # Seçili satır var mı kontrol et
        selected_rows = set()
        for item in self.table.selectedItems():
            selected_rows.add(item.row())
        
        if len(selected_rows) != 1:
            QMessageBox.warning(self, "Uyarı", "Lütfen tam olarak bir dosya seçin.")
            return
        
        row = list(selected_rows)[0]
        item = self.table.item(row, 0)
        if not item:
            return
        
        # Mevcut dosya yolunu al
        current_path = item.data(Qt.ItemDataRole.UserRole)
        if not current_path or not os.path.exists(current_path):
            QMessageBox.critical(self, "Hata", "Dosya bulunamadı.")
            return
        
        current_name = Path(current_path).name
        
        # Yeni isim sor
        new_name, ok = QInputDialog.getText(
            self, 
            "Dosya Adını Düzenle", 
            f"Mevcut isim: {current_name}\nYeni isim girin:",
            text=current_name
        )
        
        if not ok or not new_name.strip():
            return
        
        new_name = new_name.strip()
        if new_name == current_name:
            return  # Değişiklik yok
        
        # Dosya uzantısını koru
        current_ext = Path(current_path).suffix
        if not new_name.endswith(current_ext):
            new_name += current_ext
        
        # Yeni yol oluştur
        parent_dir = Path(current_path).parent
        new_path = parent_dir / new_name
        
        # Dosya zaten var mı kontrol et
        if new_path.exists():
            QMessageBox.warning(self, "Uyarı", f"'{new_name}' isminde bir dosya zaten var.")
            return
        
        try:
            # Dosyayı yeniden adlandır
            os.rename(current_path, new_path)
            
            # Tabloyu güncelle
            item.setText(new_name)
            item.setData(Qt.ItemDataRole.UserRole, str(new_path))
            
            # History.json'i güncelle
            self.update_history_file(current_path, str(new_path))
            
            print(f"[LOG] Dosya yeniden adlandırıldı: {current_name} → {new_name}")
            QMessageBox.information(self, "Başarılı", f"Dosya adı '{new_name}' olarak değiştirildi.")
            
        except Exception as e:
            print(f"[HATA] Dosya yeniden adlandırılırken: {str(e)}")
            QMessageBox.critical(self, "Hata", f"Dosya adı değiştirilemedi:\n{str(e)}")
    
    def update_history_file(self, old_path: str, new_path: str):
        """History.json'deki dosya yolunu güncelle"""
        try:
            if not self.history_file.exists():
                return
            
            with open(self.history_file, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
            
            files = history_data.get("files", [])
            if old_path in files:
                idx = files.index(old_path)
                files[idx] = new_path
                
                with open(self.history_file, 'w', encoding='utf-8') as f:
                    json.dump(history_data, f, ensure_ascii=False, indent=2)
                
                print(f"[LOG] History.json güncellendi: {old_path} → {new_path}")
        
        except Exception as e:
            print(f"[HATA] History.json güncellenirken: {str(e)}")
    
    def add_file_to_table(self, file_path: str):
        """Tabloya dosya ekle ve GÖREV 1: PDF senkronizasyonu yap"""
        # GÖREV 2 (Çözüm 1): Satır eklemeden önce sıralamayı kapat
        self.table.setSortingEnabled(False)
        try:
            file_info = Path(file_path)
            filename = file_info.name

            # Dosya boyutu ve tarihi için `os.path.exists` kontrolü
            if os.path.exists(file_path):
                stat_info = file_info.stat()
                modification_time = datetime.fromtimestamp(stat_info.st_mtime)
                formatted_date = modification_time.strftime("%d.%m.%Y %H:%M")
                file_size = self.format_file_size(stat_info.st_size)
            else:
                formatted_date = "Dosya Yok"
                file_size = "0 KB"
            
            # GÖREV 1: PDF dosyasının bulunup bulunmadığını kontrol et
            base_name = Path(file_path).stem
            pdf_pattern = str(self.pdf_folder / f"rapor_{base_name}_*.pdf")
            existing_pdfs = glob.glob(pdf_pattern)
            has_valid_pdf = len(existing_pdfs) > 0 and all(os.path.exists(p) for p in existing_pdfs)

            # Yeni satır ekle
            row_position = self.table.rowCount()
            self.table.insertRow(row_position)
            
            # Satır yüksekliğini sabitle
            self.table.setRowHeight(row_position, 45)
            
            # Sütun 0: Dosya Adı
            item_filename = QTableWidgetItem(filename)
            item_filename.setFont(QFont("Segoe UI", 10))
            item_filename.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            item_filename.setData(Qt.ItemDataRole.UserRole, file_path)
            self.table.setItem(row_position, 0, item_filename)
            
            # Sütun 1: Tarih
            item_date = QTableWidgetItem(formatted_date)
            item_date.setFont(QFont("Segoe UI", 9))
            item_date.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row_position, 1, item_date)
            
            # Sütun 2: Boyut
            item_size = QTableWidgetItem(file_size)
            item_size.setFont(QFont("Segoe UI", 9))
            item_size.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row_position, 2, item_size)
            
            # GÖREV 1: Analiz butonunu veya Raporu Aç butonunu al
            if has_valid_pdf and len(existing_pdfs) > 0:
                # PDF var, "Raporu Aç" butonunu göster
                btn_action = QPushButton("🔴 Raporu Aç")
                btn_action.setStyleSheet("background-color: #E74C3C; color: white; border: none; border-radius: 4px; padding: 4px 8px; font-weight: bold;")
                pdf_to_open = existing_pdfs[0]  # İlk PDF'i aç
                btn_action.clicked.connect(lambda: self.open_report_file(pdf_to_open))
            else:
                # PDF yok, "Analiz" butonunu göster
                btn_action = QPushButton("🔍 Analiz")
                btn_action.setStyleSheet("background-color: #B4B4B8; color: #2C3E50; border-radius: 4px; padding: 4px 8px; font-weight: bold;")
                # GÖREV 2 (Çözüm 2): Statik satır indeksi yerine butonun kendisini gönder
                btn_action.clicked.connect(lambda _, b=btn_action: self.analyze_file_from_button(b))
            
            btn_action.setCursor(Qt.CursorShape.PointingHandCursor)
            self.table.setCellWidget(row_position, 3, btn_action)
            
            # print(f"[LOG] Dosya Eklendi: {filename} | {formatted_date} | {file_size}") # Çok kalabalık yapıyor
            
            # Dosya geçmişine kaydet
            self.save_file_history()
            
        except Exception as e:
            print(f"[HATA] Dosya eklenirken hata oluştu: {str(e)}")
        finally:
            # GÖREV 2 (Çözüm 1): İşlem bitince sıralamayı tekrar aç
            self.table.setSortingEnabled(True)
    
    def analyze_file(self, filename: str, file_path: str):
        """Dosya analizi başlat - AnalysisPanel'i MainUI içine göm"""
        print(f"\n{'=' * 60}")
        print(f"[TELEMETRI AÇILIYOR...]")
        print(f"Dosya: {filename}")
        print(f"Yol: {file_path}")
        print(f"Zaman: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
        print(f"{'=' * 60}\n")
        
        if self.analysis_panel is not None:
            self.analysis_stack.removeWidget(self.analysis_panel)
            self.analysis_panel.deleteLater()
            self.analysis_panel = None

        self.analysis_panel = AnalysisPanel(file_path=file_path, base_dir=self.base_dir)
        self.analysis_panel.report_ready.connect(self.on_report_ready_for_file)
        self.analysis_stack.addWidget(self.analysis_panel)
        self.analysis_stack.setCurrentWidget(self.analysis_panel)
        
        self.file_analyzed.emit(file_path)

    def on_report_ready_for_file(self, source_file_path: str, pdf_path: str):
        """Rapor hazır olduğunda ilgili tablo satırının butonunu güncelle."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if not item:
                continue
            row_path = item.data(Qt.ItemDataRole.UserRole)
            if str(row_path) != str(source_file_path):
                continue
            button = self.table.cellWidget(row, 3)
            if isinstance(button, QPushButton):
                self.set_report_button_opened(button, pdf_path)
            break
    
    def analyze_file_by_row(self, row_position: int):
        """GÖREV 1: Satırdan dosya yolunu okuyarak analiz başlat"""
        try:
            # Satırın 0. sütunundaki item'ı al
            item = self.table.item(row_position, 0)
            if not item:
                QMessageBox.warning(self, "Hata", "Dosya bilgisi bulunamadı.")
                return
            
            # UserRole'dan güncel dosya yolunu al
            file_path = item.data(Qt.ItemDataRole.UserRole)
            if not file_path or not os.path.exists(file_path):
                QMessageBox.critical(self, "Hata", "Dosya bulunamadı. Silinmiş olabilir.")
                return
            
            # Dosya adını al
            filename = Path(file_path).name
            
            # Analizi başlat
            self.analyze_file(filename, file_path)
            
        except Exception as e:
            print(f"[HATA] Satır analizi: {str(e)}")
            QMessageBox.critical(self, "Hata", f"Satır analizi başarısız:\n{str(e)}")

    def analyze_file_from_button(self, button: QPushButton):
        """GÖREV 2: Butonun bulunduğu satırı bularak analizi dinamik olarak başlatır."""
        try:
            for row in range(self.table.rowCount()):
                if self.table.cellWidget(row, 3) == button:
                    item = self.table.item(row, 0)
                    if not item:
                        QMessageBox.warning(self, "Hata", "Satırda dosya bilgisi bulunamadı.")
                        return

                    file_path = item.data(Qt.ItemDataRole.UserRole)
                    if not file_path or not os.path.exists(file_path):
                        QMessageBox.critical(self, "Hata", "Dosya yolu geçersiz veya dosya silinmiş.")
                        return

                    filename = Path(file_path).name
                    self.analyze_file(filename, file_path)
                    return  # Eşleşme bulundu, fonksiyondan çık
        except Exception as e:
            print(f"[HATA] Butondan analiz başlatılırken: {str(e)}")
            QMessageBox.critical(self, "Kritik Hata", f"Analiz başlatılamadı:\n{str(e)}")
    
    def run_expert_system(self, row_position: int):
        """Satırdaki dosyayı doğrudan table item üstünden analiz eder."""
        try:
            item = self.table.item(row_position, 0)
            if not item:
                QMessageBox.warning(self, "Hata", "Seçili satırda dosya bilgisi bulunamadı.")
                return
            file_path = item.data(Qt.ItemDataRole.UserRole)
            if not file_path or not Path(file_path).exists():
                QMessageBox.warning(self, "Hata", "Seçili dosya bulunamadı.")
                return
            self.analyze_file(Path(file_path).name, file_path)
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Analiz başlatılamadı:\n{e}")
    
    def set_report_button_opened(self, btn_report: QPushButton, pdf_path: str):
        """Rapor butonunu 'Açma' durumuna dönüştür (kırmızı, tıklanabilir)"""
        btn_report.setText("🔴 Raporu Aç")
        btn_report.setStyleSheet("""
            background-color: #E74C3C;
            color: #FFFFFF;
            border: none;
            border-radius: 5px;
            padding: 8px 12px;
            font-weight: bold;
        """)
        btn_report.setEnabled(True)
        
        # Eski bağlantıları kaldır ve yeni bağlantı ekle
        try:
            btn_report.clicked.disconnect()
        except:
            pass  # Eğer bağlantı yoksa ignore et
        
        btn_report.clicked.connect(lambda: self.open_report_file(pdf_path))
    
    def open_report_file(self, pdf_path: str):
        """GÖREV 2: PDF dosyasını varsayılan okuyucu ile aç"""
        try:
            if not os.path.exists(pdf_path):
                QMessageBox.warning(self, "Hata", f"PDF dosyası bulunamadı:\n{pdf_path}")
                return
            
            # İşletim sistemine göre aç
            if sys.platform == "win32":
                os.startfile(pdf_path)
            elif sys.platform == "darwin":  # macOS
                subprocess.Popen(["open", pdf_path])
            else:  # Linux
                subprocess.Popen(["xdg-open", pdf_path])
            
            print(f"[LOG] Rapor açıldı: {pdf_path}")
        
        except Exception as e:
            print(f"[HATA] Rapor açılırken: {str(e)}")
            QMessageBox.critical(self, "Hata", f"Rapor açılamadı:\n{str(e)}")
    
    @staticmethod
    def format_file_size(bytes_size: int) -> str:
        """Dosya boyutunu insan tarafından okunabilir formata dönüştür"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f} TB"
    
    def update_vehicle_info(self, marka: str, model: str):
        """Araç bilgilerini güncelle"""
        self.vehicle_info = {"marka": marka, "model": model}
        self.label_vehicle.setText(f"🚗 Araç: {marka} / {model}")
    
    def update_connection_status(self, port: str, ecu: str):
        """Bağlantı durumunu güncelle"""
        self.connection_status = {"port": port, "ecu": ecu}
        status_text = f"✅ Bağlantı: {port} | {ecu}" if port != "Bağlı Değil" else f"⚠️ Bağlantı: {port} | {ecu}"
        self.label_connection.setText(status_text)
    
    def load_file_history(self):
        """GÖREV 5: history.json'dan dosya yollarını yükle ve tabloya ekle"""
        print("[LOG] Geçmişten dosyalar yükleniyor...")
        try:
            if not self.history_file.exists():
                print(f"[LOG] Geçmiş dosyası bulunamadı: {self.history_file}")
                return
            
            with open(self.history_file, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
            
            file_paths = history_data.get("files", [])
            
            # GÖREV 2: Hatalı dosya yüklemelerini yakalamak için döngü içinde try-except
            for file_path in file_paths:
                try:
                    # Dosya var mı kontrolü add_file_to_table içinde yapılacak
                    self.add_file_to_table(file_path)
                except Exception as e:
                    print(f"[HATA] Geçmişteki bir dosya ({file_path}) yüklenirken hata oluştu, atlanıyor: {e}")
        
        except (json.JSONDecodeError, IOError) as e:
            print(f"[HATA] Geçmiş dosyası ({self.history_file}) okunamadı veya bozuk: {e}")
        except Exception as e:
            print(f"[KRİTİK HATA] Geçmiş yüklenirken beklenmedik bir hata oluştu: {e}")
    
    def save_file_history(self):
        """GÖREV 5: Tablodaki tüm dosya yollarını history.json'a kaydet"""
        try:
            file_paths = []
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item:
                    # GÖREV 5: İtem'dan tam dosya yolunu al (Qt.UserRole)
                    full_path = item.data(Qt.ItemDataRole.UserRole)
                    if full_path:
                        file_paths.append(full_path)
            
            history_data = {"files": file_paths}
            
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(history_data, f, ensure_ascii=False, indent=2)
            
            print(f"[LOG] {len(file_paths)} dosya geçmişe kaydedildi")
        
        except Exception as e:
            print(f"[HATA] Geçmiş kaydedilirken hata: {str(e)}")


class AnalysisWorker(QObject):
    """
    Analiz ve raporlama işlemlerini arka planda yürüten worker.
    """
    finished = pyqtSignal(bool, str)  # Başarı durumu (bool) ve PDF yolu (str) ile tamamlandı sinyali
    error = pyqtSignal(str)     # Hata mesajı sinyali
    progress = pyqtSignal(str)  # İlerleme metni sinyali

    def __init__(self, df, pdf_path):
        super().__init__()
        self.df = df
        self.pdf_path = pdf_path

    def run(self):
        """
        Yeni expert_system ve raporlayici modüllerini kullanarak
        analiz ve raporlama işlemini başlatır.
        """
        try:
            if not ANALYSIS_MODULES_AVAILABLE:
                raise ImportError("Gerekli analiz modülleri ('expert_system', 'raporlayici') yüklenemedi.")

            # Adım 1: Uzman sistem analizi
            self.progress.emit("Uzman sistem telemetri verilerini analiz ediyor...")
            QThread.msleep(200) # Arayüzün güncellenmesi için küçük bir bekleme
            
            # Yeni expert_system.py'deki analiz_et fonksiyonunu çağır
            teshis_sonuclari = expert_system.analiz_et(self.df)

            # Adım 2: PDF Raporu Oluşturma
            self.progress.emit("Grafikler ve PDF raporu oluşturuluyor...")
            QThread.msleep(200)

            # Yeni raporlayici.py'deki köprü fonksiyonunu çağır
            basarili_mi = raporlayici.pdf_olustur(
                teshis_sonuclari=teshis_sonuclari,
                df=self.df, 
                pdf_path=self.pdf_path
            )

            self.finished.emit(basarili_mi, self.pdf_path if basarili_mi else "")

        except Exception as e:
            error_msg = f"Analiz sırasında beklenmedik bir hata oluştu:\n{e}\n{traceback.format_exc()}"
            self.error.emit(error_msg)


class AnalysisPanel(QWidget):
    """MainUI içine gömülü telemetri ve analiz paneli."""
    report_ready = pyqtSignal(str, str)  # source_file_path, pdf_path
    
    COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]
    
    def __init__(self, file_path: str, base_dir: Path):
        super().__init__()
        self.file_path = file_path
        self.base_dir = base_dir
        
        self.df = None
        self.sensor_names = []
        self.selected_sensors = set()
        self.color_map = {}
        self.thread = None
        self.worker = None
        self.pdf_path = None
        self.progress_dialog = None
        self.plot_items = {}
        self.legend = None
        
        if not self.load_and_clean_data():
            # QTimer.singleShot(0, self.close) # Hata durumunda pencereyi hemen kapat
            return
        
        self.setup_ui()
        self.apply_light_theme()

    def load_and_clean_data(self):
        """Dosyayı oku (CSV/JSON) ve veriyi temizle"""
        try:
            file_ext = Path(self.file_path).suffix.lower()
            try:
                if file_ext == ".csv":
                    self.df = self._read_csv_robust(self.file_path)
                elif file_ext == ".json": self.df = pd.read_json(self.file_path)
                else: raise ValueError(f"Desteklenmeyen dosya formatı: {file_ext}")
            except Exception as e:
                QMessageBox.critical(self, "Dosya Okunamadı", f"'{Path(self.file_path).name}' dosyası bozuk veya okunamıyor.\n\nHata: {e}")
                return False

            self.df.dropna(axis=1, how='all', inplace=True)
            numeric_df = self.df.select_dtypes(include=np.number)
            valid_columns = [col for col in numeric_df.columns if numeric_df[col].notna().sum() / len(numeric_df[col]) >= 0.05]
            
            self.df = numeric_df[valid_columns].ffill().bfill().fillna(0)
            self.sensor_names = list(self.df.columns)
            
            if not self.sensor_names:
                raise ValueError("Dosyada geçerli sayısal sensör verisi bulunamadı!")

            for idx, sensor in enumerate(self.sensor_names):
                self.color_map[sensor] = self.COLORS[idx % len(self.COLORS)]
            
            print(f"[LOG] Veri temizlendi: {len(self.df)} satır, {len(self.sensor_names)} sensör")
            return True
        except Exception as e:
            error_msg = f"Veri yükleme ve temizleme sırasında bir hata oluştu:\n\n{e}"
            QMessageBox.critical(self, "Veri Yükleme Hatası", error_msg)
            print(f"[HATA] {error_msg}")
            return False

    @staticmethod
    def _read_csv_robust(file_path: str) -> pd.DataFrame:
        """CSV dosyasını utf-8 + delimiter fallback ile yükler."""
        try:
            return pd.read_csv(file_path, encoding="utf-8", encoding_errors="replace", sep=",")
        except Exception:
            return pd.read_csv(file_path, encoding="utf-8", encoding_errors="replace", sep=";")

    def setup_ui(self):
        """GÖREV 1: Sekmesiz, tek parça UI oluştur"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # ============================================================
        # SOL KONTROL PANELİ
        # ============================================================
        left_panel = QFrame()
        left_panel.setMaximumWidth(320)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 10, 10, 10)
        
        sensor_label = QLabel(f"Sensörler ({len(self.sensor_names)})")
        sensor_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        left_layout.addWidget(sensor_label)
        
        # GÖREV 2: "Tümünü Seç / Temizle" Butonu
        self.btn_toggle_all = QPushButton("☑ Tümünü Seç / Temizle")
        self.btn_toggle_all.clicked.connect(self.toggle_all_sensors)
        left_layout.addWidget(self.btn_toggle_all)

        # Sensör Listesi
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        self.sensor_checkboxes = {}
        for sensor_name in self.sensor_names:
            cb = QCheckBox(sensor_name)
            cb.stateChanged.connect(lambda state, s=sensor_name: self.toggle_sensor(s, state))
            scroll_layout.addWidget(cb)
            self.sensor_checkboxes[sensor_name] = cb
        
        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        left_layout.addWidget(scroll_area)
        
        left_layout.addStretch() # Butonu aşağı itmek için

        # GÖREV 3: Rapor Butonu
        self.pdf_button = QPushButton("📄 Rapor Oluştur")
        self.pdf_button.setMinimumHeight(60) # Butonu daha büyük yap
        self.pdf_button.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self.pdf_button.clicked.connect(self.run_expert_system)
        left_layout.addWidget(self.pdf_button)

        # ============================================================
        # SAĞ GRAFİK PANELİ
        # ============================================================
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        self.plot_widget = PlotWidget()
        self.plot_widget.setLabel("left", "Değer")
        self.plot_widget.setLabel("bottom", "Zaman (Satır İndeksi)")
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.getViewBox().setMouseEnabled(x=True, y=False)
        self.plot_widget.setLimits(xMin=0, xMax=len(self.df))
        self.vertical_line = InfiniteLine(pos=0, angle=90, pen={"color": "red", "width": 2})
        self.plot_widget.addItem(self.vertical_line)
        self.legend = self.plot_widget.addLegend()
        self.update_graph() # Başlangıçta boş grafiği çiz
        right_layout.addWidget(self.plot_widget)

        # Zaman Kaydırıcısı (Scrubber)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, len(self.df) - 1 if self.df is not None and not self.df.empty else 0)
        self.slider.sliderMoved.connect(self.on_slider_moved)
        right_layout.addWidget(QLabel("Zaman Kaydırıcısı:"))
        right_layout.addWidget(self.slider)

        self.time_info_label = QLabel("Satır: 0 | (Sensör seçin)")
        self.time_info_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        right_layout.addWidget(self.time_info_label)

        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel, 1) # Grafik panelinin daha fazla yer kaplamasını sağla

    def toggle_all_sensors(self):
        """GÖREV 2: Tüm sensör checkbox'larının durumunu tersine çevirir."""
        # Eğer hepsi seçili değilse, hepsini seç. Aksi halde tüm seçimleri kaldır.
        are_all_checked = all(cb.isChecked() for cb in self.sensor_checkboxes.values())
        new_state = Qt.CheckState.Unchecked if are_all_checked else Qt.CheckState.Checked
        
        for checkbox in self.sensor_checkboxes.values():
            checkbox.setCheckState(new_state)
        # update_graph() zaten toggle_sensor içinde çağrılıyor, bu yüzden toplu işlem sonrası
        # son bir güncelleme yeterli olacaktır, ancak her bir checkbox stateChanged sinyali
        # gönderdiği için zaten grafik güncellenmiş olacak.
        # Manuel olarak son durumu garantilemek için çağırabiliriz:
        self.update_graph()
        self.on_slider_moved(self.slider.value())


    def run_expert_system(self):
        """GÖREV 4: Analiz işlemini QProgressDialog ile başlatır."""
        if not ANALYSIS_MODULES_AVAILABLE:
            QMessageBox.critical(self, "Modül Hatası", "Analiz modülleri ('expert_system.py', 'raporlayici.py') bulunamadı.")
            return

        file_name = Path(self.file_path).stem
        pdf_folder = self.base_dir / "pdf"
        pdf_folder.mkdir(parents=True, exist_ok=True)
        self.pdf_path = str(pdf_folder / f"rapor_{file_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf")

        self.pdf_button.setEnabled(False)
        self.pdf_button.setText("⏳ Rapor Hazırlanıyor...")

        # GÖREV 4: QProgressDialog oluştur
        self.progress_dialog = QProgressDialog("Yapay zeka verileri analiz ediyor, lütfen bekleyin...", "İptal", 0, 0, self)
        self.progress_dialog.setWindowTitle("Rapor Oluşturuluyor")
        self.progress_dialog.setCancelButton(None) # İptal butonu olmasın
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.show()

        self.thread = QThread()
        self.worker = AnalysisWorker(df=self.df, pdf_path=self.pdf_path)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_analysis_progress)
        self.worker.error.connect(self.on_analysis_error)
        self.worker.finished.connect(self.on_analysis_finished)
        self.worker.finished.connect(self._shutdown_thread)
        self.worker.error.connect(lambda _: self._shutdown_thread(False, ""))
        
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._clear_thread_references)
        self.worker.finished.connect(self.worker.deleteLater)
        
        self.thread.start()

    def on_analysis_progress(self, message):
        """GÖREV 4: QProgressDialog'u günceller."""
        if self.progress_dialog:
            self.progress_dialog.setLabelText(f"⏳ {message}")

    def on_analysis_error(self, message):
        """Worker hatasında dialogu kapatır ve butonu sıfırlar."""
        if self.progress_dialog:
            self.progress_dialog.close()
        QMessageBox.critical(self, "Analiz Hatası", message)
        self.reset_pdf_button()

    def on_analysis_finished(self, success, pdf_path):
        """GÖREV 4: Analiz bitiminde sonuç popup'ı gösterir ve butonu günceller."""
        if self.progress_dialog:
            self.progress_dialog.close()

        if success:
            QMessageBox.information(self, "Başarılı", "Rapor başarıyla oluşturuldu!")
            self.pdf_path = pdf_path
            self.pdf_button.setText("🔴 Raporu Aç")
            self.pdf_button.setStyleSheet("background-color: #e74c3c; color: white;")
            self.pdf_button.setEnabled(True)
            try: self.pdf_button.clicked.disconnect()
            except: pass
            self.pdf_button.clicked.connect(self.open_report_file)
            self.report_ready.emit(self.file_path, pdf_path)
        else:
            QMessageBox.critical(self, "Hata", "PDF raporu oluşturulamadı.")
            self.reset_pdf_button()

    def reset_pdf_button(self):
        """Butonu başlangıçtaki haline döndürür."""
        self.pdf_button.setEnabled(True)
        self.pdf_button.setText("📄 Rapor Oluştur")
        self.apply_light_theme() # Stilini temanın parçası olarak ayarla
        try: self.pdf_button.clicked.disconnect()
        except: pass
        self.pdf_button.clicked.connect(self.run_expert_system)

    def _shutdown_thread(self, *_):
        """Worker bittiğinde thread'i güvenli kapat."""
        if self.thread and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait(3000)

    def _clear_thread_references(self):
        self.thread = None
        self.worker = None
    
    def open_report_file(self):
        """Oluşturulan PDF dosyasını açar."""
        if not self.pdf_path or not os.path.exists(self.pdf_path):
            QMessageBox.warning(self, "Hata", f"PDF dosyası bulunamadı:\n{self.pdf_path}")
            return
        
        url = QUrl.fromLocalFile(self.pdf_path)
        QDesktopServices.openUrl(url)
        print(f"[LOG] Rapor açıldı: {self.pdf_path}")
    
    def toggle_sensor(self, sensor_name: str, state):
        if state == Qt.CheckState.Checked.value: self.selected_sensors.add(sensor_name)
        else: self.selected_sensors.discard(sensor_name)
        self.update_graph()
        self.on_slider_moved(self.slider.value())
    
    def update_graph(self):
        active_sensors = {s for s in self.selected_sensors if s in self.df.columns}
        removed = set(self.plot_items.keys()) - active_sensors

        for sensor in removed:
            self.plot_widget.removeItem(self.plot_items[sensor])
            del self.plot_items[sensor]

        for sensor in sorted(active_sensors):
            if sensor in self.plot_items:
                continue
            pen_color = self.color_map.get(sensor, "#1f77b4")
            self.plot_items[sensor] = self.plot_widget.plot(
                self.df.index, self.df[sensor], pen=pen_color, name=sensor
            )

        if not active_sensors:
            self.plot_widget.setTitle("(Grafik için sol panelden sensör seçin)")
        else:
            self.plot_widget.setTitle(f"Grafik - {len(active_sensors)} Sensör")
    
    def on_slider_moved(self, position: int):
        self.vertical_line.setPos(position)
        info_parts = [f"Satır: {position}"]
        for sensor in sorted(list(self.selected_sensors)):
            if sensor in self.df.columns:
                value = self.df.at[position, sensor]
                formatted_val = f"{int(value)}" if pd.api.types.is_integer_dtype(self.df[sensor].dtype) else f"{value:.2f}"
                info_parts.append(f"{sensor}: {formatted_val}")
        self.time_info_label.setText(" | ".join(info_parts) if self.selected_sensors else "Satır: 0 | (Sensör seçin)")
    
    def apply_light_theme(self):
        self.plot_widget.setBackground('w')
        for axis in ['left', 'bottom']: self.plot_widget.getAxis(axis).setPen(color='#2C3E50')
        self.plot_widget.setTitle(color="#2C3E50")
        self.time_info_label.setStyleSheet("background-color: #E3E1D9; color: #2C3E50; padding: 10px; border-radius: 5px;")

        stylesheet = """
            AnalysisPanel, QWidget { background-color: #F2EFE5; }
            QFrame { background-color: #E3E1D9; border: 2px solid #C7C8CC; border-radius: 6px; }
            QLabel { color: #2C3E50; font-weight: bold; }
            QCheckBox { color: #2C3E50; spacing: 10px; padding: 6px; font-weight: bold; }
            QCheckBox::indicator { width: 20px; height: 20px; border-radius: 4px; border: 2px solid #C7C8CC; }
            QCheckBox::indicator:unchecked { background-color: #F2EFE5; }
            QCheckBox::indicator:checked { background-color: #2C3E50; }
            QScrollArea { background-color: #E3E1D9; border: 1px solid #C7C8CC; border-radius: 4px; }
            QSlider::groove:horizontal { border: 1px solid #C7C8CC; height: 8px; background: #F2EFE5; border-radius: 4px; }
            QSlider::handle:horizontal { background: #B4B4B8; border: 1px solid #C7C8CC; width: 18px; margin: -6px 0; border-radius: 9px; }
            QPushButton {
                background-color: #B4B4B8; color: #2C3E50; border: 2px solid #C7C8CC;
                border-radius: 6px; padding: 8px 16px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background-color: #A0A0A4; }
            # GÖREV 3: Rapor Butonu Özel Stili
            QPushButton#PdfButton { 
                font-size: 14px; min-height: 60px;
            }
        """
        self.setStyleSheet(stylesheet)
        self.pdf_button.setObjectName("PdfButton") # Stil için ID ata
        self.pdf_button.style().unpolish(self.pdf_button) # Stilin yeniden uygulanmasını sağla
        self.pdf_button.style().polish(self.pdf_button)


def main():
    """Uygulamayı başlat"""
    app = QApplication(sys.argv)
    window = MainUI()
    QApplication.processEvents()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
