#!/usr/bin/env python3
"""
Baixa a partir de um LINK (Twitch, YouTube, Kick...).

  baixar.py audio  <url> --job J [--inicio h:mm:ss] [--fim h:mm:ss]
      -> jobs/J/meta.json (título, canal, duração, link do VOD, offset) e jobs/J/audio.*  (só o áudio)

  baixar.py trecho <url> <inicio_s> <fim_s> <saida.mp4>
      -> baixa só aquele pedaço do vídeo (até 1080p), cortado no tempo exato
"""
import argparse, glob, json, os, re, subprocess, sys

import yt_dlp


def seg(v):
    if v in (None, ""):
        return None
    p = [float(x) for x in str(v).split(":")]
    t = 0.0
    for x in p:
        t = t * 60 + x
    return t


def hms(t):
    t = int(t)
    return f"{t//3600}:{t%3600//60:02d}:{t%60:02d}"


def plataforma(url):
    for p in ("twitch", "youtube", "youtu.be", "kick"):
        if p in url:
            return "youtube" if p == "youtu.be" else p
    return "outra"


def info(url, flat=False):
    o = {"quiet": True, "skip_download": True, "extract_flat": "in_playlist" if flat else False}
    with yt_dlp.YoutubeDL(o) as y:
        return y.extract_info(url, download=False)


def resolver(url):
    """Canal da Twitch -> VOD mais recente (inclui a live em andamento, que já vira VOD)."""
    url = url.strip()
    m = re.match(r"https?://(www\.|m\.)?twitch\.tv/([A-Za-z0-9_]+)/?(\?.*)?$", url)
    if m and m.group(2).lower() not in ("videos", "directory"):
        canal = m.group(2)
        lista = info(f"https://www.twitch.tv/{canal}/videos?filter=archives&sort=time", flat=True)
        ents = [e for e in (lista.get("entries") or []) if e]
        if not ents:
            sys.exit(f"ERRO: o canal {canal} não tem VODs públicos (o streamer pode ter desativado).")
        vid = ents[0].get("url") or f"https://www.twitch.tv/videos/{ents[0]['id'].lstrip('v')}"
        print(f"canal {canal} -> VOD mais recente: {vid}", flush=True)
        return vid
    return url


def cmd_audio(a):
    pasta = os.path.join("jobs", a.job)
    os.makedirs(pasta, exist_ok=True)
    url = resolver(a.url)
    i = info(url)
    ao_vivo = bool(i.get("is_live") or i.get("live_status") == "is_live")
    if ao_vivo:
        if plataforma(url) != "twitch":
            sys.exit("ERRO: essa live ainda está no ar. No YouTube/Kick, mande o link depois que ela terminar "
                     "(vira VOD). Na Twitch funciona durante a live, mandando o link do canal.")
    ini, fim = seg(a.inicio), seg(a.fim)
    meta = {"url_original": a.url, "url": url, "titulo": i.get("title"), "canal": i.get("uploader") or i.get("channel"),
            "duracao": i.get("duration"), "plataforma": plataforma(url), "ao_vivo_ainda": ao_vivo,
            "offset": ini or 0.0}
    with open(os.path.join(pasta, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(json.dumps(meta, ensure_ascii=False), flush=True)

    cmd = ["yt-dlp", "-q", "--no-warnings", "-N", "8", "-f", "ba/Audio_Only/audio_only/worst",
           "-o", os.path.join(pasta, "audio.%(ext)s"), url]
    if ini is not None or fim is not None:
        cmd[1:1] = ["--download-sections", f"*{hms(ini or 0)}-{hms(fim) if fim else 'inf'}"]
    subprocess.run(cmd, check=True)
    arq = glob.glob(os.path.join(pasta, "audio.*"))
    print("baixado:", arq, flush=True)


def cmd_trecho(a):
    ini, fim = float(a.inicio), float(a.fim)
    cmd = ["yt-dlp", "-q", "--no-warnings", "-N", "8",
           "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
           "--download-sections", f"*{ini:.2f}-{fim:.2f}", "--force-keyframes-at-cuts",
           "--merge-output-format", "mp4", "-o", a.saida, a.url]
    if a.url.startswith("file://"):  # arquivo local (testes): corta direto com ffmpeg
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ini:.2f}", "-to", f"{fim:.2f}", "-i", a.url[7:],
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "aac", a.saida], check=True)
        return
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="modo", required=True)
    p1 = sp.add_parser("audio"); p1.add_argument("url"); p1.add_argument("--job", required=True)
    p1.add_argument("--inicio", default=""); p1.add_argument("--fim", default="")
    p2 = sp.add_parser("trecho"); p2.add_argument("url"); p2.add_argument("inicio"); p2.add_argument("fim"); p2.add_argument("saida")
    a = ap.parse_args()
    cmd_audio(a) if a.modo == "audio" else cmd_trecho(a)


if __name__ == "__main__":
    main()
