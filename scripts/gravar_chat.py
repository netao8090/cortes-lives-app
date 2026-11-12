#!/usr/bin/env python3
"""
Grava só o CHAT de uma live ao vivo (Kick ou Twitch) até a live acabar.
O vídeo vem depois do VOD completo; o chat é alinhado pelo horário de início da live.

  gravar_chat.py <url_do_canal> --job J [--max-minutos 340]

Saídas (salvas no repositório a cada ~10 min, para não perder nada):
  jobs/J/chat_live.jsonl  {"ts": unix_time, "u": usuário, "m": texto}
  jobs/J/live.json        {"plataforma", "canal", "titulo", "inicio_live_ts", ...}
"""
import argparse, datetime, json, os, re, subprocess, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from baixar import kick_api  # noqa: E402
import gravar  # noqa: E402


def status(url):
    """Devolve dict com ao_vivo, titulo, inicio_live_ts, chatroom."""
    url = url.strip().rstrip("/")
    m = re.match(r"https?://(www\.)?kick\.com/([A-Za-z0-9_-]+)", url)
    if m:
        slug = m.group(2)
        d = kick_api(f"v2/channels/{slug}")
        live = d.get("livestream") or {}
        ini = live.get("start_time") or live.get("created_at")
        ts = None
        if ini:
            try:
                ts = datetime.datetime.fromisoformat(ini.replace("Z", "+00:00").replace(" ", "T"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=datetime.timezone.utc)
                ts = ts.timestamp()
            except Exception:
                ts = None
        return {"plataforma": "kick", "canal": slug, "ao_vivo": bool(live) and live.get("is_live", True),
                "titulo": live.get("session_title"), "inicio_live_ts": ts,
                "chatroom": (d.get("chatroom") or {}).get("id")}
    m = re.match(r"https?://(www\.|m\.)?twitch\.tv/([A-Za-z0-9_]+)", url)
    if m:
        canal = m.group(2).lower()
        import yt_dlp
        try:
            with yt_dlp.YoutubeDL({"quiet": True}) as y:
                i = y.extract_info(f"https://www.twitch.tv/{canal}", download=False)
            return {"plataforma": "twitch", "canal": canal, "ao_vivo": True, "titulo": i.get("description"),
                    "inicio_live_ts": i.get("timestamp"), "chatroom": canal}
        except Exception:
            return {"plataforma": "twitch", "canal": canal, "ao_vivo": False, "chatroom": canal}
    sys.exit("ERRO: mande o link do canal da Kick ou da Twitch.")


def salvar_git(msg):
    subprocess.run(["git", "add", "jobs"], check=False)
    if subprocess.run(["git", "commit", "-q", "-m", msg], check=False).returncode != 0:
        return
    for i in range(5):
        if subprocess.run(["git", "pull", "-q", "--rebase"]).returncode == 0 and \
           subprocess.run(["git", "push", "-q"]).returncode == 0:
            return
        time.sleep(5 * (i + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--job", required=True)
    ap.add_argument("--max-minutos", type=float, default=340)
    a = ap.parse_args()
    jobdir = os.path.join("jobs", a.job); os.makedirs(jobdir, exist_ok=True)

    st = status(a.url)
    if not st["ao_vivo"]:
        sys.exit(f"ERRO_OFFLINE: {st['canal']} não está ao vivo agora.")
    print("live:", st, flush=True)
    info = dict(st, url_canal=a.url, inicio_captura_ts=time.time())
    json.dump(info, open(os.path.join(jobdir, "live.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    class ChatTS(gravar.Chat):
        def add(self, u, msg):
            with self.lock:
                self.f.write(json.dumps({"ts": round(time.time(), 1), "u": u, "m": msg}, ensure_ascii=False) + "\n")
                self.n += 1
                if self.n % 20 == 0:
                    self.f.flush()

    chat = ChatTS(os.path.join(jobdir, "chat_live.jsonl"), lambda t: t)
    alvo = gravar.chat_kick if st["plataforma"] == "kick" else gravar.chat_twitch
    threading.Thread(target=alvo, args=(st["chatroom"], chat), daemon=True).start()

    fim = time.time() + a.max_minutos * 60
    ultimo_save, offline = time.time(), 0
    while time.time() < fim:
        time.sleep(60)
        try:
            vivo = status(a.url)["ao_vivo"]
        except SystemExit:
            vivo = False
        except Exception as e:
            print("erro checando status:", str(e)[:100]); vivo = True
        offline = 0 if vivo else offline + 1
        print(time.strftime("%H:%M"), f"{chat.n} mensagens", "AO VIVO" if vivo else f"offline? ({offline})", flush=True)
        if offline >= 3:  # 3 checagens seguidas offline = live acabou
            break
        if time.time() - ultimo_save > 600:
            chat.f.flush(); salvar_git(f"chat parcial: {a.job}"); ultimo_save = time.time()

    gravar.PARAR.set(); time.sleep(1); chat.f.flush()
    info.update(fim_captura_ts=time.time(), mensagens=chat.n, live_acabou=offline >= 3)
    json.dump(info, open(os.path.join(jobdir, "live.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    salvar_git(f"chat final: {a.job}")
    print("fim:", info, flush=True)


if __name__ == "__main__":
    main()
