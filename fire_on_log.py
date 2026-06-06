#!/usr/bin/env python3
"""Animate a looping "fire on a log" GIF as an iTerm2 background that FOLLOWS
keyboard focus and stays a fixed size, anchored to the top-right corner of the
focused pane.

How it stays circular + fixed-size on every window/pane:
  * Each focused pane reports its exact point size via ``session.frame``.
  * We render the background canvas at that pane's size (so canvas aspect ==
    pane aspect) and paste a fixed-pixel-size circular orb in the top-right.
  * BackgroundImageMode.STRETCH then maps the canvas 1:1 onto the pane, so the
    orb is never distorted and is always the same physical size + position.

Modes:
    test   -> one frame on the focused pane
    dance  -> follow focus, animate
    clear  -> remove background from every session
    nudge  -> reposition the crop live (see do_nudge)

Usage: fire_on_log.py {test|dance|clear} [--fps N] [--minutes M]
"""
import os
import sys
import math
import time
import shutil
import asyncio
import iterm2
from PIL import Image, ImageSequence, ImageDraw, ImageFilter, ImageChops, ImageStat

MODE = sys.argv[1] if len(sys.argv) > 1 else "test"
FPS = 12.0
MINUTES = 60.0
for i, a in enumerate(sys.argv):
    if a == "--fps" and i + 1 < len(sys.argv):
        FPS = float(sys.argv[i + 1])
    if a == "--minutes" and i + 1 < len(sys.argv):
        MINUTES = float(sys.argv[i + 1])

# Runtime files live under FIRE_ON_LOG_HOME (default ~/.fire-on-log). The source
# animation is whatever GIF you point FIRE_GIF at (default fire.gif in that home
# dir) -- supply your own; none is bundled.
HOME_DIR = os.environ.get(
    "FIRE_ON_LOG_HOME", os.path.join(os.path.expanduser("~"), ".fire-on-log"))
os.makedirs(HOME_DIR, exist_ok=True)

SRC = os.environ.get("FIRE_GIF", os.path.join(HOME_DIR, "fire.gif"))
CACHE = os.path.join(HOME_DIR, "cache")
STOP_FILE = os.path.join(HOME_DIR, "STOP")
STATE_FILE = os.path.join(HOME_DIR, "frame_idx")
NUDGE_FILE = os.path.join(HOME_DIR, "nudge")   # live "dx dy" crop offset, src px

SS = 2                 # supersample for crisp edges
ORB_PT = 105           # fixed orb diameter in points (same size everywhere)
MARGIN_PT = 16         # gap from the top/right pane edges, in points
D = ORB_PT * SS        # orb diameter in canvas pixels
MARGIN = MARGIN_PT * SS

# Square crop on the flame. A square of side 2*HALF centred on (CX0, CY0), in
# source-GIF pixels. A live nudge offset (read from NUDGE_FILE) is added to the
# centre so the flame can be re-centred without restarting. These defaults are
# tuned for a 480x260 source GIF -- adjust (or use `nudge`) for your own.
CX0, CY0, HALF = 234, 82, 74
NUDGE_STEP = 8         # default px per "nudge" command

# These tunables assume a GIF that already animates smoothly on its own, so no
# synthetic interpolation and no vertical bob (the flame stays anchored).
INTERP = 1             # synthesised frames per keyframe pair (1 = native only)
BOB_AMP_PT = 0         # vertical bob amplitude in points (0 = anchored, no bob)
# Forward-only play (no reverse) so the rising flame never appears to fall.
# The GIF's native wrap (last->first) is a hard cut, so we rotate the sequence
# so the loop seam falls on the smoothest adjacent pair instead -> no jump.
LOOP_ROTATE = True

# Optionally use only a contiguous slice of the GIF's frames (0-indexed,
# inclusive) -- e.g. (1, 11) drops the leading reset frame and the tail. Set to
# None to use every frame. The loop pipeline (reorder + smooth) handles the seam.
FRAME_RANGE = (1, 12)

# Screen-direction -> crop-centre delta. Moving the crop window right makes the
# flame appear further LEFT (and likewise for the other axes), hence the signs.
NUDGE_DIRS = {"left": (1, 0), "right": (-1, 0), "up": (0, 1), "down": (0, -1)}

_SPRITES = []          # fixed-size circular orb frames (RGBA), built at startup
_CACHE = {}            # "WxH_dx_dy" -> [frame png paths]


def read_nudge():
    """Current (dx, dy) crop offset in source pixels (0, 0 if unset)."""
    try:
        with open(NUDGE_FILE) as fh:
            dx, dy = fh.read().split()[:2]
            return int(dx), int(dy)
    except Exception:
        return 0, 0


def crop_box(dx=0, dy=0):
    cx, cy = CX0 + dx, CY0 + dy
    return (cx - HALF, cy - HALF, cx + HALF, cy + HALF)


