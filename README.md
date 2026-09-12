# OptiNex Tracker

Real-time beacon tracker for the coarse alignment stage of free-space optical
communication (FSOC) links. Built for Smart India Hackathon 2026, problem
statement SIH26169 (ISRO).

It watches a live camera feed, finds the beacon, follows it with a Kalman filter
and works out how far a pan/tilt mount has to turn to bring it to the centre of
the view. Everything it tracks is what the camera actually sees.

## Quick start

```
git clone https://github.com/ishan-one8/optinex-tracker.git
cd optinex-tracker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python track.py
```

1. **Keep the torch off for the first second.** The window says "LEARNING THE
   ROOM" while it remembers every light that's normally there (ceiling lights,
   windows, screens). After that it only looks for lights that are new.
2. Turn a phone torch on and point it at the camera. The box turns **ACQUIRED**.
3. Bring it to the crosshair and hold it there. It turns **LOCKED** (green).

Keys: `q` quit, `r` reset the track, `b` re-learn the room (torch off).
The first time on a Mac it asks for camera access for the terminal.

## Try it from any computer

`app.py` is the same tracker as a web page, still all Python (built with Gradio):

```
python app.py --share
```

It prints a public link like `https://xxxx.gradio.live`. Anyone can open it in a
browser, allow their camera, and the tracker runs on their torch live. The link
works for 72 hours, as long as your laptop keeps `app.py` running.

For a link that never expires, put the repo on Hugging Face Spaces (free):
create a new Space, pick the Gradio SDK, and upload `app.py`, `tracker.py`,
`track.py` and `requirements.txt`.

## What you see

- **Crosshair and circle**: the centre of the view. Inside the circle for 10
  frames counts as locked.
- **Box**: where the tracker thinks the beacon is. Green = locked, yellow =
  tracking but off centre, red = lost (still predicting where it went).
- **Grey rings**: other lights it saw and ignored.
- **Top left**: state, pointing error, the pan/tilt correction needed, fps,
  processing time and how much of the time it's been locked.

## Options

| option | what it does |
| --- | --- |
| `--source 1` | use a different camera, a video file, or a stream url |
| `--hfov 60` | the camera's horizontal field of view, used to turn pixels into angles |
| `--threshold 220` | how bright (0-255) a pixel has to be to count |
| `--max-area N` | biggest spot that can be the beacon; raise it if the torch is very close |
| `--record demo.mp4` | save what the window shows to a video |
| `--serve` | stream every reading as JSON on `ws://127.0.0.1:8765` |
| `--serial PORT` | drive two pan/tilt servos on an Arduino |
| `--csv file.csv` | where the per-frame log goes (default `tracklog.csv`) |

## What it measures, every frame

| field | meaning |
| --- | --- |
| `state` | SEARCHING, ACQUIRED, LOCKED or LOST |
| `x`, `y` | beacon position in the frame (px) |
| `err_x_px`, `err_y_px` | offset from the centre of the view (px) |
| `err_mrad` | the same offset as an angle, in milliradians |
| `pan_cmd_deg`, `tilt_cmd_deg` | how far to turn to centre it (right / up = +) |
| `fps`, `proc_ms` | frame rate and processing time per frame |
| `lock_pct` | share of the time spent locked so far |

## How it works

1. **Learn the room.** Average the first second of frames. From then on a spot
   only counts if it's bright *and* much brighter than that part of the room
   normally is. Too small is noise; too big or too stretched is a lamp, a
   window or a reflection.
2. **Start a track** on the brightest new spot.
3. **Follow it.** A Kalman filter predicts where the beacon will be next frame,
   and only a spot close to that prediction is accepted, so other lights can't
   steal the track.
4. **Ride out dropouts.** If the beacon disappears, keep predicting. After a
   second, start searching again, but never restart on a light that was
   visible the whole time we were tracking the beacon.
5. **Steer.** The error from the centre becomes a pan/tilt correction, aimed a
   little ahead of the beacon to make up for camera and processing delay.
6. **Keep up with the room.** The room model adapts slowly to lighting changes,
   except around the beacon, so a torch held still doesn't fade away.

## How it was tested

A live camera can't tell you where the beacon really is, so accuracy was
measured on generated test clips where the true position of the beacon is
known in every frame.

| test clip | result |
| --- | --- |
| Lit room, 1280x720: window, screen, ceiling light, five shiny reflections, camera auto-exposure | tracked in all 375 frames, 6.8 px average error, 0 frames on the wrong light, locked the whole time it was held at the centre |
| Moving beacon, a fixed lamp and a 1.2 s blackout | all 205 visible frames, 5.0 px average error, came back to the beacon (not the lamp) after the blackout |
| Beacon held at the centre, then moved away | locked in 0.3 s, 2.0 px average error |
| Speed | about 2 ms per frame at 1280x720 |

## Driving real servos

With two hobby servos on an Arduino, run with `--serial /dev/tty.usbmodemXXXX`.
The tracker sends `pan,tilt\n` in degrees (0-180) at 115200 baud and keeps
nudging them until the beacon is in the middle. If an axis turns the wrong
way, flip its sign in `servo.py`.

## Files

- `track.py` - camera loop, drawing, recording, logging, options
- `app.py` - web version for any browser (Gradio)
- `tracker.py` - detection, room model, Kalman filter, states, error
- `stream.py` - websocket stream
- `servo.py` - pan/tilt servos over serial (optional)
