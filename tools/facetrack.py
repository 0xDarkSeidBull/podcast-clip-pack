"""Find where the speaker is in each shot of a clip, so the square crop keeps them in frame.

Samples frames, splits the clip into shots at hard cuts, and returns one crop
x-offset per shot (median face centre). A clip config can pin a region instead.
"""
import cv2
import numpy as np

CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def sample(src, start, end, fps=4):
    cap = cv2.VideoCapture(src)
    out = []
    t = start
    while t < end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        out.append((t - start, frame))
        t += 1.0 / fps
    cap.release()
    return out


def faces(frame, region=None):
    x0 = 0
    if region:
        x0, x1 = region
        frame = frame[:, x0:x1]
    small = cv2.resize(frame, None, fx=0.5, fy=0.5)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    found = CASCADE.detectMultiScale(gray, 1.1, 6, minSize=(40, 40))
    return [(x0 + (x + w / 2) * 2, (y + h / 2) * 2, w * 2) for x, y, w, h in found]


def shots(frames, thresh=28.0):
    """Indices where a hard cut starts a new shot."""
    cuts = [0]
    prev = None
    for i, (_, f) in enumerate(frames):
        g = cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (160, 90)).astype(np.float32)
        if prev is not None and np.abs(g - prev).mean() > thresh:
            cuts.append(i)
        prev = g
    return cuts


def refine(src, start, t_before, t_after, thresh=28.0):
    """Frame-accurate time (relative to start) of the cut between two coarse samples."""
    fine = sample(src, start + t_before, start + t_after + 0.05, fps=30)
    prev = None
    for t, f in fine:
        g = cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (160, 90)).astype(np.float32)
        if prev is not None and np.abs(g - prev).mean() > thresh:
            return t_before + t
        prev = g
    return t_after


def track(src, start, end, crop_w, frame_w, region=None, pick="largest", max_cx=None, default_cx=None):
    """Return [(t_start, x_offset), ...] relative to clip start."""
    frames = sample(src, start, end)
    cuts = shots(frames) + [len(frames)]
    plan = []
    for a, b in zip(cuts, cuts[1:]):
        xs = []
        for _, f in frames[a:b]:
            fs = [q for q in faces(f, region) if max_cx is None or q[0] < max_cx]
            if not fs:
                continue
            if pick == "largest":
                fx = max(fs, key=lambda q: q[2])[0]
            elif pick == "right":
                fx = max(fs, key=lambda q: q[0])[0]
            else:
                fx = min(fs, key=lambda q: q[0])[0]
            xs.append(fx)
        lo, hi = (region if region else (0, frame_w))
        if xs:
            cx = float(np.median(xs))
        elif default_cx is not None:
            cx = default_cx
        elif plan:
            cx = plan[-1][2]
        else:
            cx = (lo + hi) / 2
        x = int(round(min(max(cx - crop_w / 2, lo), hi - crop_w)))
        t0 = refine(src, start, frames[a - 1][0], frames[a][0]) if a else 0.0
        plan.append((t0, x, cx))
    # merge consecutive shots with near-identical framing
    merged = []
    for t, x, cx in plan:
        if merged and abs(merged[-1][1] - x) < 24:
            continue
        merged.append((t, x, cx))
    return [(t, x) for t, x, _ in merged]