def build_sprites(crop=None):
    """Render the fixed-size circular fire-on-log orb frames from the GIF."""
    if crop is None:
        crop = crop_box(*read_nudge())
    im = Image.open(SRC)
    mask = Image.new("L", (D, D), 0)
    core = int(D * 0.16)
    ImageDraw.Draw(mask).ellipse([core, core, D - core, D - core], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(int(D * 0.11)))
    sprites = []
    for frame in ImageSequence.Iterator(im):
        fr = frame.convert("RGBA").crop(crop).resize((D, D), Image.LANCZOS)
        fr.putalpha(ImageChops.multiply(fr.getchannel("A"), mask))
        sprites.append(fr)
    if FRAME_RANGE is not None:
        lo, hi = FRAME_RANGE
        sprites = sprites[lo:hi + 1]
    return smooth_loop(reorder_for_loop(sprites))


def smooth_loop(frames):
    """Soften only the hard-cut transitions by inserting blended in-between
    frames where needed.

    Some GIFs contain a content discontinuity (e.g. a reset frame) that reads as
    a visible jump no matter where the loop seam is placed. For each adjacent
    pair (cyclically) whose visual difference is well above the median, we insert
    one or more cross-faded midpoint frames so the cut is split into smaller,
    unnoticeable steps. Normal transitions are left untouched, so the flame keeps
    its native crispness everywhere except the few frames that actually need it.
    """
    n = len(frames)
    if n < 3:
        return frames

    def fdiff(a, b):
        d = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
        return sum(ImageStat.Stat(d, a.getchannel("A")).rms) / 3

    diffs = [fdiff(frames[i], frames[(i + 1) % n]) for i in range(n)]
    diffs.sort()  # for median without mutating original order
    med = diffs[len(diffs) // 2]
    diffs = [fdiff(frames[i], frames[(i + 1) % n]) for i in range(n)]

    out = []
    for i in range(n):
        a, b = frames[i], frames[(i + 1) % n]
        out.append(a)
        # number of blended frames that splits this step into ~median-sized ones
        extra = min(3, max(0, round(diffs[i] / med) - 1))
        for k in range(1, extra + 1):
            out.append(Image.blend(a, b, k / (extra + 1)))
    return out


def reorder_for_loop(frames):
    """Rotate the sequence so its loop seam is the smoothest adjacent pair.

    The GIF plays forward only (so the rising flame never appears to fall). Its
    native wrap (last frame -> first frame) can be a hard cut; rotating the
    cyclic sequence doesn't change any motion, it only moves which adjacent pair
    becomes the loop seam. We pick the pair with the smallest visual difference,
    so the wrap is the least noticeable transition in the whole loop.
    """
    n = len(frames)
    if not LOOP_ROTATE or n < 3:
        return frames

    def fdiff(a, b):
        d = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
        s = ImageStat.Stat(d, a.getchannel("A"))
        return sum(s.rms) / 3

    diffs = [fdiff(frames[i], frames[(i + 1) % n]) for i in range(n)]
    seam = min(range(n), key=lambda i: diffs[i])
    start = (seam + 1) % n
    return [frames[(start + k) % n] for k in range(n)]


def interp_sprites(base):
    """Cross-fade between consecutive keyframes (cyclically) for smooth motion.

    All keyframes share the same circular alpha mask, so blending preserves the
    orb shape and only morphs the flame's colour/brightness.
    """
    if INTERP <= 1 or len(base) < 2:
        return base
    n = len(base)
    out = []
    for i in range(n):
        a, b = base[i], base[(i + 1) % n]
        for s in range(INTERP):
            out.append(Image.blend(a, b, s / INTERP))
    return out


def ensure_pane_frames(pw, ph):
    """Cached frame paths for a pane of (pw x ph) points; render on first use.

    The current nudge offset is part of the cache key so that changing it writes
    new files at new paths, which forces iTerm2 to reload (it caches by path).
    """
    dx, dy = read_nudge()
    key = f"{pw}x{ph}_{dx}_{dy}"
    if key in _CACHE:
        return _CACHE[key]
    out = os.path.join(CACHE, key)
    os.makedirs(out, exist_ok=True)
    W, H = pw * SS, ph * SS
    x = W - D - MARGIN
    bob = BOB_AMP_PT * SS
    n = len(_SPRITES)
    paths = []
    for idx, sprite in enumerate(_SPRITES):
        # gentle sinusoidal bob over one full loop
        y = MARGIN + bob + round(bob * math.sin(2 * math.pi * idx / n))
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        canvas.alpha_composite(sprite, (x, y))
        p = os.path.join(out, f"frame{idx:02d}.png")
        canvas.save(p)
        paths.append(p)
    _CACHE[key] = paths
    return paths


async def apply_image(session, path, mode=iterm2.BackgroundImageMode.STRETCH):
    change = iterm2.LocalWriteOnlyProfile()
    change.set_background_image_mode(mode)
    change.set_background_image_location(path)
    await session.async_set_profile_properties(change)


async def clear_image(session):
    change = iterm2.LocalWriteOnlyProfile()
    change.set_background_image_location("")
    await session.async_set_profile_properties(change)


def focused_session(app):
    """The iTerm2 session that currently has keyboard focus (or None)."""
    win = app.current_terminal_window
    if win is None:
        return None
    tab = win.current_tab
    if tab is None:
        return None
    return tab.current_session


def pane_size(session):
    """Focused pane size in points, or None."""
    f = getattr(session, "frame", None)
    if f is None:
        return None
    w, h = int(round(f.size.width)), int(round(f.size.height))
    if w <= 0 or h <= 0:
        return None
    return (w, h)


async def clear_all(app):
    for win in app.terminal_windows:
        for tab in win.tabs:
            for sess in tab.all_sessions:
                try:
                    await clear_image(sess)
                except Exception:
                    pass


async def main(connection):
    app = await iterm2.async_get_app(connection)

    if MODE == "clear":
        await clear_all(app)
        print("cleared all sessions")
        return

    if MODE == "test":
        sess = focused_session(app)
        ps = pane_size(sess) if sess else None
        if sess is not None and ps is not None:
            await apply_image(sess, ensure_pane_frames(*ps)[2])
            print("set frame on focused pane", ps)
        else:
            print("no focused session/size")
        return

    if MODE == "dance":
        global _SPRITES, _CACHE
        delay = 1.0 / FPS
        deadline = time.time() + MINUTES * 60
        try:
            with open(STATE_FILE) as fh:
                i = int(fh.read().strip())
        except Exception:
            i = 0
        await app.async_refresh_focus()
        target = focused_session(app)
        last_nudge = read_nudge()
        last_log = 0.0
        last_log_i = i
        print(f"dance start: src={os.path.basename(SRC)} fps={FPS:g} "
              f"frames={len(_SPRITES)} bob={BOB_AMP_PT}pt", flush=True)
        dropped = False
        while time.time() < deadline and not os.path.exists(STOP_FILE):
            if i % 5 == 0:
                nudge = read_nudge()
                if nudge != last_nudge:
                    _SPRITES = build_sprites(crop_box(*nudge))
                    _CACHE.clear()
                    last_nudge = nudge
                    print(f"nudge applied: {nudge[0]} {nudge[1]}", flush=True)
            current = focused_session(app)
            try:
                if current is not None and (
                        target is None or current.session_id != target.session_id):
                    if target is not None:
                        try:
                            await clear_image(target)
                        except Exception:
                            pass
                    target = current
                if target is not None:
                    ps = pane_size(target)
                    if ps is not None:
                        paths = ensure_pane_frames(*ps)
                        await apply_image(target, paths[i % len(paths)])
                        now = time.time()
                        if now - last_log >= 5.0:
                            actual = (i - last_log_i) / (now - last_log) if last_log else 0.0
                            print(f"{time.strftime('%H:%M:%S')}  pane={ps[0]}x{ps[1]}  "
                                  f"frame={i % len(paths):02d}/{len(paths)}  "
                                  f"actual={actual:4.1f}fps  nudge={nudge[0]},{nudge[1]}  "
                                  f"fire crackling \U0001f525", flush=True)
                            last_log = now
                            last_log_i = i
            except Exception as e:
                print("apply failed (connection drop?):", e, flush=True)
                dropped = True
                break
            i += 1
            if i % 10 == 0:
                try:
                    with open(STATE_FILE, "w") as fh:
                        fh.write(str(i))
                except Exception:
                    pass
            await asyncio.sleep(delay)
        if dropped:
            print("connection dropped; supervisor will resume", flush=True)
        else:
            try:
                await clear_all(app)
            except Exception:
                pass
            print("dance ended, cleared", flush=True)
        return


def do_nudge():
    """Adjust NUDGE_FILE from CLI args; a running 'dance' picks it up live.

    Usage: fire_on_log.py nudge {left|right|up|down} [step]
           fire_on_log.py nudge set DX DY
           fire_on_log.py nudge reset
    """
    args = sys.argv[2:]
    cmd = args[0] if args else ""
    dx, dy = read_nudge()
    if cmd in NUDGE_DIRS:
        step = NUDGE_STEP
        if len(args) > 1:
            try:
                step = int(args[1])
            except ValueError:
                pass
        ddx, ddy = NUDGE_DIRS[cmd]
        dx += ddx * step
        dy += ddy * step
    elif cmd == "set" and len(args) >= 3:
        dx, dy = int(args[1]), int(args[2])
    elif cmd == "reset":
        dx, dy = 0, 0
    else:
        print("usage: nudge {left|right|up|down [step]|set DX DY|reset}")
        return
    with open(NUDGE_FILE, "w") as fh:
        fh.write(f"{dx} {dy}")
    print(f"nudge -> {dx} {dy}")


if __name__ == "__main__":
    if MODE == "nudge":
        do_nudge()
        sys.exit(0)
    if MODE in ("dance", "test"):
        shutil.rmtree(CACHE, ignore_errors=True)
        os.makedirs(CACHE, exist_ok=True)
        _SPRITES = build_sprites()
    iterm2.run_until_complete(main)
