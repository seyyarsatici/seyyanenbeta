import os
from colorama import Fore, Back, Style, init

# Initialize colorama with autoreset
init(autoreset=True)

class Dashboard:
    """
    Akıllı Dashboard Sistemi - V70 Smart Pulse
    Colorama ile renkli, faz-odaklı terminal arayüzü
    """
    
    # Renk Paleti
    CYAN = Fore.CYAN + Style.BRIGHT
    YELLOW = Fore.YELLOW + Style.BRIGHT
    RED = Fore.RED + Style.BRIGHT
    GREEN = Fore.GREEN + Style.BRIGHT
    WHITE = Fore.WHITE + Style.BRIGHT
    MAGENTA = Fore.MAGENTA + Style.BRIGHT
    BLUE = Fore.BLUE + Style.BRIGHT
    
    # RPM için gradyan renkler
    @staticmethod
    def rpm_color(rpm, max_rpm=7000):
        """RPM değerine göre renk döndür (yeşil -> sarı -> kırmızı)"""
        ratio = min(rpm / max_rpm, 1.0)
        if ratio < 0.5:
            return Fore.GREEN + Style.BRIGHT
        elif ratio < 0.75:
            return Fore.YELLOW + Style.BRIGHT
        else:
            return Fore.RED + Style.BRIGHT
    
    @staticmethod
    def clear_screen():
        """Ekranı temizle - Çapraz platform desteği (Windows/Linux)"""
        os.system('cls' if os.name == 'nt' else 'clear')
    
    @staticmethod
    def print_header(text, color=None):
        """Başlık yazdır"""
        if color is None:
            color = Dashboard.CYAN
        line = "═" * 70
        print(f"\n{color}╔{line}╗")
        print(f"{color}║ {text:^68} ║")
        print(f"{color}╚{line}╝{Style.RESET_ALL}")
    
    @staticmethod
    def print_box(lines, color=None):
        """Kutulu mesaj yazdır"""
        if color is None:
            color = Dashboard.WHITE
        
        max_len = max(len(line) for line in lines)
        top = f"{color}╔{'═' * (max_len + 2)}╗{Style.RESET_ALL}"
        bottom = f"{color}╚{'═' * (max_len + 2)}╝{Style.RESET_ALL}"
        
        print(top)
        for line in lines:
            print(f"{color}║ {line:<{max_len}} ║{Style.RESET_ALL}")
        print(bottom)
    
    @staticmethod
    def preflight_check(desteklenen_pidler, ariza_kodlari):
        """
        Pre-Flight Check - Sistem Hazırlık Kontrolü
        Kritik sensörleri listeler ve sistem durumunu gösterir
        """
        Dashboard.clear_screen()
        Dashboard.print_header("PRE-FLIGHT CHECK - SİSTEM KONTROLÜ", Dashboard.CYAN)
        
        print(f"\n{Dashboard.WHITE}╔════════════════════════════════════════════════════════════════════╗")
        print(f"║ {'SENSÖR DURUMU':<40} {'DURUM':<26} ║")
        print(f"╠════════════════════════════════════════════════════════════════════╣")
        
        # Kritik sensör listesi
        critical_sensors = {
            "010C": "RPM Sensörü",
            "010B": "MAP Sensörü (Hava Basıncı)",
            "0105": "ECT Sensörü (Motor Sıcaklığı)",
            "0111": "TPS Sensörü (Gaz Kelebeği)",
            "0106": "STFT (Kısa Süreli Yakıt)",
            "0107": "LTFT (Uzun Süreli Yakıt)",
        }
        
        all_ok = True
        for pid, name in critical_sensors.items():
            if pid in desteklenen_pidler:
                status = f"{Dashboard.GREEN}[✓] HAZIR{Style.RESET_ALL}"
            else:
                status = f"{Dashboard.RED}[✗] YANIT YOK!{Style.RESET_ALL}"
                all_ok = False
            print(f"║ {name:<40} {status:<26} ║")
        
        print(f"╚════════════════════════════════════════════════════════════════════╝{Style.RESET_ALL}")
        
        # Arıza Durumu
        if ariza_kodlari:
            print(f"\n{Dashboard.YELLOW}⚠️  UYARI: {len(ariza_kodlari)} adet arıza kodu tespit edildi!")
            for kod in ariza_kodlari[:3]:  # İlk 3 tanesi
                print(f"   └─ {Dashboard.RED}{kod}{Style.RESET_ALL}")
        else:
            print(f"\n{Dashboard.GREEN}✓ SİSTEM TEMİZ - Arıza kodu yok{Style.RESET_ALL}")
        
        # Final durum
        print("\n" + "═" * 70)
        if all_ok and not ariza_kodlari:
            print(f"{Dashboard.GREEN}║ SİSTEM HAZIR ║ LÜTFEN MARŞ BASIN VE TESPİTE BAŞLAYIN...{Style.RESET_ALL}")
        elif all_ok:
            print(f"{Dashboard.YELLOW}║ SİSTEM HAZIR ║ UYARI: ARIZA KODLARI MEVCUT{Style.RESET_ALL}")
        else:
            print(f"{Dashboard.RED}║ UYARI ║ BAZI SENSÖRLER YANIT VERMİYOR - TEST EDİLEBİLİR{Style.RESET_ALL}")
        print("═" * 70 + "\n")
    
    @staticmethod
    def show_koeo_banner(voltaj, neden="Sistem başlatıldı"):
        """KOEO Fazı Banner - Kontak Açık, Motor Kapalı"""
        # V112: None koruması — float() cast ile NoneType crash engellenir
        voltaj = float(voltaj or 0.0)
        Dashboard.clear_screen()
        Dashboard.print_header("KOEO MODU - KONTAK AÇIK", Dashboard.BLUE)
        
        aku_durum = "İYİ" if voltaj > 12.2 else "DÜŞÜK"
        aku_renk = Dashboard.GREEN if voltaj > 12.2 else Dashboard.YELLOW
        
        lines = [
            f"DURUM         : Kontak Açık, Motor Kapalı",
            f"BEKLENİYOR    : Marş Butonuna Basın",
            f"AKÜ VOLTAJ    : {voltaj:.1f}V ({aku_renk}{aku_durum}{Style.RESET_ALL})",
            f"GEÇİŞ NEDENİ  : {Dashboard.YELLOW}{neden}{Style.RESET_ALL}"
        ]
        Dashboard.print_box(lines, Dashboard.WHITE)
    
    @staticmethod
    def show_cranking_banner(voltaj, neden="Voltaj düştü, marş başladı"):
        """CRANKING Fazı Banner - Marş Esnasında"""
        # V112: None koruması
        voltaj = float(voltaj or 0.0)
        Dashboard.clear_screen()
        Dashboard.print_header("CRANKING - MARŞ ATILIYOR", Dashboard.YELLOW)
        
        aku_durum = "SAĞLAM" if voltaj > 9.0 else "ZAYIF"
        aku_renk = Dashboard.GREEN if voltaj > 9.0 else Dashboard.RED
        
        lines = [
            f"DURUM         : Marş Başlatıcı Aktif",
            f"AKÜ VOLTAJ    : {voltaj:.1f}V ({aku_renk}{aku_durum}{Style.RESET_ALL})",
            f"BEKLENİYOR    : Motor Çalışma Başlayacak...",
            f"GEÇİŞ NEDENİ  : {Dashboard.YELLOW}{neden}{Style.RESET_ALL}"
        ]
        Dashboard.print_box(lines, Dashboard.YELLOW)
    
    @staticmethod
    def show_warmup_banner(ect_current, target_ect=90, neden="Motor çalıştı, ısınma başladı"):
        """WARMUP Fazı Banner - Isınma"""
        Dashboard.clear_screen()
        Dashboard.print_header("ISINMA MODU - MOTOR TEMPERATURE RISING", Dashboard.CYAN)
        
        # Progress bar
        progress = min(ect_current / target_ect, 1.0)
        bar_length = 20
        filled = int(progress * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)
        
        lines = [
            f"DURUM         : Motor Isınıyor",
            f"HEDEF SICAKLIK: {target_ect}°C",
            f"ŞU ANKI SICAKLIK: {ect_current}°C [{bar}] %{int(progress*100)}",
            f"GEÇİŞ NEDENİ  : {Dashboard.YELLOW}{neden}{Style.RESET_ALL}"
        ]
        Dashboard.print_box(lines, Dashboard.CYAN)
    
    @staticmethod
    def show_hot_banner(neden="ECT hedef sıcaklığa ulaştı"):
        """HOT Fazı Banner - Normal Çalışma"""
        Dashboard.clear_screen()
        Dashboard.print_header("NORMAL ÇALIŞMA - RÖLANTI ÖLÇÜMÜ", Dashboard.GREEN)
        
        lines = [
            f"DURUM         : Motor Normal Sıcaklıkta",
            f"ÖLÇ.YAPILIYOR : Rölanti Stabilitesi, Yakıt Sapması",
            f"BEKLENİYOR    : Sabit Rölanti Koşulları",
            f"GEÇİŞ NEDENİ  : {Dashboard.YELLOW}{neden}{Style.RESET_ALL}"
        ]
        Dashboard.print_box(lines, Dashboard.GREEN)
    
    @staticmethod
    def show_load_banner(power_pct, neden="Yüksek TPS veya LOAD tespit edildi"):
        """LOAD/DYNO Fazı Banner - Performans Testi"""
        Dashboard.clear_screen()
        Dashboard.print_header("PERFORMANS TESTİ - YÜK ALTINDA", Dashboard.MAGENTA)
        
        power_color = Dashboard.GREEN if power_pct > 90 else (Dashboard.YELLOW if power_pct > 80 else Dashboard.RED)
        
        lines = [
            f"DURUM         : Performans Testi Aktif",
            f"TAHMİNİ YÜK  : {power_color}%{power_pct:.0f} ⚡ (Relatif){Style.RESET_ALL}",
            f"ÖLÇ.YAPILIYOR : Maksimum RPM, Güç Kaybı Analizi",
            f"GEÇİŞ NEDENİ  : {Dashboard.YELLOW}{neden}{Style.RESET_ALL}"
        ]
        Dashboard.print_box(lines, Dashboard.MAGENTA)
    
    @staticmethod
    def show_progress_bar(kalan_sure, current_phase, rpm, ect, total_trim, power_str="", max_rpm=7000, tps=None, yakit_tipi="GASOLINE", frp=None):
        """
        Anlık veri satırı - Renkli RPM barı ile
        UYARI: Bu satır \r ile sürekli güncellenir
        max_rpm: Araç tipine göre dinamik max RPM (Dizel: 5000, Benzin: 7000)
        tps: LOAD fazında gösterilecek gaz kelebeği %'si
        """
        # RPM bar - Dinamik max_rpm kullanımı
        rpm_blocks = min(20, int(rpm / (max_rpm / 20)))
        rpm_color = Dashboard.rpm_color(rpm, max_rpm=max_rpm)
        rpm_bar = f"{rpm_color}{'▓' * rpm_blocks}{'░' * (20 - rpm_blocks)}{Style.RESET_ALL}"
        
        # ECT string
        ect_str = f"ECT: {ect}°C" if ect is not None else "ECT: ---"
        
        # Dizel için FRP, benzinli için TRIM göster
        if yakit_tipi == "DIESEL":
            label = "FRP"
            value_str = f"{int(frp) if frp is not None else '---'} kPa"
            value_color = Dashboard.WHITE # FRP için nötr renk
        else:
            label = "TRIM"
            value_str = f"{total_trim:+.1f}%"
            if abs(total_trim) < 10:
                value_color = Dashboard.GREEN
            elif abs(total_trim) < 15:
                value_color = Dashboard.YELLOW
            else:
                value_color = Dashboard.RED
        
        # Phase renklendirme
        phase_colors = {
            "KOEO": Dashboard.BLUE,
            "CRANKING": Dashboard.YELLOW,
            "WARMUP": Dashboard.CYAN,
            "HOT": Dashboard.GREEN,
            "LOAD": Dashboard.MAGENTA,
        }
        phase_color = phase_colors.get(current_phase, Dashboard.WHITE)
        
        # TPS (Throttle Position) for LOAD phase
        tps_str = ""
        if current_phase == "LOAD" and tps is not None:
            tps_color = Dashboard.GREEN if tps > 80 else Dashboard.YELLOW
            tps_str = f"| TPS: {tps_color}%{tps:.0f}{Style.RESET_ALL} "
        
        # Progress line
        print(f"⏳ {kalan_sure:4d}sn | {phase_color}{current_phase:8}{Style.RESET_ALL} | "
              f"{rpm:4d} RPM [{rpm_bar}] {tps_str}| {ect_str} | {label}: {value_color}{value_str}{Style.RESET_ALL} {power_str}    ", 
              end="\r")
    
    @staticmethod
    def show_results_table(detayli_karne):
        """Sonuç tablosunu renkli göster"""
        print("\n" + Dashboard.CYAN + "═" * 95 + Style.RESET_ALL)
        print(f"{Dashboard.CYAN}{'PARÇA':<20} | {'ÖLÇÜLEN':<15} | {'REFERANS':<15} | {'DURUM'}{Style.RESET_ALL}")
        print(Dashboard.CYAN + "═" * 95 + Style.RESET_ALL)
        
        for k, v in detayli_karne.items():
            # Durum renklendir
            durum = v['Durum']
            if durum in ["IYI", "NORMAL", "SAGLAM", "MUKEMMEL", "TEMIZ", "CANLI", "STABIL"]:
                durum_color = Dashboard.GREEN
            elif durum in ["KABUL EDILEBILIR", "BILGI", "GAZ VERILDI", "Hafif Dalgalı"]:
                durum_color = Dashboard.YELLOW
            elif durum == "DESTEKLENMIYOR":
                durum_color = Fore.WHITE
            else:
                durum_color = Dashboard.RED
            
            print(f"{v['Parca']:<20} | {v['Olculen']:<15} | {v['Referans']:<15} | {durum_color}{durum}{Style.RESET_ALL}")
        
        print(Dashboard.CYAN + "═" * 95 + Style.RESET_ALL)
    
    @staticmethod
    def show_score_summary(skor):
        """V76: General score summary with verbal grade"""
        print("\n")
        Dashboard.print_header("GENEL KARNE ÖZETİ", Dashboard.CYAN)
        
        # Verbal grade determination
        if skor >= 85:
            derece = "MÜKEMMEL (Sorunsuz)"
            renk = Dashboard.GREEN
        elif skor >= 70:
            derece = "İYİ (Ufak Bakım Gerekebilir)"
            renk = Dashboard.BLUE
        elif skor >= 50:
            derece = "ORTA / TAKİP EDİLMELİ"
            renk = Dashboard.YELLOW
        else:
            derece = "KRİTİK / RİSKLİ"
            renk = Dashboard.RED
        
        print(f"\n{renk}╔{'═' * 50}╗{Style.RESET_ALL}")
        print(f"{renk}║{' ' * 15}{derece:^20}{' ' * 15}║{Style.RESET_ALL}")
        print(f"{renk}║{' ' * 18}PUAN: {skor}/100{' ' * 18}║{Style.RESET_ALL}")
        print(f"{renk}╚{'═' * 50}╝{Style.RESET_ALL}")
        print()
    
    @staticmethod
    def show_phase_analysis(asamali_rapor):
        """Aşamalı sürüş analizini renkli göster"""
        print("\n" + Dashboard.CYAN + "═" * 60 + Style.RESET_ALL)
        print(f"{Dashboard.CYAN}📊 AŞAMALI SÜRÜŞ ANALİZİ{Style.RESET_ALL}")
        print(Dashboard.CYAN + "═" * 60 + Style.RESET_ALL)
        
        for phase, metrics in asamali_rapor.items():
            # Phase color
            phase_colors = {
                "KOEO": Dashboard.BLUE,
                "CRANKING": Dashboard.YELLOW,
                "WARMUP": Dashboard.CYAN,
                "HOT": Dashboard.GREEN,
                "LOAD": Dashboard.MAGENTA,
            }
            phase_color = phase_colors.get(phase, Dashboard.WHITE)
            
            sure_str = f"{metrics.get('Sure', 0):.1f}sn"
            durum = metrics.get('Durum', '---')
            
            # Durum renklendirme
            if durum in ["İyi", "Normal", "Sağlam", "Stabil"]:
                durum_color = Dashboard.GREEN
            elif durum in ["Kabul Edilebilir", "Hafif Dalgalı"]:
                durum_color = Dashboard.YELLOW
            else:
                durum_color = Dashboard.RED
            
            print(f"{phase_color}{phase:10}{Style.RESET_ALL} | Süre: {sure_str:8} | Durum: {durum_color}{durum}{Style.RESET_ALL}")
            
            # Ek metrikler
            if phase == "KOEO" and "BaslangicVoltaj" in metrics:
                print(f"           └─ Başlangıç Voltajı: {Dashboard.WHITE}{metrics['BaslangicVoltaj']:.1f}V{Style.RESET_ALL}")
            elif phase == "CRANKING" and "MinVoltaj" in metrics:
                print(f"           └─ Minimum Voltaj: {Dashboard.WHITE}{metrics['MinVoltaj']:.1f}V{Style.RESET_ALL}")
            elif phase == "WARMUP" and "IsinmaHizi" in metrics:
                print(f"           └─ Isınma Hızı: {Dashboard.WHITE}{metrics['IsinmaHizi']}{Style.RESET_ALL}")
            elif phase == "HOT" and "RolantiStd" in metrics:
                print(f"           └─ Rölanti Sapma: {Dashboard.WHITE}{metrics['RolantiStd']} RPM{Style.RESET_ALL}")
            elif phase == "LOAD" and "GucKaybi" in metrics:
                print(f"           └─ Max RPM: {Dashboard.WHITE}{metrics['MaxRPM']}{Style.RESET_ALL}")
                print(f"           └─ Tahmini Güç Kaybı: {Dashboard.WHITE}{metrics['GucKaybi']}{Style.RESET_ALL}")
        
        print(Dashboard.CYAN + "═" * 60 + Style.RESET_ALL)
