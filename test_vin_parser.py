#!/usr/bin/env python3
"""
Test script: Mode 09 (VIN) Multi-Frame Parser
Opel Insignia arabasından VIN numarası çekmesi simulate'i test et
"""

import re
import sys
sys.path.insert(0, '.')

def log_flush(msg):
    print(f"[LOG] {msg}")

# Mock _multiframe_birlestir ve _hex_to_ascii_cleaned fonksiyonları
def _hex_to_ascii_cleaned(hex_str, verbose=False):
    """
    V138: Hex dizesini ASCII'ye dönüştürür ve protokol byte'larını temizler.
    """
    try:
        # Çift sayıda hex char olmasını sağla
        if len(hex_str) % 2 != 0:
            hex_str = hex_str[:-1]
        
        if verbose:
            print(f"  [DEBUG] Hex (original): {hex_str[:40]}")
        
        # Basit protokol header temizliği (49 02 / 41 vs.)
        # Mode 09 (VIN): 49 02 XX ... → XX ...
        if hex_str.startswith('4902'):
            hex_str = hex_str[4:]  # 49 02 çıkar
            if verbose:
                print(f"  [DEBUG] 49 02 çıkarıldı: {hex_str[:40]}")
        
        # Mode 01 (Standard PID): 41 ... → ...
        elif hex_str.startswith('41'):
            hex_str = hex_str[2:]  # 41 çıkar (optiyonel)
        
        # ISO-TP PCI Stripping
        if hex_str.startswith('10'):
            hex_str = hex_str[4:]
            if verbose:
                print(f"  [DEBUG] First Frame PCI çıkarıldı: {hex_str[:40]}")
        
        elif hex_str.startswith('2'):
            hex_str = hex_str[2:]
            if verbose:
                print(f"  [DEBUG] Consecutive Frame PCI çıkarıldı: {hex_str[:40]}")
        
        # ASCII'ye dönüştür (hata karakterleri yok say)
        ascii_metin = bytes.fromhex(hex_str).decode('ascii', errors='ignore')
        if verbose:
            print(f"  [DEBUG] ASCII sonuç: {ascii_metin}")
        return ascii_metin, hex_str
    except Exception as e:
        log_flush(f"[HEX_ASCII_ERROR] Dönüştürme hatası: {e}")
        return "", hex_str


def _multiframe_birlestir(satirlar, verbose=False):
    """
    V138: ISO-TP Multi-Frame Birleştirici (Mode 09, 01 dahil).
    """
    frame_satirlar = {}
    diger_satirlar = []
    can_header_re = re.compile(r'^(7E[0-9A-Fa-f])')

    for satir in satirlar:
        temiz = satir.strip().replace(' ', '')
        
        # CAN header'ı temizle
        temiz = can_header_re.sub('', temiz)

        # Format 1: ELM327'nin multiframe formatı ("0: AABB...", "1: AABB...", vb.)
        eslesme = re.match(r'^([0-9A-Fa-f]+):([0-9A-Fa-f]+)$', temiz)
        if eslesme:
            try:
                indeks = int(eslesme.group(1), 16)
                payload = eslesme.group(2)
                frame_satirlar[indeks] = payload
                if verbose:
                    print(f"    [DEBUG] Frame {indeks}: {payload}")
                continue
            except ValueError:
                pass
        
        # Format 2: Doğrudan ISO-TP formatı
        if re.match(r'^(10|2[0-9A-Fa-f]|49|41)[0-9A-Fa-f]+', temiz):
            if temiz.startswith('10'):  # First Frame
                frame_satirlar[0] = temiz
                if verbose:
                    print(f"    [DEBUG] First Frame (index 0): {temiz[:20]}")
            elif temiz.startswith('2'):  # Consecutive Frame
                try:
                    pci_byte = int(temiz[0:2], 16)
                    indeks = pci_byte & 0x0F
                    frame_satirlar[indeks] = temiz
                    if verbose:
                        print(f"    [DEBUG] Consecutive Frame (index {indeks}): {temiz[:20]}")
                except ValueError:
                    diger_satirlar.append(temiz)
            else:  # Mode response
                diger_satirlar.append(temiz)
                if verbose:
                    print(f"    [DEBUG] Mode response: {temiz}")
        elif temiz:
            diger_satirlar.append(temiz)
    
    if not frame_satirlar:
        result = ''.join(diger_satirlar).upper()
        if verbose:
            print(f"  [DEBUG] No frames, combining other: {result[:40]}")
        return result

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
                        full_payload.append(payload[4:])
                        if verbose:
                            print(f"  [DEBUG] First Frame: length={length}, data={payload[4:20]}")
                    else:
                        full_payload.append(payload)
                else:
                    full_payload.append(payload)
            
            # Consecutive Frame (PCI: 2N)
            elif i > 0 and payload.startswith('2'):
                if len(payload) >= 2:
                    full_payload.append(payload[2:])
                    if verbose:
                        print(f"  [DEBUG] Consecutive {i}: {payload[2:20]}")
                else:
                    full_payload.append(payload)
            else:
                # Normal veri
                full_payload.append(payload)
                if verbose:
                    print(f"  [DEBUG] Normal data (index {i}): {payload[:20]}")
        except (ValueError, IndexError) as e:
            log_flush(f"[ISOTP_ERROR] Çerçeve işlenemedi (index {i}): {payload}")
            full_payload.append(payload)

    birlesmis = "".join(full_payload)

    if data_len > 0:
        result = birlesmis[:data_len * 2].upper()
    else:
        result = birlesmis.upper()
    
    if verbose:
        print(f"  [DEBUG] Birleştirilmiş sonuç: {result}")
    return result


