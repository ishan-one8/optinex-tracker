import serial  # pip install pyserial


class PanTilt:
    """Two hobby servos on an Arduino. Sends 'pan,tilt' in degrees (0-180),
    one line per update, at 115200 baud."""

    def __init__(self, port, gain=0.4):
        self.ser = serial.Serial(port, 115200, timeout=0)
        self.pan = 90.0
        self.tilt = 90.0
        self.gain = gain  # don't jump the whole way each frame or it overshoots

    def nudge(self, d_pan, d_tilt):
        # if the camera turns away from the beacon, your servo is mounted the
        # other way round: flip the sign of that axis here
        self.pan = min(max(self.pan + d_pan * self.gain, 0), 180)
        self.tilt = min(max(self.tilt + d_tilt * self.gain, 0), 180)
        self.ser.write(f"{self.pan:.1f},{self.tilt:.1f}\n".encode())
