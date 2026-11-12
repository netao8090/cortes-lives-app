#!/usr/bin/env python3
import json, re, sys, time
from curl_cffi import requests as cr
import websocket
slug = sys.argv[2]
d = cr.get(f"https://kick.com/api/v2/channels/{slug}", impersonate="chrome", timeout=30).json()
cid, room = d.get("id"), (d.get("chatroom") or {}).get("id")
print("channel id", cid, "chatroom", room, "chaves:", [k for k in d.keys()][:40])
print("chatroom obj:", json.dumps(d.get("chatroom"))[:500])
for path in [f"v2/channels/{cid}/messages", f"v1/channels/{cid}/messages", f"v2/chatrooms/{room}/messages"]:
    for i in range(3):
        r = cr.get(f"https://kick.com/api/{path}", impersonate="chrome", timeout=30)
        try:
            msgs = r.json().get("data", {}).get("messages", [])
            print(path, r.status_code, len(msgs), [m.get("content", "")[:30] for m in msgs[:3]], msgs[0].get("created_at") if msgs else "")
        except Exception:
            print(path, r.status_code, r.text[:150])
        time.sleep(2)
for cl in ["us2", "us3", "mt1", "eu", "ap1", "ap2", "us1", "sa1"]:
    try:
        ws = websocket.create_connection(f"wss://ws-{cl}.pusher.com/app/32cbd69e4b950bf97679?protocol=7&client=js&version=8.4.0&flash=false", timeout=8)
        print(cl, ws.recv()[:150]); ws.close()
    except Exception as e:
        print(cl, "erro", str(e)[:80])
html = cr.get(f"https://kick.com/{slug}", impersonate="chrome", timeout=30).text
for k in ["pusher", "websocket", "wss://", "reverb", "soketi", "ably"]:
    for m in re.finditer(k, html, re.I):
        print("html", k, html[max(0, m.start()-80):m.start()+120].replace("\n", " ")); break
srcs = re.findall(r'(/_next/static/[^"\']+\.js)', html)
print("scripts:", len(srcs))
for s in srcs:
    js = cr.get("https://kick.com" + s, impersonate="chrome", timeout=30).text
    for k in ["pusher", "wss://", "reverb", "soketi"]:
        for m in re.finditer(k, js, re.I):
            print("js", s[-40:], k, js[max(0, m.start()-150):m.start()+200].replace("\n", " ")); break
