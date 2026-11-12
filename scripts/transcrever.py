#!/usr/bin/env python3
"""
Transcreve uma live (vídeo ou áudio) localmente, sem API paga.

Saídas (na pasta --saida):
  transcricao.json  -> [{"start": s, "end": s, "text": "...", "energia": 0-1}]
  transcricao.txt   -> versão compacta para leitura: [mm:ss-mm:ss] texto  (!! = grito/pico de volume)
  picos.txt         -> momentos de volume alto SEM fala reconhecida (explosões, risadas, gritos)

Uso:
  python3 transcrever.py live.mp4 --saida trabalho/ [--modelos DIR] [--idioma pt]
"""
import argparse, json, os, subprocess, sys, time
import numpy as np

SR = 16000


def fmt(t):
    t = int(t)
    h, m, s = t // 3600, (t % 3600) // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def extrair_audio(video, wav):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-vn", "-ac", "1",
                    "-ar", str(SR), "-c:a", "pcm_s16le", wav], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entrada")
    ap.add_argument("--saida", default="trabalho")
    ap.add_argument("--modelos", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models"))
    ap.add_argument("--idioma", default="pt")
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--modelo", default="small", help="small (melhor) ou base (mais rápido)")
    ap.add_argument("--offset", type=float, default=0.0, help="soma este valor (s) a todos os tempos")
    a = ap.parse_args()

    import sherpa_onnx
    import soundfile as sf

    os.makedirs(a.saida, exist_ok=True)
    wav = os.path.join(a.saida, "audio16k.wav")
    t0 = time.time()
    print("[1/3] extraindo áudio...", flush=True)
    extrair_audio(a.entrada, wav)
    audio, _ = sf.read(wav, dtype="float32")
    dur = len(audio) / SR
    print(f"      duração: {fmt(dur)}", flush=True)

    # --- energia por 0,5 s (para achar gritos / explosões) ---
    hop = SR // 2
    n = len(audio) // hop
    rms = np.sqrt(np.mean(audio[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    ref_baixo, ref_alto = np.percentile(db, 50), np.percentile(db, 99.5)
    energia = np.clip((db - ref_baixo) / max(ref_alto - ref_baixo, 1e-6), 0, 1)
    limiar_pico = np.percentile(energia, 97)

    def energia_em(s, e):
        i, j = int(s * 2), max(int(e * 2), int(s * 2) + 1)
        return float(energia[i:j].max()) if i < len(energia) else 0.0

    # --- VAD: segmentos de fala ---
    print("[2/3] detectando trechos de fala...", flush=True)
    vcfg = sherpa_onnx.VadModelConfig()
    vcfg.silero_vad.model = os.path.join(a.modelos, "silero_vad.onnx")
    vcfg.silero_vad.min_silence_duration = 0.35
    vcfg.silero_vad.min_speech_duration = 0.3
    vcfg.silero_vad.max_speech_duration = 12
    vcfg.silero_vad.threshold = 0.45
    vcfg.sample_rate = SR
    vad = sherpa_onnx.VoiceActivityDetector(vcfg, buffer_size_in_seconds=60)
    win = vcfg.silero_vad.window_size
    segs = []
    for k in range(0, len(audio), win):
        vad.accept_waveform(audio[k:k + win])
        while not vad.empty():
            segs.append((vad.front.start / SR, np.array(vad.front.samples, dtype=np.float32)))
            vad.pop()
    vad.flush()
    while not vad.empty():
        segs.append((vad.front.start / SR, np.array(vad.front.samples, dtype=np.float32)))
        vad.pop()
    print(f"      {len(segs)} trechos de fala", flush=True)

    # --- Whisper ---
    m = a.modelo
    print(f"[3/3] transcrevendo (whisper-{m})...", flush=True)
    md = os.path.join(a.modelos, f"sherpa-onnx-whisper-{m}")
    rec = sherpa_onnx.OfflineRecognizer.from_whisper(
        encoder=os.path.join(md, f"{m}-encoder.int8.onnx"),
        decoder=os.path.join(md, f"{m}-decoder.int8.onnx"),
        tokens=os.path.join(md, f"{m}-tokens.txt"),
        language=a.idioma, task="transcribe", num_threads=a.threads,
        tail_paddings=800)

    out = []
    ultimo_log = time.time()
    # frases que o Whisper "alucina" em trechos de música/barulho
    lixo = {"", ".", "...", "Legendas pela comunidade Amara.org"}
    for idx, (st, samples) in enumerate(segs):
        s = rec.create_stream()
        s.accept_waveform(SR, samples)
        rec.decode_stream(s)
        txt = s.result.text.strip()
        en = st + len(samples) / SR
        if txt in lixo or "Amara.org" in txt:
            continue
        # repetição degenerada (ex.: "não não não não não ...") -> encurta
        palavras = txt.split()
        if len(palavras) > 12 and len(set(w.lower() for w in palavras)) <= 3:
            txt = " ".join(palavras[:6]) + "..."
        out.append({"start": round(st, 2), "end": round(en, 2), "text": txt,
                    "energia": round(energia_em(st, en), 2)})
        if time.time() - ultimo_log > 30:
            print(f"      {fmt(en)} / {fmt(dur)}  ({(idx+1)*100//len(segs)}%)", flush=True)
            ultimo_log = time.time()

    off = a.offset
    if off:
        for o in out:
            o["start"] = round(o["start"] + off, 2); o["end"] = round(o["end"] + off, 2)
    with open(os.path.join(a.saida, "transcricao.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    with open(os.path.join(a.saida, "transcricao.txt"), "w", encoding="utf-8") as f:
        for o in out:
            mark = "!! " if o["energia"] >= limiar_pico else ""
            f.write(f"[{fmt(o['start'])}-{fmt(o['end'])}] {mark}{o['text']}\n")

    # picos de volume fora da fala reconhecida
    falado = np.zeros(len(energia), bool)
    for o in out:
        falado[int((o["start"] - off) * 2):int((o["end"] - off) * 2) + 1] = True
    picos, i = [], 0
    while i < len(energia):
        if energia[i] >= limiar_pico and not falado[i]:
            j = i
            while j < len(energia) and energia[j] >= limiar_pico * 0.85:
                j += 1
            picos.append((i / 2, j / 2, float(energia[i:j].max())))
            i = j + 4
        else:
            i += 1
    with open(os.path.join(a.saida, "picos.txt"), "w", encoding="utf-8") as f:
        for s, e, v in picos:
            f.write(f"[{fmt(s+off)}-{fmt(e+off)}] volume {v:.2f}\n")

    os.remove(wav)
    print(f"pronto em {fmt(time.time()-t0)}: {len(out)} falas, {len(picos)} picos sem fala", flush=True)


if __name__ == "__main__":
    main()
