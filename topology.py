import time

class TopologyScanner:
    def __init__(self, send_function):
        self.send_function = send_function

    def scan_network(self):
        """Scan the network for active ECUs."""
        try:
            # Set functional broadcast address
            self.send_function("AT SH 7DF")

            # Send PID request
            responses = self.send_function("0100")
            time.sleep(0.1)  # Allow ECUs to respond

            ecus = []
            for response in responses:
                if response.startswith("7E8") or response.startswith("7E9"):
                    ecus.append(response[:3])

            return list(set(ecus))
        except Exception as e:
            print(f"Network Scan Error: {e}")
            return []

    def fingerprint_ecu(self, ecu_address):
        """Identify ECU by querying VIN and SW version."""
        try:
            # Lock onto target ECU
            self.send_function(f"AT SH {ecu_address}")

            # Query VIN and SW version
            vin_response = self.send_function("22 F1 90")
            sw_response = self.send_function("22 F1 87")

            # Restore functional broadcast
            self.send_function("AT SH 7DF")

            return {
                "VIN": vin_response,
                "SW_Version": sw_response
            }
        except Exception as e:
            print(f"ECU Fingerprint Error: {e}")
            return {}

# Example usage
if __name__ == "__main__":
    def mock_send(command, broadcast=False):
        print(f"Sending: {command} (Broadcast: {broadcast})")

    def mock_receive():
        return ["7E8 10 14", "7E9 10 14"]

    scanner = TopologyScanner(mock_send)
    ecus = scanner.scan_network()
    print("Detected ECUs:", ecus)

    for ecu in ecus:
        fingerprint = scanner.fingerprint_ecu(ecu)
        print(f"ECU {ecu} Fingerprint:", fingerprint)