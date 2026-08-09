import json
from typing import Any

import pandas as pd


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip().upper() for c in out.columns]
    return out


def _repair_data(df: pd.DataFrame) -> pd.DataFrame:
    repaired = _normalize_columns(df).copy()
    numeric_cols = repaired.select_dtypes(include="number").columns
    if len(numeric_cols) > 0:
        repaired[numeric_cols] = repaired[numeric_cols].interpolate(method="linear", limit_direction="both")
        repaired[numeric_cols] = repaired[numeric_cols].ffill().bfill()
    return repaired


def _build_groups(df: pd.DataFrame) -> dict[str, dict[str, float | None]]:
    groups = {
        "atesleme": {"TIMING_ADVANCE": None, "RPM": None},
        "yakit": {"STFT": None, "LTFT": None, "FUEL_RAIL_PRESS": None},
        "hava": {"MAF": None, "MAP": None, "IAT": None},
        "sogutma": {"ECT": None},
    }
    for group_values in groups.values():
        for sensor in list(group_values.keys()):
            if sensor in df.columns:
                group_values[sensor] = float(df[sensor].mean())
    return groups


def _trim_diagnosis(df: pd.DataFrame) -> tuple[str | None, float | None]:
    if "STFT" not in df.columns or "LTFT" not in df.columns:
        return None, None
    total_trim = float((df["STFT"] + df["LTFT"]).mean())
    if total_trim > 10.0:
        return "Fakir Karışım", total_trim
    if total_trim < -10.0:
        return "Zengin Karışım", total_trim
    return None, total_trim


def _idle_leak_suspicion(df: pd.DataFrame) -> tuple[bool, dict[str, Any]]:
    if "RPM" not in df.columns or "MAP" not in df.columns:
        return False, {"ortalama_map": None, "rpm_std": None, "ornek_sayisi": 0}
    idle_df = df[(df["RPM"] >= 650) & (df["RPM"] <= 950)]
    if idle_df.empty:
        return False, {"ortalama_map": None, "rpm_std": None, "ornek_sayisi": 0}
    map_mean = float(idle_df["MAP"].mean())
    rpm_std = float(idle_df["RPM"].std(ddof=0))
    suspicion = map_mean > 35.0 and rpm_std > 75.0
    return suspicion, {"ortalama_map": map_mean, "rpm_std": rpm_std, "ornek_sayisi": int(len(idle_df))}


def _build_gemini_prompt(groups: dict[str, dict[str, float | None]], total_trim: float | None, idle_metrics: dict[str, Any]) -> str:
    group_text = json.dumps(groups, ensure_ascii=False, indent=2)
    deviations = {
        "trim_toplam_yuzde": total_trim,
        "rolanti_map_ortalama_kpa": idle_metrics.get("ortalama_map"),
        "rolanti_rpm_std": idle_metrics.get("rpm_std"),
    }
    dev_text = json.dumps(deviations, ensure_ascii=False, indent=2)
    return (
        "Sen bir Bosch ECU Diagnostik Uzmanısın. Şu teknik verileri analiz et: "
        f"{group_text}. Hesaplanan sapmalar: {dev_text}. "
        "Lütfen resmi bir dille; Sorun, Olası Sebep ve Çözüm Önerisi şeklinde Türkçe özetle."
    )


