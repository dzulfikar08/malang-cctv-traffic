# malang-cctv-traffic

Low-cost road-congestion monitoring built on the public CCTV portal of
Kota Malang ([cctv.malangkota.go.id](https://cctv.malangkota.go.id/sebaran-cctv),
published by Diskomininfo Kota Malang).

**The idea:** rush hour repeats, so you don't need AI prediction or a 24/7
server — you need a few weeks of sparse samples. Every 10–15 minutes this repo's
scheduled workflow fetches one 2-second HLS segment per camera and measures
motion energy (mean absolute difference between downscaled consecutive frames
via ffmpeg). Rows go into a Cloudflare D1 database. After a few weeks an
hour × weekday heatmap answers "which hour is safe to go out?".

- `sampler.py` — the collector (Python stdlib + ffmpeg only)
- `data/cameras_selected.csv` — the 17 monitored cameras (all public street cameras)
- `.github/workflows/sample.yml` — the scheduled collector
- `.github/workflows/probe.yml` — manual connectivity check

No personal data: no home locations, no secrets in the repo (the ingest key is
a GitHub Secret). The portal is fetched politely — one playlist + one tiny
probe per camera per round.

Related pieces (not in this repo): a Cloudflare Worker that stores/query the
samples, and a local systemd timer that also samples while a laptop is awake.
