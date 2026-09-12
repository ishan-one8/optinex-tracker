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

## Complete code walkthrough (easy Hinglish)

This section explains what every source file does and how data moves through
the project. The tracker does not use a trained AI/ML model. It uses normal
computer-vision rules, background subtraction and an OpenCV Kalman filter.

### Full project flow

```text
camera / video / stream
        |
        v
track.py or app.py reads one frame
        |
        v
tracker.py learns the room and finds new bright spots
        |
        v
Kalman filter follows the selected beacon
        |
        v
centre error and pan/tilt correction are calculated
        |
        +--> result is drawn on the frame
        +--> result can be written to CSV
        +--> result can be sent over WebSocket
        +--> result can move the pan/tilt servos
```

### `tracker.py` - detection and tracking engine

`tracker.py` contains the `BeaconTracker` class. This is the main brain of the
project. It receives one camera frame at a time and returns the beacon position,
tracking state, pointing error and servo correction.

#### Imports and constants

- `math` is used for distance and angle calculations.
- `time` is used to measure processing time and add timestamps.
- `cv2` provides image processing, connected components and the Kalman filter.
- `numpy` stores images, matrices and Kalman filter values.
- `WARMUP_FRAMES = 10` skips the webcam's first dark/unstable frames while
  auto-exposure settles.
- `LEARN_FRAMES = 20` uses the next 20 frames to create an average picture of
  the room.

#### `BeaconTracker.__init__()`

The constructor receives the frame `width`, frame `height`, camera horizontal
field of view (`hfov`), brightness `threshold` and optional `max_area`.

- `s = width / 640` scales all pixel-based limits for the current resolution.
  A 1280-pixel-wide frame therefore gets limits twice as large as a 640-pixel
  frame.
- `deg_per_px = hfov / width` converts a horizontal pixel error into degrees.
- `min_area` rejects tiny noisy spots.
- `max_area` rejects objects that are probably a lamp, window or large glare.
- `gate_px` is the maximum distance allowed between the Kalman prediction and
  the next accepted measurement.
- `lock_px` is the radius around the image centre that counts as aligned.
- `boresight` is the centre of the camera frame.

The Kalman state has four values:

```text
[x, y, vx, vy]
```

Here `x, y` are the estimated beacon coordinates and `vx, vy` are its speed in
pixels per second. The measurement contains only `x, y`; the filter estimates
velocity from movement across frames.

#### `reset()`

`reset()` forgets the current track and clears runtime statistics. It resets:

- whether a beacon is being tracked;
- missed-beacon time and current state;
- lock-frame count, elapsed frames, FPS and lock percentage data;
- current blobs and target;
- remembered clutter lights.

It does not erase the learned room background. This is why the `r` key resets
only the track.

#### `relearn()` and `learning`

`relearn()` deletes the stored background and sets the background frame count
to zero. The `learning` property stays true until all warm-up and learning
frames have been processed. This is what the `b` key and the web UI's
**Re-learn the room** button use.

#### `find_blobs(blur)`

This function finds possible beacon spots in a blurred grayscale frame.

1. `cv2.subtract()` compares the current frame with the learned room.
2. A pixel is accepted only when its current brightness is above `threshold`
   and it is more than 40 brightness levels above the background.
3. `connectedComponentsWithStats()` joins neighbouring accepted pixels into
   blobs and gives each blob a box, area and centre point.
4. Blobs smaller than `min_area` or bigger than `max_area` are rejected.
5. Long, thin or very ragged blobs are rejected because they are more likely
   to be an edge or reflection than a beacon spot.
6. Remaining blobs are sorted by peak brightness and then area, brightest
   first.

Each returned blob contains:

```text
(centre_x, centre_y, peak_brightness, area)
```

#### `is_clutter(blob)`

While a real beacon is being followed, other repeated lights are remembered as
`clutter`. A new candidate is considered clutter when it has already been seen
at least 10 times and is close to a remembered clutter position. This prevents
a fixed lamp from stealing the track after a beacon dropout.

