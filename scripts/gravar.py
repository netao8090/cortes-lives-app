#!/usr/bin/env python3
"""
Grava uma live que está AO VIVO (Kick ou Twitch) + o chat, a partir de agora.

  gravar.py <url_do_canal> --job J --minutos 30 --pasta /mnt/gravacao

Saídas:
  <pasta>/<J>/gravacao.ts        vídeo da live (qualidade original, sem recompressão)
  jobs/<J>/meta.json             dados da live
  jobs/<J>/chat.jsonl            mensagens do chat: {"t": segundos_no_video, "u": usuário, "m": texto}
"""
import argparse, json, os, re, socket, subprocess, sys, threading, time

import yt_dlp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from baixar import kick_api  # noqa: E402

PARAR = threading.Event()


# ---------------------------------------------------------------- resolver live
def resolver(url):
    url = url.strip().rstrip("/")
    m = re.match(r"https?://(www\.)?kick\.com/([A-Za-z0-9_-]+)", url)
    if m:
        slug = m.group(2)
        d = kick_api(f"v2/channels/{slug}")
        live = d.get("livestream") or {}
        if not live or not live.get("is_live", True):
            sys.exit(f"ERRO_OFFLINE: {slug} não está ao vivo agora.")
        return {"plataforma": "kick", "canal": slug, "titulo": live.get("session_title"),
                "m3u8": d.get("playback_url"), "chatroom": d.get("id")}
    m = re.match(r"https?://(www\.|m\.)?twitch\.tv/([A-Za-z0-9_]+)", url)
    if m:
        canal = m.group(2).lower()
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "format": "best[height<=1080]/best"}) as y:
                i = y.extract_info(f"https://www.twitch.tv/{canal}", download=False)
        except Exception as e:
            sys.exit(f"ERRO_OFFLINE: {canal} não está ao vivo agora ({str(e)[:120]})")
        return {"plataforma": "twitch", "canal": canal, "titulo": i.get("description") or i.get("title"),
                "m3u8": i["url"], "chatroom": canal}
    sys.exit("ERRO: para gravar ao vivo, mande o link do canal da Kick ou da Twitch.")


# ---------------------------------------------------------------- chat
class Chat:
    def __init__(self, arquivo, relogio):
        self.f = open(arquivo, "a", encoding="utf-8")
        self.relogio = relogio  # função: tempo de parede -> segundos no vídeo
        self.n = 0
        self.lock = threading.Lock()

    def add(self, u, msg, ts=None):
        t = self.relogio(ts or time.time())
        if t is None:
            return
        with self.lock:
            self.f.write(json.dumps({"t": round(t, 1), "u": u, "m": msg}, ensure_ascii=False) + "\n")
            self.n += 1
            if self.n % 50 == 0:
                self.f.flush()


def chat_kick(canal_id, chat):
    """Kick: lê a API de mensagens recentes do canal a cada 2 s (o websocket antigo foi desativado)."""
    import datetime
    from curl_cffi import requests as cr
    vistos = set()
    sess = cr.Session(impersonate="chrome")
    while not PARAR.is_set():
        try:
            r = sess.get(f"https://kick.com/api/v2/channels/{canal_id}/messages", timeout=20)
            msgs = (r.json().get("data") or {}).get("messages") or []
            for m in reversed(msgs):  # do mais antigo pro mais novo
                if m.get("id") in vistos:
                    continue
                vistos.add(m.get("id"))
                ts = None
                try:
                    ts = datetime.datetime.fromisoformat(m["created_at"].replace("Z", "+00:00")).timestamp()
                except Exception:
                    pass
                txt = re.sub(r"\[emote:\d+:([^\]]+)\]", r":\1:", m.get("content", ""))
                chat.add((m.get("sender") or {}).get("username", "?"), txt, ts)
            if len(vistos) > 20000:
                vistos = set(list(vistos)[-5000:])
        except Exception as e:
            print("chat kick erro:", str(e)[:120], flush=True)
            time.sleep(5)
        time.sleep(2)