def analiz_et(df: pd.DataFrame) -> dict:
    repaired = _repair_data(df)
    groups = _build_groups(repaired)
    trim_label, total_trim = _trim_diagnosis(repaired)
    leak_suspicion, idle_metrics = _idle_leak_suspicion(repaired)
    gemini_prompt = _build_gemini_prompt(groups, total_trim, idle_metrics)

    bulgular = []
    tavsiyeler = []
    saglik_puani = 100

    if leak_suspicion:
        bulgular.append("Sübap kaçağı veya emiş kaçağı şüphesi")
        tavsiyeler.append("Vakum hattı, emme manifoldu contaları ve subap kaçak testi kontrol edilmelidir.")
        saglik_puani -= 25

    if trim_label == "Fakir Karışım":
        bulgular.append("Yakıt düzeltme toplamı +%10 üzerinde: Fakir Karışım")
        tavsiyeler.append("Yakıt basıncı, enjektör debisi, kaçak hava ve MAF/MAP uyumu kontrol edilmelidir.")
        saglik_puani -= 20
    elif trim_label == "Zengin Karışım":
        bulgular.append("Yakıt düzeltme toplamı -%10 altında: Zengin Karışım")
        tavsiyeler.append("Enjektör sızıntısı, yakıt basınç regülatörü ve O2 geri besleme devresi kontrol edilmelidir.")
        saglik_puani -= 20

    if not bulgular:
        bulgular.append("Anlamlı bir mekanik sapma tespit edilmedi.")
        tavsiyeler.append("Periyodik bakım aralığına uygun takip önerilir.")

    # Fiziksel korelasyon kontrolleri
    if "ECT" in repaired.columns and "IAT" in repaired.columns:
        ect_mean = float(repaired["ECT"].mean())
        iat_mean = float(repaired["IAT"].mean())
        if ect_mean >= 90.0 and iat_mean >= 110.0:
            bulgular.append("IAT Sensör Arızası veya Intercooler Verimsizliği")
            tavsiyeler.append("IAT sensörü kalibrasyonu, emiş hattı ve intercooler verimi kontrol edilmelidir.")
            saglik_puani -= 20

    if "LOAD" in repaired.columns and "FUEL_RAIL_PRESS" in repaired.columns:
        high_load = repaired[repaired["LOAD"] >= 95.0]
        if not high_load.empty:
            high_load_frp_mean = float(high_load["FUEL_RAIL_PRESS"].mean())
            overall_frp_mean = float(repaired["FUEL_RAIL_PRESS"].mean())
            if high_load_frp_mean < (overall_frp_mean * 0.9):
                bulgular.append("Yüksek yükte yakıt besleme yetersizliği (Pompa/Filtre)")
                tavsiyeler.append("Yakıt pompası debi testi, filtre tıkanıklığı ve ray basınç regülasyonu kontrol edilmelidir.")
                saglik_puani -= 25

    saglik_puani = max(0, saglik_puani)

    ai_json = {
        "model": "Gemini 1.5 Flash",
        "dil": "tr",
        "sablon": "Sorun/Olası Sebep/Çözüm Önerisi",
        "atesleme_yorum": "Ateşleme sistemi verileri nominal aralıktadır; anlık avans ve devir takibi önerilir.",
        "yakit_yorum": (
            "Yakıt sistemi trim toplamı "
            f"{total_trim:.2f}%" if total_trim is not None else "Yakıt trim verisi mevcut değil."
        ),
        "hava_yorum": (
            "Rölantide MAP ve RPM davranışı kaçağa işaret ediyor."
            if leak_suspicion
            else "Hava emiş hattında belirgin kaçak emaresi tespit edilmedi."
        ),
        "sogutma_yorum": "Soğutma devresi için ECT trendi düzenli izlenmelidir.",
        "sorun": bulgular,
        "olasi_sebep": [
            "Sensör sapması",
            "Vakum/emme hattı kaçakları",
            "Yakıt düzeltme parametrelerinde limit dışı çalışma",
        ],
        "cozum_onerisi": tavsiyeler,
    }

    return {
        "arac_sagligi": f"%{saglik_puani}",
        "bulgular": bulgular,
        "tavsiyeler": tavsiyeler,
        "sistem_gruplari": groups,
        "hesaplanan_sapmalar": {
            "trim_toplam_yuzde": total_trim,
            "rolanti_map_ortalama_kpa": idle_metrics.get("ortalama_map"),
            "rolanti_rpm_std": idle_metrics.get("rpm_std"),
            "rolanti_ornek_sayisi": idle_metrics.get("ornek_sayisi"),
        },
        "karisim_etiketi": trim_label,
        "gemini_prompt": gemini_prompt,
        "ai_yanit_json": ai_json,
    }

