"""Web version of the tracker, so it can be tried from any computer.

    python app.py            # http://127.0.0.1:7860
    python app.py --share    # also gives a public link anyone can open

The visitor's webcam frames come in here, go through the same tracker.py as
the desktop version, and the frame goes back with the tracking drawn on it.
"""
import argparse
import time

import cv2
import gradio as gr

from track import draw
from tracker import BeaconTracker

INTRO = """
# OptiNex Tracker
Real-time beacon tracker for the coarse alignment stage of FSOC links (SIH 2026, SIH26169).

1. Allow the camera and press the record button under **Your camera**.
2. Keep your torch off for the first few seconds while it learns the room.
3. Turn on your phone's torch and point it at the camera. The box turns yellow (ACQUIRED).
4. Bring it to the crosshair and hold it. It turns green (LOCKED).

Works best in a dim room.
"""


def process(frame, session):
    """Runs for every frame the browser sends. frame is RGB."""
    if frame is None:
        return None, "Waiting for the camera..."
    bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    h, w = bgr.shape[:2]
    now = time.time()

    tr = session.get("tracker")
    if tr is None or tr.boresight != (w / 2, h / 2):
        tr = session["tracker"] = BeaconTracker(w, h)
        session["last"] = now - 0.1
    dt = min(now - session["last"], 0.5)
    session["last"] = now

    d = tr.update(bgr, dt)
    shown = draw(bgr, tr, d)

    if tr.learning:
        text = "**Learning the room, keep the torch off...**"
    else:
        text = (
            f"**{d['state']}** · error {d['err_x_px']:+.0f}, {d['err_y_px']:+.0f} px ({d['err_mrad']:.1f} mrad)"
            f" · turn pan {d['pan_cmd_deg']:+.2f}°, tilt {d['tilt_cmd_deg']:+.2f}°"
            f" · {d['fps']:.0f} fps · {d['proc_ms']:.1f} ms per frame · locked {d['lock_pct']:.0f}% of the time"
        )
    return cv2.cvtColor(shown, cv2.COLOR_BGR2RGB), text


def reset(session):
    if session.get("tracker"):
        session["tracker"].reset()


def relearn(session):
    if session.get("tracker"):
        session["tracker"].relearn()


with gr.Blocks(title="OptiNex Tracker") as demo:
    gr.Markdown(INTRO)
    session = gr.State({})  # every visitor gets their own tracker
    with gr.Row():
        cam = gr.Image(sources=["webcam"], streaming=True, label="Your camera")
        out = gr.Image(label="What the tracker sees")
    stats = gr.Markdown()
    with gr.Row():
        gr.Button("Reset track").click(reset, session)
        gr.Button("Re-learn the room (torch off)").click(relearn, session)
    cam.stream(process, inputs=[cam, session], outputs=[out, stats], stream_every=0.08)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--share", action="store_true", help="make a public link that works on any computer")
    ap.add_argument("--port", type=int, default=7860)
    args = ap.parse_args()
    demo.launch(share=args.share, server_port=args.port)
