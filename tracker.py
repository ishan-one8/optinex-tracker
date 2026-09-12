import math
import time

import cv2
import numpy as np

WARMUP_FRAMES = 10  # a webcam's first frames are dark while its exposure settles, skip them
LEARN_FRAMES = 20  # then learn the room from this many frames (about a second in total)


class BeaconTracker:
    """Finds the beacon (a small bright spot that isn't part of the room) in each
    frame, follows it with a Kalman filter and works out how far it is from the
    centre of the camera."""

    def __init__(self, width, height, hfov=60.0, threshold=220, max_area=None):
        s = width / 640  # the pixel numbers below were picked on a 640 px wide image
        self.deg_per_px = hfov / width
        self.threshold = threshold
        self.min_area = 4 * s * s  # smaller than this = noise
        self.max_area = max_area or 5000 * s * s  # bigger than this = a lamp or a window
        self.gate_px = 60 * s  # while tracking, only look this far from where we expect it
        self.lock_px = 25 * s  # within this of the centre counts as locked
        self.boresight = (width / 2, height / 2)

        # state = x, y, vx, vy (pixels, pixels/s)
        self.kf = cv2.KalmanFilter(4, 2)
        self.kf.measurementMatrix = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], np.float32)
        self.kf.processNoiseCov = np.eye(4, dtype=np.float32) * 1.0
        self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 4.0
        self.relearn()
        self.reset()

    def reset(self):
        self.tracking = False
        self.missed_time = 0.0
        self.state = "SEARCHING"
        self.lock_frames = 0
        self.frames = 0
        self.t = 0.0
        self.fps = 0.0
        self.locked_time = 0.0
        self.first_lock = None
        self.blobs = []
        self.target = None
        self.track_age = 0.0
        # other lights seen while we had the beacon: [x, y, times_seen, last_seen]
        self.clutter = []

    def relearn(self):
        """Forget what the room looks like and learn it again. Do it with the torch off."""
        self.background = None
        self.bg_frames = 0

    @property
    def learning(self):
        return self.bg_frames < WARMUP_FRAMES + LEARN_FRAMES

    def find_blobs(self, blur):
        # the beacon has to be bright AND a lot brighter than that spot normally is,
        # so ceiling lights, windows and screens that were there from the start don't count
        new = cv2.subtract(blur, self.background.astype(np.uint8))
        mask = ((blur > self.threshold) & (new > 40)).astype(np.uint8)
        n, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
        blobs = []
        for i in range(1, n):
            x, y, w, h, area = (int(v) for v in stats[i])
            if area < self.min_area or area > self.max_area:
                continue
            if area / (w * h) < 0.4 or max(w, h) > 3 * min(w, h):
                continue  # long or ragged: an edge or a reflection, not a spot
            peak = int(blur[y : y + h, x : x + w].max())
            blobs.append((float(centroids[i][0]), float(centroids[i][1]), peak, area))
        # brightest first, if two are equally bright take the bigger one
        blobs.sort(key=lambda b: (b[2], b[3]), reverse=True)
        return blobs

    def is_clutter(self, blob):
        return any(c[2] >= 10 and math.hypot(c[0] - blob[0], c[1] - blob[1]) < self.gate_px / 3 for c in self.clutter)

    def update(self, frame, dt):
        start = time.perf_counter()
        self.frames += 1
        self.t += dt
        if dt > 0.001:
            self.fps = 1 / dt if not self.fps else self.fps * 0.9 + 0.1 / dt

        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)

        was_learning = self.learning
        if was_learning:
            # average a second of frames (after the warm-up): that's what the room looks like
            self.bg_frames += 1
            n = self.bg_frames - WARMUP_FRAMES
            if n == 1:
                self.background = blur.astype(np.float32)
            elif n > 1:
                cv2.accumulateWeighted(blur, self.background, 1 / n)
            self.blobs = []
        else:
            self.blobs = self.find_blobs(blur)

        target = None
        if self.tracking:
            self.kf.transitionMatrix = np.array(
                [[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]], np.float32
            )
            px, py = self.kf.predict()[:2, 0]
            near = [b for b in self.blobs if math.hypot(b[0] - px, b[1] - py) < self.gate_px]
            if near:
                target = min(near, key=lambda b: math.hypot(b[0] - px, b[1] - py))
                self.kf.correct(np.array([[target[0]], [target[1]]], np.float32))
            else:
                # opencv doesn't carry the prediction over if you skip correct()
                self.kf.statePost = self.kf.statePre.copy()
                self.kf.errorCovPost = self.kf.errorCovPre.copy()
        else:
            # start a new track on the brightest light that isn't one we already
            # know is a lamp. if there's nothing new, keep waiting.
            fresh = [b for b in self.blobs if not self.is_clutter(b)]
            if fresh:
                target = fresh[0]
                self.kf.statePost = np.array([[target[0]], [target[1]], [0], [0]], np.float32)
                self.kf.errorCovPost = np.eye(4, dtype=np.float32) * 10
                self.tracking = True
                self.track_age = 0.0
        self.target = target

        # while we're on the beacon, every other light in view is by definition
        # not the beacon. remember them so a dropout doesn't hand the track to one.
        if target is not None and self.track_age > 1.0:
            for b in self.blobs:
                if b is target:
                    continue
                for c in self.clutter:
                    if math.hypot(c[0] - b[0], c[1] - b[1]) < self.gate_px / 4:
                        c[0], c[1], c[2], c[3] = b[0], b[1], c[2] + 1, self.t
                        break
                else:
                    self.clutter.append([b[0], b[1], 1, self.t])
        # forget lights we haven't seen in a while (or the camera has moved)
        self.clutter = [c for c in self.clutter if self.t - c[3] < 10]

        if self.tracking:
            self.track_age += dt
        if target:
            self.missed_time = 0.0
        elif self.tracking:
            self.missed_time += dt
            if self.missed_time > 1.0:  # gone for a second, start looking again
                self.tracking = False

        bx, by = self.boresight
        if self.tracking:
            x, y, vx, vy = (float(v) for v in self.kf.statePost.ravel())
            err_x, err_y = x - bx, y - by
            # aim a bit ahead to make up for camera + processing delay
            aim_x, aim_y = err_x + vx * 0.05, err_y + vy * 0.05
        else:
            x = y = None
            err_x = err_y = aim_x = aim_y = 0.0
        err_px = math.hypot(err_x, err_y)
        err_mrad = math.radians(err_px * self.deg_per_px) * 1000

        # let the room model follow slow lighting changes, but not around the
        # beacon, or a torch held still would slowly fade into the background
        if not was_learning:
            keep = np.full(blur.shape, 255, np.uint8)
            if x is not None:
                cv2.circle(keep, (int(x), int(y)), int(self.gate_px), 0, -1)
            cv2.accumulateWeighted(blur, self.background, 0.005, mask=keep)

        if not self.tracking:
            self.state = "SEARCHING"
        elif target is None:
            if self.missed_time > 0.4:
                self.state = "LOST"
        elif err_px < self.lock_px:
            self.lock_frames += 1
            self.state = "LOCKED" if self.lock_frames >= 10 else "ACQUIRED"
        else:
            self.lock_frames = 0
            self.state = "ACQUIRED"
        if self.state in ("SEARCHING", "LOST"):
            self.lock_frames = 0

        if self.state == "LOCKED":
            self.locked_time += dt
            if self.first_lock is None:
                self.first_lock = round(self.t, 2)

        return {
            "time": round(time.time(), 3),
            "t": round(self.t, 3),
            "frame": self.frames,
            "state": self.state,
            "x": round(x, 1) if x is not None else None,
            "y": round(y, 1) if y is not None else None,
            "err_x_px": round(err_x, 1),
            "err_y_px": round(err_y, 1),
            "err_mrad": round(err_mrad, 2),
            # how far the pan/tilt needs to turn to centre it (right / up are positive)
            "pan_cmd_deg": round(aim_x * self.deg_per_px, 3),
            "tilt_cmd_deg": round(-aim_y * self.deg_per_px, 3),
            "blobs": len(self.blobs),
            "fps": round(self.fps, 1),
            "proc_ms": round((time.perf_counter() - start) * 1000, 2),
            "lock_pct": round(100 * self.locked_time / self.t, 1) if self.t else 0.0,
            "first_lock_s": self.first_lock,
        }
