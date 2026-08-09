import serial
import time

ser = serial.Serial("COM3", 9600, timeout=1)
time.sleep(2)

ser.write(b"ATZ\r")
time.sleep(1)

print(ser.read(100))

ser.write(b"ATSP5\r")
time.sleep(1)
ser.write(b"0100\r")
time.sleep(1)


print(ser.read(100))