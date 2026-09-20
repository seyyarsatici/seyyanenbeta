import csv
import json
import os

def generate():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    target_dir = os.path.join(out_dir, "canonical_session")
    os.makedirs(target_dir, exist_ok=True)

    start_ts = 1726842720124000
    rows = []
    header = [
        "timestamp_us", "sequence", "frame_id", "pid", "name",
        "request", "raw_response", "decoded_value", "unit",
        "status", "quality", "freshness", "latency_us"
    ]

    pids_cycle = [
        ('010C', 'RPM', 'rpm', 150),
        ('010B', 'MAP', 'kPa', 150),
        ('0111', 'TPS', '%', 150),
        ('0104', 'LOAD', '%', 500),
        ('010D', 'SPEED', 'km/h', 500),
        ('0105', 'ECT', 'degC', 2000),
    ]

    current_ts = start_ts
    seq = 1
    frame_id = 1
    sample_count = 82

    for i in range(sample_count):
        elapsed_s = (current_ts - start_ts) / 1000000.0
        if 5.0 <= elapsed_s <= 8.5:
            # Stationary throttle blip from idle ~780 rpm to ~1620 rpm and back
            rpm_val = 780.0 + (1620.0 - 780.0) * (1.0 - abs(elapsed_s - 6.75) / 1.75)
            map_val = 34.0 + (54.0 - 34.0) * (1.0 - abs(elapsed_s - 6.75) / 1.75)
            tps_val = 12.5 + (18.4 - 12.5) * (1.0 - abs(elapsed_s - 6.75) / 1.75)
            load_val = 22.0 + (42.0 - 22.0) * (1.0 - abs(elapsed_s - 6.75) / 1.75)
        else:
            rpm_val = 780.0 + (i % 3) * 4.0 - 4.0
            map_val = 34.0 + (i % 2) * 1.0
            tps_val = 12.55
            load_val = 21.57

        pid_spec = pids_cycle[i % len(pids_cycle)]
        pid_code, pid_name, pid_unit, _ = pid_spec
        latency = 22000 + (i % 5) * 1500

        status = 'VALID'
        quality = 'GOOD'
        freshness = 'FRESH'
        decoded_str = ''
        raw_resp = ''

        # Sequence 45: simulate 1 intermittent NO_DATA on a PID to test zero-resistance
        if seq == 45:
            status = 'NO_DATA'
            quality = 'NO_DATA'
            freshness = 'STALE'
            raw_resp = 'NO DATA'
            decoded_str = ''
        elif pid_code == '010C':
            raw_a = int(rpm_val * 4) // 256
            raw_b = int(rpm_val * 4) % 256
            raw_resp = f'41 0C {raw_a:02X} {raw_b:02X}'
            decoded_str = f'{((raw_a * 256 + raw_b) / 4.0):.2f}'
        elif pid_code == '010B':
            raw_a = int(map_val)
            raw_resp = f'41 0B {raw_a:02X}'
            decoded_str = f'{raw_a:.2f}'
        elif pid_code == '0111':
            raw_a = int(tps_val * 255 / 100)
            raw_resp = f'41 11 {raw_a:02X}'
            decoded_str = f'{(raw_a * 100.0 / 255.0):.2f}'
        elif pid_code == '0104':
            raw_a = int(load_val * 255 / 100)
            raw_resp = f'41 04 {raw_a:02X}'
            decoded_str = f'{(raw_a * 100.0 / 255.0):.2f}'
        elif pid_code == '010D':
            raw_resp = '41 0D 00'
            decoded_str = '0.00'
        elif pid_code == '0105':
            raw_a = 87 + 40
            raw_resp = f'41 05 {raw_a:02X}'
            decoded_str = f'{(raw_a - 40):.2f}'

        rows.append([
            str(current_ts), str(seq), str(frame_id), pid_code, pid_name,
            pid_code, raw_resp, decoded_str, pid_unit, status, quality, freshness, str(latency)
        ])

        seq += 1
        if (i + 1) % len(pids_cycle) == 0:
            frame_id += 1
        current_ts += int(192000 + (i % 4) * 5000)

    csv_file = os.path.join(target_dir, "session.csv")
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    events_file = os.path.join(target_dir, "events.log")
    with open(events_file, 'w', encoding='utf-8') as f:
        f.write("2026-09-20T14:32:00.124Z [SESSION_START] Session MINI-AVEO-F14D3-001 started on Chevrolet Aveo F14D3\n")
        f.write("2026-09-20T14:32:00.220Z [ADAPTER_INFO] vLinker MC+ v2.2 (ISO 15765-4 CAN 11/500)\n")
        f.write("2026-09-20T14:32:00.310Z [ACQUISITION_RUNNING] Polling 6 active PIDs at idle\n")
        f.write("2026-09-20T14:32:06.820Z [THROTTLE_BLIP] Controlled stationary RPM increase (780 -> 1620 rpm)\n")
        f.write("2026-09-20T14:32:15.892Z [SESSION_STOP] Session finalized cleanly. Written samples: 82\n")

    print(f"Generated canonical session in {target_dir}")

if __name__ == "__main__":
    generate()