#### `update(frame, dt)`

`update()` runs once for every frame. `dt` is the number of seconds since the
previous frame.

Its work happens in this order:

1. **Update timing.** It increases frame/time counters and calculates a
   smoothed FPS value.
2. **Prepare the image.** A colour frame is converted to grayscale and blurred
   with a 5x5 Gaussian filter to reduce noise.
3. **Learn or detect.** During learning, frames are averaged into the room
   background. Afterwards, `find_blobs()` finds candidate lights.
4. **Predict.** If tracking is already active, the Kalman transition matrix is
   updated using `dt` and the next beacon position is predicted.
5. **Match.** Only blobs inside `gate_px` of the prediction are considered. The
   closest one corrects the Kalman estimate.
6. **Start a new track.** If no track is active, the brightest candidate that
   is not known clutter becomes the target. Its initial velocity is zero.
7. **Handle missing frames.** With no measurement, the predicted Kalman state
   is carried forward. After 0.4 seconds the state can become `LOST`; after one
   second the tracker gives up the old track and starts searching again.
8. **Remember distractions.** Other blobs visible during a stable track are
   saved as clutter. Clutter not seen for 10 seconds is forgotten.
9. **Calculate error.** Beacon position is compared with `boresight`, producing
   signed horizontal and vertical pixel error plus total radial error.
10. **Calculate steering.** A small `velocity * 0.05` lead aims slightly ahead
    of a moving beacon to compensate for camera and processing delay.
11. **Update the room slowly.** Normal lighting changes are added to the
    background with a very small weight (`0.005`). The area around the tracked
    beacon is protected so a stationary beacon does not disappear into the
    background.
12. **Choose the state.** The result becomes `SEARCHING`, `ACQUIRED`, `LOCKED`
    or `LOST`.

The main error calculations are:

```text
err_x = beacon_x - centre_x
err_y = beacon_y - centre_y
err_px = distance from beacon to centre
err_mrad = radians(err_px * degrees_per_pixel) * 1000
```

The steering calculations are:

```text
pan correction  = (err_x + vx * 0.05) * degrees_per_pixel
tilt correction = -(err_y + vy * 0.05) * degrees_per_pixel
```

Tilt has a minus sign because image `y` increases downwards, while positive
tilt is defined as upwards.

The method finally returns a dictionary containing the timestamp, state,
position, error, steering commands, blob count, FPS, processing time, lock
percentage and first-lock time.

### Tracking state meaning

```text
SEARCHING --> ACQUIRED --> LOCKED
                  |
                  v
                 LOST --> SEARCHING
```

- `SEARCHING`: no acceptable beacon is currently being followed.
- `ACQUIRED`: a beacon has been found, but it is not yet stable at the centre.
- `LOCKED`: the beacon has stayed inside the lock circle for at least 10
  consecutive frames.
- `LOST`: an active beacon is temporarily missing and the Kalman filter is
  predicting its position.

### `track.py` - desktop runner and coordinator

`track.py` connects the tracker engine to a webcam, video file or stream. It
also handles the OpenCV window, command-line options, CSV logging, video
recording, WebSocket output and optional servo control.

#### `FIELDS` and `COLORS`

`FIELDS` defines the exact order of columns written to the CSV log. `COLORS`
maps each tracking state to an OpenCV BGR colour: green for locked, yellow for
acquired, red for lost and grey for searching.

#### `draw(frame, tr, d)`

`draw()` modifies the current frame to show what the tracker is doing:

- a centre crosshair and lock circle;
- grey circles around all detected blobs;
- a coloured box around the estimated beacon;
- a line from the centre to the beacon;
- state, pixel/angular error, pan/tilt command, FPS, processing time and lock
  percentage.

During room learning it replaces those stats with the instruction to keep the
torch off.

#### `main()`

`main()` performs the complete desktop workflow:

1. Parse command-line options with `argparse`.
2. Convert a numeric source such as `0` into a webcam number; other values stay
   strings for video files or URLs.
