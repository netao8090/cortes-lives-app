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
    try:
        with yt_dlp.YoutubeDL(o) as y:
            return y.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if "not a bot" in msg or "Sign in to confirm" in msg:
            sys.exit("ERRO_YOUTUBE_BLOQUEOU: o YouTube bloqueou o download vindo do servidor do GitHub "
                     "(pede 'confirme que não é um robô'). Use a Twitch ou tente mais tarde.")
        if "subscriber" in msg.lower() or "private" in msg.lower():
            sys.exit("ERRO_VOD_RESTRITO: esse VOD é privado ou só para inscritos.")
        raise


def kick_api(caminho):
    """Kick fica atrás do Cloudflare: usa curl_cffi imitando um navegador."""
    from curl_cffi import requests as cr
    r = cr.get(f"https://kick.com/api/{caminho}", impersonate="chrome", timeout=40)
    if r.status_code != 200:
        sys.exit(f"ERRO_KICK: a Kick respondeu {r.status_code} para {caminho}")
    return r.json()


DEPOIS = float(os.environ.get("VOD_DEPOIS_DE") or 0)  # só aceita VOD que começou depois disso (unix)


def resolver(url):
    """Devolve (url_para_baixar, meta_extra).
    - canal da Twitch -> VOD mais recente (a live em andamento já vira VOD)
    - canal da Kick   -> VOD mais recente (Kick só gera VOD quando a live termina)
    """
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
        return vid, {}
    m = re.match(r"https?://(www\.)?kick\.com/([A-Za-z0-9_-]+)/?(\?.*)?$", url)
    if m and m.group(2).lower() not in ("video", "browse", "categories"):
        slug = m.group(2)
        vids = kick_api(f"v2/channels/{slug}/videos")
        vids = vids if isinstance(vids, list) else vids.get("data", [])
        vids = [v for v in vids if not v.get("is_live")]
        if DEPOIS:
            import datetime
            def ini(v):
                x = v.get("start_time") or v.get("created_at") or ""
                try:
                    d = datetime.datetime.fromisoformat(x.replace("Z", "+00:00").replace(" ", "T"))
                    return (d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)).timestamp()
                except Exception:
                    return 0
            vids = [v for v in vids if ini(v) >= DEPOIS - 1800]
        if not vids:
            sys.exit(f"ERRO_VOD_AINDA_NAO: o VOD da live de {slug} ainda não apareceu na Kick.")
        v = vids[0]
        uuid = (v.get("video") or {}).get("uuid")
        extra = {"titulo": v.get("session_title"), "canal": slug, "inicio_vod": v.get("start_time") or v.get("created_at"),
                 "duracao": (v.get("duration") or 0) / 1000 or None, "m3u8": v.get("source")}
        print(f"canal kick {slug} -> VOD mais recente: {uuid} ({extra['titulo']})", flush=True)
        return (f"https://kick.com/{slug}/videos/{uuid}" if uuid else v.get("source")), extra
    return url, {}


def info_com_reserva(url, extra):
    """Tenta o extrator do yt-dlp; na Kick, se falhar, usa a playlist m3u8 direta da API."""
    try:
        return url, info(url)
    except Exception as e:
        if extra.get("m3u8"):
            print("extrator falhou, usando m3u8 direto da Kick:", str(e)[:200], flush=True)
            return extra["m3u8"], info(extra["m3u8"])
        raise


def cmd_audio(a):
    pasta = os.path.join("jobs", a.job)
    os.makedirs(pasta, exist_ok=True)
    url, extra = resolver(a.url)
    url, i = info_com_reserva(url, extra)
    ao_vivo = bool(i.get("is_live") or i.get("live_status") == "is_live")
    if ao_vivo:
        if plataforma(url) != "twitch":
            sys.exit("ERRO: essa live ainda está no ar. No YouTube/Kick, mande o link depois que ela terminar "
                     "(vira VOD). Na Twitch funciona durante a live, mandando o link do canal.")
    ini, fim = seg(a.inicio), seg(a.fim)
    meta = {"url_original": a.url, "url": url, "titulo": extra.get("titulo") or i.get("title"),
            "canal": extra.get("canal") or i.get("uploader") or i.get("channel"),
            "duracao": i.get("duration") or extra.get("duracao"), "inicio_vod": extra.get("inicio_vod"), "plataforma": plataforma(a.url), "ao_vivo_ainda": ao_vivo,
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
    """Baixa o trecho direto do stream na MELHOR qualidade (até 1080p), com corte exato e
    quase sem perda (CRF 12), para a edição final não sofrer compressão dupla."""
    ini, fim = float(a.inicio), float(a.fim)
    if a.url.startswith("file://"):  # arquivo local (testes)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ini:.2f}", "-to", f"{fim:.2f}", "-i", a.url[7:],
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-c:a", "aac", a.saida], check=True)
        return
    o = {"quiet": True, "no_warnings": True,
         "format": "bv*[height<=1080][vcodec^=avc]+ba/bv*[height<=1080]+ba/b[height<=1080]/b"}
    with yt_dlp.YoutubeDL(o) as y:
        i = y.extract_info(a.url, download=False)
    fmts = i.get("requested_formats") or [i]
    v = fmts[0]
    print(f"   fonte: {v.get('format_id')} {v.get('width')}x{v.get('height')} "
          f"{v.get('fps') or ''}fps {round(v.get('tbr') or 0)}kbps", flush=True)
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for f in fmts:
        hdr = "".join(f"{k}: {val}\r\n" for k, val in (f.get("http_headers") or {}).items())
        if hdr:
            cmd += ["-headers", hdr]
        cmd += ["-ss", f"{ini:.3f}", "-i", f["url"]]
    cmd += ["-t", f"{fim - ini:.3f}", "-map", "0:v:0", "-map", f"{len(fmts) - 1}:a:0?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", a.saida]
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
