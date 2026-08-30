#!/usr/bin/env python3
"""Find CCTV cameras near a point or matching a name.

Usage:
  ./pick_cameras.py -7.9420 112.6340        # 10 nearest to a lat,lng
  ./pick_cameras.py -7.9420 112.6340 -n 20  # 20 nearest
  ./pick_cameras.py --search dinoyo          # by name/address substring
"""
import argparse, csv, math, sys
from pathlib import Path

DATA = Path(__file__).parent / "data" / "cameras.csv"


def haversine(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load():
    with open(DATA, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lat", nargs="?", type=float)
    ap.add_argument("lng", nargs="?", type=float)
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--search", help="substring in name/address instead of lat,lng")
    a = ap.parse_args()

    cams = load()
    if a.search:
        q = a.search.lower()
        hits = [c for c in cams if q in c["name"].lower() or q in c["address"].lower()]
        for c in hits:
            print(f"{c['name']}\n    {c['address']}  @({c['latitude']},{c['longitude']}) id={c['stream_id']}")
        print(f"-- {len(hits)} matches", file=sys.stderr)
        return

    if a.lat is None or a.lng is None:
        ap.error("give lat lng, or --search")

    ranked = sorted(cams, key=lambda c: haversine(a.lat, a.lng, float(c["latitude"]), float(c["longitude"])))
    for c in ranked[: a.n]:
        d = haversine(a.lat, a.lng, float(c["latitude"]), float(c["longitude"]))
        print(f"{d:7.0f} m  {c['name']:<45}  kec={c['kecamatan_id']}  id={c['stream_id']}")
        print(f"          {c['address']}")


if __name__ == "__main__":
    main()