3. Open the source using `cv2.VideoCapture()` and read the first frame.
4. Use the first frame to determine resolution and create `BeaconTracker`.
5. Optionally start `DataStream`, `PanTilt`, `VideoWriter` and a CSV writer.
6. Repeatedly call `tracker.update(frame, dt)` for every frame.
7. Send the returned data to enabled outputs.
8. Draw the overlay and display or record it.
9. Handle `q`, `r` and `b` keyboard controls.
10. Release the camera, video writer, CSV file and WebSocket server in the
    `finally` block, even if the program is stopped with `Ctrl+C`.

For a video file, `dt` comes from the video's FPS. For a live camera, it comes
from real elapsed time. Unless `--fast` is used, a headless video run waits so
it processes at approximately the original playback speed.

### `app.py` - Gradio web interface

`app.py` wraps the same `BeaconTracker` and `draw()` functions in a browser UI.
It does not contain a second tracking algorithm.

#### `process(frame, session)`

This function runs whenever the browser sends a webcam frame.

1. Wait if no frame has arrived.
2. Convert the browser's RGB image to OpenCV BGR.
3. Create a tracker for this visitor if one does not exist or the resolution
   has changed.
4. Calculate `dt`, limited to 0.5 seconds so a long browser pause does not cause
   one huge Kalman update.
5. Run `tr.update()` and `draw()`.
6. Convert the result back to RGB for the browser.
7. Return the annotated frame and a Markdown status line.

`gr.State({})` gives every visitor their own tracker state. The **Reset track**
button calls `reset()`, while **Re-learn the room** calls `relearn()`.
`stream_every=0.08` asks Gradio to process roughly one frame every 80 ms when
possible.

The web version currently uses the default tracker settings. CSV logging,
recording, WebSocket streaming and servo control belong to the desktop runner
and are not exposed in this web UI.

### `stream.py` - WebSocket telemetry

`stream.py` defines `DataStream`, which broadcasts every tracker result as JSON
on `ws://127.0.0.1:8765` by default.

- `__init__()` creates a WebSocket server and runs it in a daemon thread.
- `_handle()` adds connected clients to a shared set, keeps their connection
  open and removes them when they disconnect.
- `send(data)` converts the tracker dictionary to JSON and sends it to a copy
  of the current client list.
- `close()` shuts down the server.

A threading lock protects the client set because the camera loop and WebSocket
server run in different threads. Failed sends are ignored because the handler
will clean up disconnected clients.

### `servo.py` - Arduino pan/tilt output

`servo.py` defines `PanTilt` for two hobby servos connected through an Arduino.

- The serial connection runs at 115200 baud.
- Both servo angles start at 90 degrees.
- `nudge(d_pan, d_tilt)` adds part of the requested correction to the current
  angles.
- The default gain is `0.4`, so the mount moves gradually instead of jumping
  the full correction and overshooting.
- Both angles are clamped to the normal servo range of 0 to 180 degrees.
- Each update is sent as one line: `pan,tilt\n`.

Example serial output:

```text
92.4,87.6
```

If an axis moves in the wrong direction, the sign of that axis can be reversed
inside `nudge()`. This repository sends the serial commands but does not include
the Arduino sketch that reads them.

### `requirements.txt` - Python dependencies

- `opencv-python`: camera input, image processing, Kalman filter and drawing.
- `numpy`: image arrays and matrices.
- `websockets`: optional live JSON stream.
- `gradio`: browser version.
- `pyserial`: optional Arduino serial connection.

### `.gitignore` - generated files not committed

- `.venv/`: local Python virtual environment.
- `__pycache__/`: Python's generated bytecode cache.
- `tracklog.csv`: default tracker log.
- `*.mp4`: recorded output videos.

### One-line mental model

`tracker.py` thinks, `track.py` connects everything on the desktop, `app.py`
provides the browser UI, `stream.py` broadcasts readings and `servo.py` moves
the hardware.