def test_vin_parsing():
    """Test Case: Opel Insignia VIN çekme"""
    print("\n" + "="*70)
    print("TEST 1: Opel Insignia VIN (Mode 09 0902) - Multi-Frame Yanıt")
    print("="*70)
    
    # Mock ELM327 yanıtı (multi-frame)
    # VIN: W0LAAAAAAAAAAAAA (17 hane - Opel)
    # Hex: 57 30 4C 41 41 41 41 41 41 41 41 41 41 41 41 41 41
    # (W=57, 0=30, L=4C, A=41 × 14)
    # Mode 09 format: 49 02 <17 byte VIN>
    
    # ISO-TP ile 17 byte veri birden fazla frame'de gelir:
    # Frame 0: 10 11 57 30 4C 41 41 41 (PCI=10, Length=0x11=17, first 6 bytes)
    # Frame 1: 21 41 41 41 41 41 41 41 41 (PCI=21, consecutive 8 bytes)
    # Frame 2: 22 41 (PCI=22, last 3 bytes)
    
    mock_response = [
        "0: 10 11 57 30 4C 41 41 41",      # First frame: W0LAAA
        "1: 21 41 41 41 41 41 41 41 41",   # Consecutive 1: AAAAAAAA
        "2: 22 41 41 41"                    # Consecutive 2: AAA
    ]
    
    print(f"\nMock Response (ISO-TP ELM327 format):")
    for i, line in enumerate(mock_response):
        print(f"  Line {i}: {line}")
    
    # Step 1: Multi-frame birleştir
    print(f"\nStep 1: Multi-frame birleştirme...")
    hex_str = _multiframe_birlestir(mock_response, verbose=True)
    print(f"Result: {hex_str}")
    
    # Step 2: Hex'i ASCII'ye dönüştür
    print(f"\nStep 2: Hex → ASCII dönüştürme...")
    ascii_metin, clean_hex = _hex_to_ascii_cleaned(hex_str, verbose=True)
    print(f"ASCII: '{ascii_metin}'")
    print(f"ASCII Length: {len(ascii_metin)}")
    
    # Step 3: VIN Regex
    print(f"\nStep 3: VIN Regex Matching...")
    vin_patterns = [
        r'(W0L|WVW|WF0|ZFA|VF1|VF3|KL|KM|JT|JM)[A-HJ-NPR-Z0-9]{14}',
        r'(WF|JT|JM|KL|KM|VF|ZF)[A-HJ-NPR-Z0-9]{15}',
        r'[A-HJ-NPR-Z0-9]{17}'
    ]
    
    eslesme = None
    for i, pattern in enumerate(vin_patterns):
        print(f"  Pattern {i+1}: {pattern}")
        test_match = re.search(pattern, ascii_metin)
        if test_match:
            eslesme = test_match
            print(f"    ✅ MATCH: {eslesme.group(0)}")
            break
        else:
            print(f"    ❌ nomatch")
    
    if eslesme:
        vin = eslesme.group(0)
        print(f"\n✅ VIN BAŞARIYLA ÇEKİLDİ: {vin}")
        return True
    else:
        print(f"\n❌ VIN ÇEKİLEMEDİ")
        return False


