#!/usr/bin/env python3
"""Diagnóstico do chat da Kick: testa websocket (pusher) e a API de mensagens."""
import json, re, sys, time
from curl_cffi import requests as cr
import websocket

chatroom, slug = sys.argv[1], sys.argv[2]
print("== API de mensagens recentes")
for path in [f"v2/channels/{chatroom}/messages", f"v2/chatrooms/{chatroom}/messages"]:
    try:
        r = cr.get(f"https://kick.com/api/{path}", impersonate="chrome", timeout=30)
        print(path, r.status_code, r.text[:400].replace("\n", " "))
    except Exception as e:
        print(path, "erro", e)
print("== chave do pusher no site")
try:
    html = cr.get(f"https://kick.com/{slug}", impersonate="chrome", timeout=30).text
    scripts = re.findall(r'src="([^"]+\.js)"', html)[:40]
    achou = set(re.findall(r'(?:pusher|PUSHER)[^"]{0,80}?"([0-9a-f]{20})"', html))
    for s in scripts:
        u = s if s.startswith("http") else "https://kick.com" + s
        try:
            js = cr.get(u, impersonate="chrome", timeout=30).text
            for k in re.findall(r'"([0-9a-f]{20})"', js):
                if "pusher" in js.lower():
                    achou.add(k)
            for c in re.findall(r'cluster:\s*"([a-z0-9-]+)"', js):
                print("cluster no js:", c)
        except Exception:
            pass
    print("chaves candidatas:", achou)
except Exception as e:
    print("erro site", e)
print("== websocket")
for key in ["32cbd69e4b950bf97679"]:
    for ch in [f"chatrooms.{chatroom}.v2", f"chatrooms.{chatroom}", f"chatroom_{chatroom}"]:
        try:
            ws = websocket.create_connection(f"wss://ws-us2.pusher.com/app/{key}?protocol=7&client=js&version=8.4.0&flash=false", timeout=10)
            print(key, ch, "conectou:", ws.recv()[:200])
            ws.send(json.dumps({"event": "pusher:subscribe", "data": {"auth": "", "channel": ch}}))
            fim = time.time() + 25
            n = 0
            while time.time() < fim:
                try:
                    m = ws.recv(); n += 1
                    if n <= 4:
                        print("  ", m[:300])
                except websocket.WebSocketTimeoutException:
                    pass
            print("  total eventos:", n)
            ws.close()
        except Exception as e:
            print(key, ch, "erro:", e)
