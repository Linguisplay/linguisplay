"""One-time audio asset generation for the immersive layer (run LOCALLY, then upload).

BGM  — one loop per mood in engine/scene.py's taxonomy, generated with MusicGen-small
       (facebook/musicgen-small via transformers; ~2GB download on first run, CPU ok).
SFX  — the one-shot effects, synthesized procedurally with numpy DSP (no model needed;
       noise/tone shaping is plenty convincing for ambience one-shots).

Output: app/static/scene/bgm/<mood>.mp3 and app/static/scene/sfx/<stem>.mp3 — exactly
the paths play.html requests. Idempotent: existing files are skipped (--force regens).

Usage:  python gen_audio.py [bgm|sfx|all] [--force]
Upload: tar czf - -C app/static/scene . | ssh persona "tar xzf - -C /opt/linguisplay/apps/api/app/static/scene"
"""

import os
import sys

import numpy as np

SR = 32000  # MusicGen native rate; SFX rendered at the same for consistency

BGM_DIR = os.path.join("app", "static", "scene", "bgm")
SFX_DIR = os.path.join("app", "static", "scene", "sfx")

# mood → MusicGen prompt. Instrumental, loopable, understated — it sits UNDER text.
BGM_PROMPTS = {
    "daily":    "gentle lo-fi ambient background, soft piano and warm pads, calm, unobtrusive, loopable, no drums",
    "warm":     "warm tender ambient piano with soft strings, intimate and comforting, slow, loopable instrumental",
    "romantic": "soft romantic instrumental, delicate piano and light strings, wistful sweetness, slow tempo, loopable",
    "sad":      "melancholic sparse piano with distant strings, sorrowful and quiet, slow, loopable instrumental",
    "lonely":   "desolate minimal ambient, single distant piano notes with long reverb tail, empty and cold, loopable",
    "tense":    "tense suspenseful underscore, low pulsing drone with staccato string stabs, unsettling, loopable, no melody",
    "eerie":    "eerie horror ambience, dissonant drones, faint metallic scrapes, ghostly whispers of wind, dark and hollow",
}
BGM_SECONDS = 24


def _mp3(path: str, audio: np.ndarray, sr: int = SR) -> None:
    """float32 mono [-1,1] → mp3 file (lameenc, no ffmpeg dependency)."""
    import lameenc
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
    enc = lameenc.Encoder()
    enc.set_bit_rate(128)
    enc.set_in_sample_rate(sr)
    enc.set_channels(1)
    enc.set_quality(2)
    data = enc.encode(pcm.tobytes()) + enc.flush()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(bytes(data))
    print(f"  {path}  ({len(data)//1024} KB)")


def _fade(a: np.ndarray, ms: int = 400, sr: int = SR) -> np.ndarray:
    n = min(len(a), int(sr * ms / 1000))
    if n > 0:
        a[:n] *= np.linspace(0, 1, n)
        a[-n:] *= np.linspace(1, 0, n)
    return a


# ── BGM via MusicGen ──────────────────────────────────────────────────────────
def gen_bgm(force: bool = False) -> None:
    todo = {m: p for m, p in BGM_PROMPTS.items()
            if force or not os.path.exists(os.path.join(BGM_DIR, f"{m}.mp3"))}
    if not todo:
        print("bgm: all present, nothing to do")
        return
    print(f"bgm: generating {len(todo)} loops with MusicGen-small (CPU, ~minutes each)…")
    import torch
    from transformers import AutoProcessor, MusicgenForConditionalGeneration
    processor = AutoProcessor.from_pretrained("facebook/musicgen-small")
    model = MusicgenForConditionalGeneration.from_pretrained("facebook/musicgen-small")
    model.eval()
    # ~50 tokens/second of audio
    max_new = int(BGM_SECONDS * 50)
    for mood, prompt in todo.items():
        print(f"  [{mood}] {prompt[:60]}…")
        inputs = processor(text=[prompt], padding=True, return_tensors="pt")
        with torch.no_grad():
            out = model.generate(**inputs, do_sample=True, guidance_scale=3.0,
                                 max_new_tokens=max_new)
        audio = out[0, 0].cpu().numpy().astype(np.float32)
        audio = 0.6 * audio / (np.max(np.abs(audio)) + 1e-6)   # headroom under speech
        _mp3(os.path.join(BGM_DIR, f"{mood}.mp3"), _fade(audio, 800))


# ── SFX via numpy DSP ─────────────────────────────────────────────────────────
def _noise(n: int) -> np.ndarray:
    return np.random.default_rng(7).standard_normal(n).astype(np.float32)


def _lowpass(x: np.ndarray, alpha: float) -> np.ndarray:
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):          # simple one-pole; fine for offline synthesis
        acc += alpha * (v - acc)
        y[i] = acc
    return y


def _env(n: int, attack: float, decay: float) -> np.ndarray:
    a = int(n * attack)
    e = np.ones(n, dtype=np.float32)
    e[:a] = np.linspace(0, 1, a) if a else 1
    e[a:] = np.exp(-np.linspace(0, decay, n - a))
    return e


def _thump(freq: float, dur: float, sr: int = SR) -> np.ndarray:
    n = int(sr * dur)
    t = np.arange(n) / sr
    sweep = freq * np.exp(-t * 8)      # pitch drops as the hit decays
    return (np.sin(2 * np.pi * np.cumsum(sweep) / sr) * _env(n, 0.02, 6)).astype(np.float32)