def test_vin_parsing_iso_tp():
    """Test Case: Real ISO-TP format (First Frame + Consecutive Frames)"""
    print("\n" + "="*70)
    print("TEST 2: ISO-TP Format (First + Consecutive Frames)")
    print("="*70)
    
    # More realistic ISO-TP response
    # VIN: W0LAAAAAAAAAAAAA (17 byte)
    # Hex: 57 30 4C 41 41 41 41 41 41 41 41 41 41 41 41 41 41
    # 17 bytes split:
    # Frame 0 (First): 10 11 57 30 4C 41 41 41 (PCI=10, Length=17, data=6 bytes)
    # Frame 1 (Conse): 21 41 41 41 41 41 41 41 41 (PCI=21, data=8 bytes, total=14)
    # Frame 2 (Conse): 22 41 41 41 (PCI=22, data=3 bytes, total=17)
    
    mock_response_isotp = [
        "0: 10 11 57 30 4C 41 41 41",  # Frame 0: First, length=17, W0LAAA
        "1: 21 41 41 41 41 41 41 41 41",  # Frame 1: Consecutive, AAAAAAAA  
        "2: 22 41 41 41"                    # Frame 2: Consecutive, AAA
    ]
    
    print(f"\nMock Response (ISO-TP format with correct 17-byte VIN):")
    for i, line in enumerate(mock_response_isotp):
        print(f"  Line {i}: {line}")
    
    # Step 1: Multi-frame birleştir
    print(f"\nStep 1: Multi-frame birleştirme...")
    hex_str = _multiframe_birlestir(mock_response_isotp, verbose=True)
    print(f"Result: {hex_str}")
    print(f"Result length: {len(hex_str)} chars (should be 34 for 17 hex bytes)")
    
    # Step 2: Hex'i ASCII'ye dönüştür
    print(f"\nStep 2: Hex → ASCII dönüştürme...")
    ascii_metin, clean_hex = _hex_to_ascii_cleaned(hex_str, verbose=True)
    print(f"ASCII: '{ascii_metin}'")
    print(f"ASCII length: {len(ascii_metin)}")
    
    # Step 3: VIN Regex
    print(f"\nStep 3: VIN Regex Matching...")
    vin_patterns = [
        r'(W0L|WVW|WF0|ZFA|VF1|VF3|KL|KM|JT|JM)[A-HJ-NPR-Z0-9]{14}',
        r'(WF|JT|JM|KL|KM|VF|ZF)[A-HJ-NPR-Z0-9]{15}',
        r'[A-HJ-NPR-Z0-9]{17}'
    ]
    
    eslesme = None
    for i, pattern in enumerate(vin_patterns):
        print(f"  Pattern {i+1}: {pattern}")
        test_match = re.search(pattern, ascii_metin)
        if test_match:
            eslesme = test_match
            print(f"    ✅ MATCH: {eslesme.group(0)}")
            break
        else:
            print(f"    ❌ nomatch")
    
    if eslesme:
        vin = eslesme.group(0)
        print(f"\n✅ VIN BAŞARIYLA ÇEKİLDİ: {vin}")
        return True
    else:
        print(f"\n❌ VIN ÇEKİLEMEDİ")
        return False


if __name__ == "__main__":
    print("\n🧪 VIN Parser Test Suite")
    print("="*70)
    
    result1 = test_vin_parsing()
    result2 = test_vin_parsing_iso_tp()
    
    print("\n" + "="*70)
    print("TEST ÖZET:")
    print(f"  Test 1 (Multi-frame): {'✅ PASSED' if result1 else '❌ FAILED'}")
    print(f"  Test 2 (ISO-TP): {'✅ PASSED' if result2 else '❌ FAILED'}")
    print("="*70 + "\n")
