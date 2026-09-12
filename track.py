import argparse
import csv
import time

import cv2

from tracker import BeaconTracker

FIELDS = [
    "time", "t", "frame", "state", "x", "y", "err_x_px", "err_y_px", "err_mrad",
    "pan_cmd_deg", "tilt_cmd_deg", "blobs", "fps", "proc_ms", "lock_pct", "first_lock_s",
]

COLORS = {"LOCKED": (0, 220, 0), "ACQUIRED": (0, 200, 255), "LOST": (0, 0, 255), "SEARCHING": (200, 200, 200)}


def draw(frame, tr, d):
    h, w = frame.shape[:2]
    bx, by = w // 2, h // 2
    color = COLORS[d["state"]]

    # crosshair and lock circle
    cv2.line(frame, (bx - 20, by), (bx + 20, by), (255, 255, 255), 1)
    cv2.line(frame, (bx, by - 20), (bx, by + 20), (255, 255, 255), 1)
    cv2.circle(frame, (bx, by), tr.lock_px, (255, 255, 255), 1)

    for x, y, _, _ in tr.blobs:
        cv2.circle(frame, (int(x), int(y)), 9, (130, 130, 130), 1)
    if d["x"] is not None:
        x, y = int(d["x"]), int(d["y"])
        cv2.rectangle(frame, (x - 16, y - 16), (x + 16, y + 16), color, 2)
        cv2.line(frame, (bx, by), (x, y), color, 1)

    text = [
        d["state"],
        f"err {d['err_x_px']:+.0f},{d['err_y_px']:+.0f} px   {d['err_mrad']:.1f} mrad",
        f"cmd pan {d['pan_cmd_deg']:+.2f}  tilt {d['tilt_cmd_deg']:+.2f} deg",
        f"{d['fps']:.0f} fps   {d['proc_ms']:.1f} ms   lock {d['lock_pct']:.0f}%",
    ]
    for i, line in enumerate(text):
        cv2.putText(frame, line, (10, 26 + i * 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    color if i == 0 else (255, 255, 255), 1, cv2.LINE_AA)
    return frame


def main():
    ap = argparse.ArgumentParser(description="OptiNex real-time beacon tracker")
    ap.add_argument("--source", default="0", help="camera number, video file or stream url (default: webcam 0)")
    ap.add_argument("--hfov", type=float, default=60.0, help="camera's horizontal field of view in degrees")
    ap.add_argument("--threshold", type=int, default=220, help="how bright a pixel must be to count, 0-255")
    ap.add_argument("--max-area", type=int, default=5000, help="biggest blob (px) that can be the beacon; raise it if the torch is close")
    ap.add_argument("--csv", default="tracklog.csv", help="log file, every frame goes in here ('' = no log)")
    ap.add_argument("--serve", action="store_true", help="stream the data live on ws://127.0.0.1:8765")
    ap.add_argument("--serial", help="serial port of the pan/tilt servo board, e.g. /dev/tty.usbmodem1101")
    ap.add_argument("--no-window", action="store_true", help="don't show the video window")
    ap.add_argument("--fast", action="store_true", help="for video files: don't wait, run as fast as possible")
    args = ap.parse_args()

    src = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(src)
    ok, frame = cap.read()
    if not ok:
        raise SystemExit(f"couldn't read from {args.source} (on a Mac, allow camera access for the terminal)")
    h, w = frame.shape[:2]
    is_file = isinstance(src, str) and not src.startswith(("rtsp://", "http://", "https://"))
    file_dt = 1 / (cap.get(cv2.CAP_PROP_FPS) or 30)

    tracker = BeaconTracker(w, h, hfov=args.hfov, threshold=args.threshold, max_area=args.max_area)

    stream = None
    if args.serve:
        from stream import DataStream
        stream = DataStream()
        print("streaming on ws://127.0.0.1:8765")

    servo = None
    if args.serial:
        from servo import PanTilt
        servo = PanTilt(args.serial)

    log = writer = None
    if args.csv:
        log = open(args.csv, "w", newline="")
        writer = csv.DictWriter(log, fieldnames=FIELDS)
        writer.writeheader()

    print(f"tracking {args.source} ({w}x{h})   q = quit, r = reset")
    last = time.perf_counter()
    last_print = 0.0
    data = None
    try:
        while ok:
            now = time.perf_counter()
            dt = file_dt if is_file else now - last
            last = now

            data = tracker.update(frame, dt)
            if writer:
                writer.writerow(data)
            if stream:
                stream.send(data)
            if servo and tracker.tracking:
                servo.nudge(data["pan_cmd_deg"], data["tilt_cmd_deg"])

            if now - last_print > 1.0:
                print(f"{data['state']:<9} err {data['err_mrad']:7.1f} mrad   {data['fps']:4.0f} fps   blobs {data['blobs']}")
                last_print = now

            if not args.no_window:
                cv2.imshow("OptiNex tracker", draw(frame, tracker, data))
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord("r"):
                    tracker.reset()
            elif is_file and not args.fast:
                time.sleep(max(0.0, file_dt - (time.perf_counter() - now)))

            ok, frame = cap.read()
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        if log:
            log.close()
        if stream:
            stream.close()
        cv2.destroyAllWindows()

    if data:
        print(f"\n{tracker.frames} frames, locked {data['lock_pct']}% of the time, first lock at {tracker.first_lock} s")
        if args.csv:
            print(f"log saved to {args.csv}")


if __name__ == "__main__":
    main()