def sfx_rain(sr=SR):
    x = _lowpass(_noise(sr * 6), 0.25) * 0.5
    mod = 1 + 0.15 * np.sin(2 * np.pi * 0.3 * np.arange(len(x)) / sr)
    return (x * mod).astype(np.float32)


def sfx_wind(sr=SR):
    x = _lowpass(_noise(sr * 6), 0.045)
    mod = 0.5 + 0.5 * np.abs(np.sin(2 * np.pi * 0.17 * np.arange(len(x)) / sr))
    return (2.2 * x * mod).astype(np.float32)


def sfx_waves(sr=SR):
    x = _lowpass(_noise(sr * 8), 0.12)
    swell = 0.25 + 0.75 * np.clip(np.sin(2 * np.pi * 0.11 * np.arange(len(x)) / sr), 0, 1)
    return (1.6 * x * swell).astype(np.float32)


def sfx_thunder(sr=SR):
    n = sr * 5
    x = _lowpass(_noise(n), 0.03) * _env(n, 0.02, 5)
    return (3.0 * x).astype(np.float32)


def sfx_heartbeat(sr=SR):
    beat = np.concatenate([_thump(55, 0.18), np.zeros(int(sr * 0.12), np.float32),
                           _thump(45, 0.22), np.zeros(int(sr * 0.55), np.float32)])
    return np.tile(beat, 4)


def sfx_knock(sr=SR):
    k = _thump(160, 0.09)
    gap = np.zeros(int(sr * 0.16), np.float32)
    return np.concatenate([k, gap, k, gap, k])


def sfx_door(sr=SR):
    n = int(sr * 0.7)
    creak_f = 300 + 180 * np.linspace(0, 1, n) + 40 * np.sin(np.linspace(0, 22, n))
    creak = 0.18 * np.sin(2 * np.pi * np.cumsum(creak_f) / sr) * _env(n, 0.1, 2.5)
    return np.concatenate([creak.astype(np.float32), _thump(90, 0.25)])


def sfx_footsteps(sr=SR):
    step = _thump(110, 0.12)
    out = []
    for i in range(6):
        out += [step * (0.7 + 0.3 * (i % 2)), np.zeros(int(sr * 0.42), np.float32)]
    return np.concatenate(out)


def sfx_buzz(sr=SR):
    n = sr * 3
    t = np.arange(n) / sr
    x = 0.25 * np.sign(np.sin(2 * np.pi * 50 * t)) * (0.7 + 0.3 * np.sin(2 * np.pi * 7 * t))
    return _lowpass(x.astype(np.float32), 0.35)


def sfx_ringtone(sr=SR):
    tone = lambda f, d: 0.3 * np.sin(2 * np.pi * f * np.arange(int(sr * d)) / sr).astype(np.float32)
    ring = (tone(880, 0.35) + tone(1180, 0.35)) * _env(int(sr * 0.35), 0.05, 1.2)
    gap = np.zeros(int(sr * 0.25), np.float32)
    burst = np.concatenate([ring, gap, ring, np.zeros(int(sr * 1.2), np.float32)])
    return np.tile(burst, 2)


def _reverb(x: np.ndarray, sr: int = SR, tail: float = 0.5) -> np.ndarray:
    """A handful of decaying early reflections + room to breathe — takes the synthetic
    dryness off percussive one-shots so they stop punching through the scene."""
    n = len(x) + int(sr * tail)
    y = np.zeros(n, np.float32)
    y[:len(x)] += x
    for delay, gain in ((0.029, 0.32), (0.047, 0.24), (0.071, 0.18), (0.109, 0.12), (0.151, 0.07)):
        i = int(sr * delay)
        y[i:i + len(x)] += gain * x
    return y


_PERCUSSIVE = {"knock", "door", "footsteps", "heartbeat"}

SFX_BUILDERS = {
    "rain": sfx_rain, "wind": sfx_wind, "waves": sfx_waves, "thunder": sfx_thunder,
    "heartbeat": sfx_heartbeat, "knock": sfx_knock, "door": sfx_door,
    "footsteps": sfx_footsteps, "buzz": sfx_buzz, "ringtone": sfx_ringtone,
}


def gen_sfx(force: bool = False) -> None:
    print("sfx: synthesizing one-shots…")
    for stem, fn in SFX_BUILDERS.items():
        path = os.path.join(SFX_DIR, f"{stem}.mp3")
        if not force and os.path.exists(path):
            print(f"  skip {stem} (exists)")
            continue
        audio = fn().astype(np.float32)
        if stem in _PERCUSSIVE:
            audio = _reverb(audio)
        peak = 0.6 if stem in _PERCUSSIVE else 0.75
        audio = peak * audio / (np.max(np.abs(audio)) + 1e-6)
        _mp3(path, _fade(audio, 120))


if __name__ == "__main__":
    what = next((a for a in sys.argv[1:] if not a.startswith("-")), "all")
    force = "--force" in sys.argv
    if what in ("sfx", "all"):
        gen_sfx(force)
    if what in ("bgm", "all"):
        gen_bgm(force)
    print("done.")
