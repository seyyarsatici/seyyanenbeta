import time
import logging

class ActiveTestController:
    """
    UDS (ISO 14229-1) Compliant Active Test Controller
    Handles diagnostic sessions and security access with proper error checking.
    """
    def __init__(self, send_function):
        self.send_function = send_function
        self.security_level = 0
        self.logger = logging.getLogger(__name__)

    def start_extended_session(self):
        """
        Start extended diagnostic session (UDS Service 10 - DiagnosticSessionControl).
        Command: 10 03 (Extended Diagnostic Session)
        Expected Response: 50 03 [data] (positive) or 7F 10 XX (negative)
        Returns: True if successful, False otherwise
        """
        try:
            # Send Extended Session command
            response = self.send_function("10 03")
            time.sleep(0.1)  # Allow ECU to stabilize

            if not response or len(response) == 0:
                self.logger.error("No response from ECU for session start")
                print("❌ ECU sessiyonu başlatmıyor (yanıt yok)")
                return False

            response_str = "".join(response).replace(" ", "").upper()

            # Check for negative response (7F = Negative Response)
            if "7F" in response_str:
                # Extract NRC (Negative Response Code)
                if len(response_str) >= 6:
                    service_id = response_str[2:4]
                    nrc = response_str[4:6]
                    self.logger.warning(f"Negative Response: Service 0x{service_id}, NRC 0x{nrc}")
                    print(f"❌ ECU Hata Verdi: NRC 0x{nrc}")
                return False

            # Check for positive response (50 = Positive response to 0x10)
            if response_str.startswith("5003"):
                self.logger.info("Extended Session started successfully")
                print("✅ Extended Session Başlatıldı")
                return True
            else:
                self.logger.error(f"Unexpected response: {response_str[:20]}")
                print(f"❌ Beklenmeyen cevap: {response_str[:20]}")
                return False

        except Exception as e:
            self.logger.exception(f"Error starting extended session: {e}")
            print(f"❌ Session Hatası: {e}")
            return False

    def security_access(self):
        """
        Perform UDS Security Access (Service 27 - SecurityAccess).
        Phase 1: Request seed (27 01)
        Phase 2: Send key (27 02)
        Returns: True if security access granted, False otherwise
        """
        try:
            # Phase 1: Request seed
            self.logger.info("Requesting security seed...")
            seed_response = self.send_function("27 01")
            time.sleep(0.1)

            if not seed_response or len(seed_response) == 0:
                self.logger.error("No response from ECU for seed request")
                print("❌ ECU seed sorgusu yanıtlamıyor")
                return False

            seed_str = "".join(seed_response).replace(" ", "").upper()

            # Check for negative response
            if "7F" in seed_str:
                if len(seed_str) >= 6:
                    service_id = seed_str[2:4]
                    nrc = seed_str[4:6]
                    self.logger.warning(f"Seed Request Failed: Service 0x{service_id}, NRC 0x{nrc}")
                    print(f"❌ Seed İsteği Başarısız: NRC 0x{nrc}")
                return False

            # Extract seed from positive response (67 01 [seed bytes])
            if seed_str.startswith("6701"):
                seed_hex = seed_str[4:]  # Remove "6701" prefix
                if len(seed_hex) < 2:
                    self.logger.error("Seed too short")
                    print("❌ Seed çok kısa")
                    return False

                self.logger.info(f"Seed received: {seed_hex}")
                print(f"✅ Seed Alındı: 0x{seed_hex}")

                # Phase 2: Calculate key from seed and send
                key_hex = self._calculate_key_from_seed(seed_hex)
                if not key_hex:
                    print("❌ Key hesaplanamadı")
                    return False

                # Send key to ECU
                time.sleep(0.1)
                key_command = f"27 02 {' '.join([key_hex[i:i+2] for i in range(0, len(key_hex), 2)])}"
                self.logger.info(f"Sending security key: {key_command}")
                
                key_response = self.send_function(key_command)
                time.sleep(0.1)

                if not key_response or len(key_response) == 0:
                    self.logger.error("No response from ECU for key submission")
                    print("❌ ECU key yanıtlamıyor")
                    return False

                key_resp_str = "".join(key_response).replace(" ", "").upper()

                # Check for negative response
                if "7F" in key_resp_str:
                    if len(key_resp_str) >= 6:
                        service_id = key_resp_str[2:4]
                        nrc = key_resp_str[4:6]
                        self.logger.warning(f"Key Submission Failed: Service 0x{service_id}, NRC 0x{nrc}")
                        print(f"❌ Key Gönderimi Başarısız: NRC 0x{nrc}")
                    return False

                # Check for positive response (67 02)
                if key_resp_str.startswith("6702"):
                    self.security_level = 1
                    self.logger.info("Security access granted")
                    print("✅ Güvenlik Erişimi Sağlandı")
                    return True
                else:
                    self.logger.error(f"Unexpected key response: {key_resp_str[:20]}")
                    print(f"❌ Beklenmeyen key yanıtı: {key_resp_str[:20]}")
                    return False
            else:
                self.logger.error(f"Unexpected seed response: {seed_str[:20]}")
                print(f"❌ Beklenmeyen seed yanıtı: {seed_str[:20]}")
                return False

        except Exception as e:
            self.logger.exception(f"Error during security access: {e}")
            print(f"❌ Güvenlik Hatası: {e}")
            return False

    def _calculate_key_from_seed(self, seed_hex):
        """
        DUMMY Security Algorithm (Placeholder).
        In production, this should implement the actual OEM security algorithm.
        
        Dummy Algorithm: Simple XOR with fixed key + bit rotation
        Real implementations vary by OEM (Bosch, Siemens, Delphi, etc.)
        """
        try:
            if len(seed_hex) < 2:
                return None

            # Convert hex string to bytes
            seed_bytes = bytes.fromhex(seed_hex)

            # Dummy algorithm: XOR with fixed key + rotate left by 3
            fixed_key = b'\xA5'  # Arbitrary magic number
            result_bytes = bytearray()

            for byte in seed_bytes:
                # Step 1: XOR with fixed key
                xored = byte ^ fixed_key[0]
                
                # Step 2: Rotate left by 3 bits
                rotated = ((xored << 3) | (xored >> 5)) & 0xFF
                
                # Step 3: Invert lower nibble
                inverted = (rotated ^ 0x0F)
                
                result_bytes.append(inverted)

            key_hex = result_bytes.hex().upper()
            self.logger.info(f"Dummy security key calculated: {key_hex}")
            return key_hex

        except Exception as e:
            self.logger.exception(f"Error calculating security key: {e}")
            print(f"❌ Key Hesaplama Hatası: {e}")
            return None

    def send_active_test(self, command):
        """
        Send an active test command (Routine Control / InputOutput).
        Typically used for actuator tests (fan, pump, relay, etc.)
        
        Args:
            command: Command string (e.g., "31 01 01" for Routine Control)
        Returns: Response from vehicle
        """
        if self.security_level < 1:
            self.logger.warning("Security access not granted, cannot send active test")
            print("❌ Güvenlik erişimi yok, test yapılamaz")
            return None

        try:
            self.logger.info(f"Sending active test: {command}")
            response = self.send_function(command)
            
            if response:
                response_str = "".join(response).replace(" ", "").upper()
                
                # Check for negative response
                if "7F" in response_str:
                    self.logger.warning(f"Active test failed: {response_str}")
                    print(f"❌ Test Başarısız: {response_str}")
                    return None
                
                self.logger.info(f"Active test response: {response_str}")
                print(f"✅ Test Yanıtı: {response_str}")
            
            return response

        except Exception as e:
            self.logger.exception(f"Error sending active test: {e}")
            print(f"❌ Test Gönderme Hatası: {e}")
            return None

    def end_session(self):
        """
        End diagnostic session and return to default (UDS Service 10 - DiagnosticSessionControl).
        Command: 10 01 (Default Diagnostic Session)
        Expected Response: 50 01 (positive) or 7F 10 XX (negative)
        Returns: True if successful, False otherwise
        """
        try:
            self.logger.info("Ending diagnostic session")
            response = self.send_function("10 01")
            time.sleep(0.1)

            if not response or len(response) == 0:
                self.logger.error("No response from ECU for session end")
                print("❌ ECU session sonu yanıtlamıyor")
                return False

            response_str = "".join(response).replace(" ", "").upper()

            # Check for negative response
            if "7F" in response_str:
                self.logger.warning(f"Session end failed: {response_str}")
                print(f"❌ Session Sonu Başarısız: {response_str}")
                return False

            # Check for positive response (50 = Positive response to 0x10)
            if response_str.startswith("5001"):
                self.security_level = 0
                self.logger.info("Session ended successfully")
                print("✅ Session Sona Erdirildi")
                return True
            else:
                self.logger.error(f"Unexpected session end response: {response_str[:20]}")
                print(f"❌ Session sonu cevabı: {response_str[:20]}")
                return False

        except Exception as e:
            self.logger.exception(f"Error ending session: {e}")
            print(f"❌ Session Sonu Hatası: {e}")
            return False


# Example usage
if __name__ == "__main__":
    def mock_send(command):
        """Mock function for testing"""
        print(f"[Mock] Sending: {command}")
        
        # Simulate responses
        if "10 03" in command:
            return ["50 03 00 32 01 F4"]  # Extended session positive response
        elif "27 01" in command:
            return ["67 01 12 34 56 78"]  # Seed request positive response
        elif "27 02" in command:
            return ["67 02"]  # Key submission positive response
        elif "10 01" in command:
            return ["50 01"]  # Default session positive response
        else:
            return ["7F 10 31"]  # Generic negative response

    # Test the controller
    controller = ActiveTestController(mock_send)
    
    print("\n=== Active Test Sequence ===\n")
    
    if controller.start_extended_session():
        if controller.security_access():
            controller.send_active_test("31 01 01")  # Example: Start routine
        controller.end_session()
    else:
        print("❌ Session başlatılamadı, işlem iptal edildi")