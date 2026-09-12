# OptiNex tracker

Real-time beacon tracker for the coarse alignment stage of an FSOC link.
It reads frames from a real camera, finds the beacon, follows it with a Kalman
filter and works out how much a pan/tilt mount has to turn to put it in the
centre of the view. No simulation: whatever the camera sees is what it tracks.

## Setup

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```
python track.py                          # laptop webcam
python track.py --source 1               # a USB camera
python track.py --source clip.mp4        # a recorded video
python track.py --serve                  # also stream the data live on ws://127.0.0.1:8765
```

Press `q` to quit, `r` to reset. Every frame gets written to `tracklog.csv`.

For the beacon use a phone torch or an LED, in a room that isn't too bright.
If lamps or windows get picked up, raise `--threshold` (default 220). The
first time on a Mac it will ask for camera access for the terminal.

## What it measures, every frame

| field | meaning |
| --- | --- |
| `state` | SEARCHING, ACQUIRED, LOCKED or LOST |
| `x`, `y` | where the beacon is in the frame (px) |
| `err_x_px`, `err_y_px` | offset from the centre of the view (px) |
| `err_mrad` | the same offset as an angle, in milliradians |
| `pan_cmd_deg`, `tilt_cmd_deg` | how far to turn to centre it (right / up = +) |
| `fps`, `proc_ms` | frame rate and time spent per frame |
| `lock_pct` | share of the time spent locked so far |

The angle numbers depend on `--hfov`, the camera's horizontal field of view.
Most laptop webcams are somewhere around 60-70 degrees.

## Driving real servos

With two servos on an Arduino, pass `--serial /dev/tty.usbmodemXXXX`. The
tracker sends `pan,tilt\n` in degrees (0-180) at 115200 baud and keeps nudging
them until the beacon is in the middle. If an axis turns the wrong way, flip
its sign in `servo.py`.

## How it works

1. Blur, threshold, and find bright blobs. Too small is noise, too big is a lamp or window.
2. No track yet: take the brightest blob.
3. Tracking: predict where it'll be with the Kalman filter and only accept a
   blob close to that prediction, so other lights don't steal the track.
4. Missing for a bit: keep predicting. Missing for over a second: start over.
5. Locked once it's been within 25 px of the centre for 10 frames.

## Files

- `track.py` - camera loop, drawing, logging, arguments
- `tracker.py` - detection, Kalman filter, states, error
- `stream.py` - websocket stream
- `servo.py` - pan/tilt servos over serial (optional)
