#!/usr/bin/env python3
"""Sample road congestion from Malang public CCTV.

One round = for each camera in data/cameras_selected.csv:
  GET the live HLS playlist, download the newest finished 2s segment,
  measure motion energy (mean abs frame difference) with ffmpeg,
  append one CSV row to data/samples.csv.

Stdlib + ffmpeg only. Zero Python dependencies.

Usage:
  ./sampler.py             # sample all cameras, append to data/samples.csv
  ./sampler.py --live      # same fetch, but print a "how is it right now" ranking
  ./sampler.py --live -r cafe
"""
import argparse, csv, fcntl, io, json, math, os, re, subprocess, sys, time
import urllib.request
import urllib.error
import http.cookiejar
import ssl
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = "https://cctv.malangkota.go.id"
PAGE = f"{BASE}/sebaran-cctv"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TZ = ZoneInfo("Asia/Jakarta")
DATA = Path(__file__).parent / "data"
SAMPLES = DATA / "samples.csv"
ERRORS = DATA / "errors.log"
CAMERAS = DATA / "cameras_selected.csv"
POLITENESS_S = 0.5          # between cameras
MAX_SEGMENT_BYTES = 1_500_000
# Motion energy of an empty dark street is not zero, and night scenes move
# less light around, so scores are only compared within the same camera and
# hour-of-day -- which is exactly how report.py aggregates them.
MOTION_FILTER = "scale=160:90,format=gray,tblend=all_mode=difference,signalstats,metadata=mode=print:key=lavfi.signalstats.YAVG"
YAVG_RE = re.compile(r"YAVG=([\d.]+)")

CTX = ssl._create_unverified_context()  # portal serves an incomplete cert chain


def log_err(msg):
    with open(ERRORS, "a") as f:
        f.write(f"{datetime.now(TZ).isoformat(timespec='seconds')} {msg}\n")


def make_opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar), urllib.request.HTTPSHandler(context=CTX))


def fetch(opener, url, timeout=20, max_bytes=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": PAGE})
    with opener.open(req, timeout=timeout) as r:
        blob = r.read(max_bytes) if max_bytes else r.read()
    return blob


def warm_up(opener):
    """The WAF 403s every path until the session has NANCY_TOKEN cookies."""
    fetch(opener, PAGE, timeout=25)


def newest_segment_url(opener, stream_id):
    pl = fetch(opener, f"{BASE}/cctv-stream/streams/{stream_id}.m3u8", timeout=15).decode("utf-8", "replace")
    segs = [l.strip() for l in pl.splitlines() if l.strip() and not l.startswith("#")]
    if not segs:
        raise RuntimeError("empty playlist")
    seg = segs[-2] if len(segs) >= 2 else segs[-1]   # [-1] may still be recording
    return seg if seg.startswith("http") else f"{BASE}/cctv-stream/streams/{seg}"


def motion_energy(seg_bytes):
    """Mean abs difference between consecutive downscaled frames (0..255)."""
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "info", "-i", "pipe:0",
         "-vf", MOTION_FILTER, "-f", "null", "-"],
        input=seg_bytes, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    vals = [float(m) for m in YAVG_RE.findall(p.stderr.decode("utf-8", "replace"))]
    if not vals:
        raise RuntimeError("ffmpeg produced no motion values (exit %d)" % p.returncode)
    return sum(vals) / len(vals), len(vals)


def load_cameras():
    with open(CAMERAS, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def sample_round(cameras, opener, delay=POLITENESS_S):
    rows = []
    for i, cam in enumerate(cameras):
        sid, name, role = cam["stream_id"], cam["name"], cam["role"]
        row = {"ts": datetime.now(TZ).isoformat(timespec="seconds"),
               "camera_id": sid, "name": name, "role": role,
               "bytes": "", "motion": "", "frames": ""}
        try:
            url = newest_segment_url(opener, sid)
            seg = fetch(opener, url, timeout=25, max_bytes=MAX_SEGMENT_BYTES)
            row["bytes"] = len(seg)
            row["motion"], row["frames"] = [round(v, 3) for v in motion_energy(seg)]
            print(f"  ok  {name:<45} motion={row['motion']:6.2f}  {row['bytes']} B")
        except Exception as e:
            row["frames"] = -1
            print(f"  ERR {name:<45} {e}", file=sys.stderr)
            log_err(f"{sid} {name}: {e}")
        rows.append(row)
        if i < len(cameras) - 1:
            time.sleep(delay)
    return rows


def append_rows(rows):
    SAMPLES.parent.mkdir(exist_ok=True)
    new_file = not SAMPLES.exists()
    with open(SAMPLES, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ts", "camera_id", "name", "role", "bytes", "motion", "frames"])
        if new_file:
            w.writeheader()
        w.writerows(rows)


def show_live(rows):
    valid = [r for r in rows if r["motion"] != ""]
    if not valid:
        print("no live data")
        return
    lo = min(r["motion"] for r in valid)
    hi = max(r["motion"] for r in valid)
    print(f"\n{'camera':<46} {'motion':>7}  bar (relative, same moment)")
    for r in sorted(valid, key=lambda r: r["motion"]):
        frac = (r["motion"] - lo) / (hi - lo) if hi > lo else 0.5
        bar = "#" * max(1, round(frac * 30))
        print(f"{r['name']:<46} {r['motion']:>7.2f}  {bar}")
    print("\nlower = calmer right now (relative across cameras this instant)")


def ingest(rows):
    """Optional: push this round to the collector API (used by GitHub Actions).

    Enabled when INGEST_URL and INGEST_KEY are set in the environment.
    """
    url, key = os.environ.get("INGEST_URL"), os.environ.get("INGEST_KEY")
    if not (url and key):
        return
    req = urllib.request.Request(
        url, data=json.dumps({"rows": rows}).encode(),
        headers={"content-type": "application/json", "x-key": key})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("ingested:", r.read().decode()[:200])
    except Exception as e:
        print(f"ingest failed: {e}", file=sys.stderr)
        log_err(f"ingest: {e}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="print current ranking instead of recording")
    ap.add_argument("-r", "--role", help="only cameras with this role (e.g. cafe, dest1+2)")
    a = ap.parse_args()

    cameras = load_cameras()
    if a.role:
        cameras = [c for c in cameras if c["role"] == a.role]
    if not cameras:
        sys.exit("no cameras matched")

    opener = make_opener()
    warm_up(opener)
    t0 = time.time()
    rows = sample_round(cameras, opener)
    ok = sum(1 for r in rows if r["motion"] != "")
    print(f"\n{ok}/{len(rows)} cameras in {time.time()-t0:.0f}s")

    if a.live:
        show_live(rows)
    else:
        with open(SAMPLES.parent / ".sampler.lock", "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            append_rows(rows)
        print(f"appended -> {SAMPLES}")
        ingest(rows)


if __name__ == "__main__":
    main()
