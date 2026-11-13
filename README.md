# yt-agent — operator runbook

AI pipeline that turns a **PDF / text / audio / video** source into a finished
9:16 YouTube Short (voiceover + captions + AI visuals), fully local on the Jetson
AGX Orin, behind a human approval gate. Full design/history is in
[`yt-agent-context.md`](../yt/yt-agent-context.md).

Reach this machine on the LAN as **`orinx.local`** (mDNS/avahi) — the IP can change.

---

## 0. After a reboot (or power cut) — bring the box up

Run these from `~/yt-agent`. Steps 1–2 are only needed if the NVMe isn't mounted.

```bash
# 1. Is the SSD present + mounted? Expect a ~931G exfat at /mnt/nvme.
lsblk | grep -E 'sd|nvme'
#    If /mnt/nvme is missing but a disk shows -> just mount it:
sudo ./scripts/nvme_mount.sh
#    If NO disk shows at all -> physically REPLUG the SSD into a USB-A port
#    (NOT the Type-C port — it won't enumerate there), wait 5s, re-run lsblk.

# 2. One-shot recovery after a power cut (mounts + resumes any LTX download):
sudo ./scripts/powercut_recover.sh

# 3. (Optional, throughput only) set max power — REQUIRES A REBOOT to take effect:
sudo nvpmodel -m 0 && sudo jetson_clocks     # MAXN; roughly halves GPU gen time
```

You do **not** need to start anything by hand for normal use — the launchers below
start their own dependencies (Ollama, ComfyUI).

---

## 1. Create a Short — the UI way (easiest)

```bash
cd ~/yt-agent
./scripts/studio.sh
```

- Starts **Ollama** + **ComfyUI**, then opens **Studio** at `http://orinx.local:7860`
  (or `http://<orin-ip>:7860`). Open it in a browser on any LAN machine.
- Flow in the UI:
  1. **Source** — type a path or upload a `.pdf` / `.txt` / audio / video file.
  2. **Draft** — generates the concept + script.
  3. **Refine** — reword by prompting Qwen, or hand-edit the script.
  4. **Visual** dropdown — `auto` (AI image if ComfyUI is up, else chart) / `image` / `chart` / `none`.
  5. **Generate** — runs voice → captions → visual → assemble, streaming progress.
  6. **Preview with sound** inline when it's done.
- Output + work dirs are UI fields; they default to the NVMe (keeps the small eMMC free).

Stop it with `Ctrl-C` in that terminal. To keep it alive across SSH drops, run it
inside `screen -S studio` (detach with `Ctrl-a d`, reattach with `screen -r studio`).

---

## 2. Create a Short — the terminal way

```bash
cd ~/yt-agent

# One finished Short from a PDF (default ~short length):
./run.sh data/pdfs/your-book.pdf

# Pick a length (short | 60s | 90 | 3min | 5min) and put artifacts on the NVMe:
./run.sh data/pdfs/your-book.pdf 3min --output /mnt/nvme/yt-agent/output \
                                      --work   /mnt/nvme/yt-agent/work

# From a video or audio file (it's transcribed, re-expressed in original words,
# and rebuilt with OUR visuals — not a copy of the source footage):
./run.sh ~/clip.mp4 90 --output /mnt/nvme/yt-agent/output
```

Finished files land in the output dir as:
`short-<timestamp>.mp4` + `short-<timestamp>.metadata.json`.

**Notes**
- AI image/video backgrounds need ComfyUI running (`./scripts/comfy.sh start`);
  without it the pipeline falls back to charts/gradients automatically.
- Long jobs: run inside `screen -S run` so an SSH/Wi-Fi drop doesn't kill them.

### Watch the result (with sound)
```bash
./scripts/preview.sh /mnt/nvme/yt-agent/output      # serves on :8000
# then open  http://orinx.local:8000  and click a video
```
(Use this instead of VNC — VNC carries no audio.)

---

## 3. Helper services (start/stop as needed)

```bash
./scripts/comfy.sh  start|stop|status     # ComfyUI (SDXL images + LTX clips) on :8188
./scripts/vnc.sh    start|stop|status     # TigerVNC+XFCE desktop on :5901 (LAN)
./scripts/preview.sh [dir] [port]         # LAN preview-with-sound (default data/output :8000)
ollama list                               # confirm the LLM (qwen2.5:14b) is present
```

---

## 4. Publish to YouTube (Phase 3 — approval-gated)

**One-time setup:** install the Google libs and drop your OAuth credential in place.
```bash
.venv/bin/pip install -r publish/requirements.txt
# Create an OAuth 2.0 **Desktop app** client in Google Cloud Console with the
# "YouTube Data API v3" enabled, download the JSON, then:
mkdir -p data/secrets && cp ~/Downloads/client_secret*.json data/secrets/client_secret.json
```

**Every upload** (gate is ON — nothing uploads without `--yes`):
```bash
# Dry run: prints the title/description/tags/privacy plan, uploads nothing:
python3 -m publish.publish /mnt/nvme/yt-agent/output/short-<ts>.mp4

# Approve + upload (defaults to PRIVATE; promote to public in YouTube Studio once happy):
python3 -m publish.publish /mnt/nvme/yt-agent/output/short-<ts>.mp4 --yes
python3 -m publish.publish /mnt/nvme/yt-agent/output/short-<ts>.mp4 --yes --privacy unlisted
```
First upload opens a Google consent flow and caches `data/secrets/token.json`.
Capped at **6 uploads/day** (YouTube API quota); the count is tracked locally.

---

## 5. Resuming a Claude session on this box

```bash
screen -S claude          # so it survives SSH/Wi-Fi/IP drops
claude --continue         # resume the previous conversation
# then say: "Read yt-agent-context.md and continue from where we left off."
```

---

## Cheat sheet

| I want to… | Command |
|---|---|
| Make a Short in the browser | `./scripts/studio.sh` → `http://orinx.local:7860` |
| Make a Short from a PDF (terminal) | `./run.sh data/pdfs/book.pdf 3min --output /mnt/nvme/yt-agent/output` |
| Make a Short from a video | `./run.sh ~/clip.mp4 90 --output /mnt/nvme/yt-agent/output` |
| Watch output with sound | `./scripts/preview.sh /mnt/nvme/yt-agent/output` → `:8000` |
| Start/stop ComfyUI | `./scripts/comfy.sh start` / `stop` |
| After a power cut | `lsblk` → replug SSD (USB-A) if absent → `sudo ./scripts/powercut_recover.sh` |
| Upload (dry run) | `python3 -m publish.publish <file>.mp4` |
| Upload (for real) | `python3 -m publish.publish <file>.mp4 --yes` |
