import os
import json
import csv

class DBManager:
    def __init__(self, base_path):
        self.base_path = base_path
        self.data = {}

    def load_all(self):
        """Dynamically load all CSV and JSON files from dbCSV."""
        for root, _, files in os.walk(self.base_path):
            for file in files:
                if file.endswith('.csv'):
                    self._load_csv(os.path.join(root, file))
                elif file.endswith('.json'):
                    self._load_json(os.path.join(root, file))

    def _load_csv(self, file_path):
        """Load a CSV file and store its content."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                reader = csv.DictReader(f)
                self.data[os.path.basename(file_path)] = list(reader)
        except Exception as e:
            print(f"Error loading CSV {file_path}: {e}")

    def _load_json(self, file_path):
        """Load a JSON file and store its content."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.data[os.path.basename(file_path)] = json.load(f)
        except Exception as e:
            print(f"Error loading JSON {file_path}: {e}")

    def parse_mode01(self, json_file):
        """Parse SAE_J1979_Mode01.json for bit masking, scale, and offset."""
        try:
            mode01_data = self.data.get(json_file)
            if not mode01_data:
                raise ValueError(f"JSON file {json_file} not loaded.")

            parsed_data = {}
            for pid, details in mode01_data.items():
                scale = details.get('scale', 1)
                offset = details.get('offset', 0)
                bitmask = details.get('bitmask', 0xFF)
                parsed_data[pid] = {
                    'scale': scale,
                    'offset': offset,
                    'bitmask': bitmask
                }
            return parsed_data
        except Exception as e:
            print(f"Error parsing Mode01 JSON {json_file}: {e}")
            return {}

# Example usage
if __name__ == "__main__":
    db_manager = DBManager("dbCSV")
    db_manager.load_all()
    mode01_data = db_manager.parse_mode01("SAE_J1979_Mode01.json")
    print(mode01_data)