def chat_twitch(canal, chat):
    while not PARAR.is_set():
        try:
            s = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=30)
            s.send(b"NICK justinfan%d\r\n" % (int(time.time()) % 99999))
            s.send(f"JOIN #{canal}\r\n".encode())
            buf = ""
            while not PARAR.is_set():
                try:
                    buf += s.recv(65536).decode("utf-8", "ignore")
                except socket.timeout:
                    continue
                *linhas, buf = buf.split("\r\n")
                for ln in linhas:
                    if ln.startswith("PING"):
                        s.send(b"PONG :tmi.twitch.tv\r\n")
                    m = re.match(r":(\w+)!\S+ PRIVMSG #\w+ :(.*)", ln)
                    if m:
                        chat.add(m.group(1), m.group(2))
        except Exception as e:
            print("chat twitch reconectando:", str(e)[:120], flush=True)
            time.sleep(3)


# ---------------------------------------------------------------- gravação
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--job", required=True)
    ap.add_argument("--minutos", type=float, default=30)
    ap.add_argument("--pasta", default="/mnt/gravacao")
    a = ap.parse_args()

    info = resolver(a.url)
    print("live:", {k: v for k, v in info.items() if k != "m3u8"}, flush=True)
    dest = os.path.join(a.pasta, a.job); os.makedirs(dest, exist_ok=True)
    jobdir = os.path.join("jobs", a.job); os.makedirs(jobdir, exist_ok=True)

    partes = []  # (inicio_parede, duracao_no_video_ate_agora)
    estado = {"inicio_parte": None, "acumulado": 0.0}

    def relogio(agora):
        if estado["inicio_parte"] is None:
            return None
        return estado["acumulado"] + (agora - estado["inicio_parte"])

    chat = Chat(os.path.join(jobdir, "chat.jsonl"), relogio)
    if info["plataforma"] == "kick" and info.get("chatroom"):
        threading.Thread(target=chat_kick, args=(info["chatroom"], chat), daemon=True).start()
    elif info["plataforma"] == "twitch":
        threading.Thread(target=chat_twitch, args=(info["chatroom"], chat), daemon=True).start()

    fim = time.time() + a.minutos * 60
    k = 0
    while time.time() < fim - 5:
        arq = os.path.join(dest, f"parte_{k:02d}.ts")
        resta = fim - time.time()
        estado["inicio_parte"] = time.time()
        p = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", info["m3u8"], "-map", "0:v:0", "-map", "0:a:0?",
                            "-c", "copy", "-t", f"{resta:.0f}", "-f", "mpegts", arq])
        dur = 0.0
        if os.path.exists(arq) and os.path.getsize(arq) > 100000:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", arq],
                               capture_output=True, text=True)
            try:
                dur = float(r.stdout.strip())
            except ValueError:
                dur = 0.0
            partes.append(arq)
        estado["acumulado"] += dur
        estado["inicio_parte"] = None
        print(f"parte {k}: {dur/60:.1f} min (ffmpeg saiu com {p.returncode})", flush=True)
        k += 1
        if time.time() < fim - 5:
            time.sleep(5)
            try:  # a URL do stream pode ter mudado
                info["m3u8"] = resolver(a.url)["m3u8"]
            except SystemExit as e:
                print("live caiu/terminou:", e, flush=True); break

    PARAR.set(); time.sleep(1); chat.f.flush()
    if not partes:
        sys.exit("ERRO: nada foi gravado.")
    lista = os.path.join(dest, "lista.txt")
    with open(lista, "w") as f:
        for p_ in partes:
            f.write(f"file '{p_}'\n")
    final = os.path.join(dest, "gravacao.ts")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lista, "-c", "copy", final], check=True)
    for p_ in partes:
        os.remove(p_)
    meta = {"url_original": a.url, "url": "file://" + final, "titulo": info.get("titulo"), "canal": info["canal"],
            "plataforma": info["plataforma"], "gravado_ao_vivo": True,
            "inicio_gravacao": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(fim - a.minutos * 60)),
            "duracao": estado["acumulado"], "mensagens_chat": chat.n, "offset": 0.0}
    with open(os.path.join(jobdir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print("gravação ok:", json.dumps(meta, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
