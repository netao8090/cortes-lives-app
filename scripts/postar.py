#!/usr/bin/env python3
"""
Posta sozinho os cortes renderizados no TikTok, Instagram Reels, YouTube Shorts
(e Facebook, se estiver conectado) usando a API do Upload-Post.

Entrada:
  jobs/J/postagem.json         textos de cada corte (escritos pelo Claude)
  saida/J/corte_<id>_vertical.mp4   vídeos (o workflow baixa da Release)
  env UPLOADPOST_API_KEY       chave da API (segredo do repositório)
  env UPLOADPOST_USER          opcional: nome do perfil no Upload-Post
Saída:
  jobs/J/postagens.json        o que foi postado/agendado (rodar de novo não duplica)

postagem.json:
  {"fuso": "America/Sao_Paulo",                      (opcional)
   "horarios": ["12:00", "15:00", "18:00", "21:00"], (opcional: 1 corte por horário)
   "redes": ["tiktok", "instagram", "youtube"],      (opcional: padrão = todas conectadas)
   "cortes": [{"id": "01",
               "titulo": "título curto pro YouTube (até 100)",
               "legenda": "legenda do TikTok/Reels com #hashtags",
               "descricao": "descrição do YouTube com Créditos: canal – link"}]}

Linhas que o Claude procura no log: POSTADO, AGENDADO, ERRO_POSTAGEM, AVISO_SEM_CHAVE,
AVISO_SEM_REDES, AVISO_RECONECTAR, AVISO_SEM_AGENDAMENTO, ERRO_LIMITE.
"""
import argparse, json, os, re, sys, time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

API = os.environ.get("UPLOADPOST_API", "https://api.upload-post.com/api")
REDES = ["tiktok", "instagram", "youtube", "facebook"]
HORARIOS = ["12:00", "15:00", "18:00", "21:00"]
FUSO = "America/Sao_Paulo"
LIMITE_JOB_MIN = 300  # o GitHub mata o job em 6 h; sobra folga


def cab(chave):
    return {"Authorization": f"Apikey {chave}"}


def erro_txt(r):
    try:
        j = r.json()
        return str(j.get("message") or j.get("error") or j.get("detail") or j)[:300]
    except Exception:
        return (r.text or "")[:300]


def conectada(v):
    return isinstance(v, dict) and bool(v.get("username") or v.get("handle") or v.get("display_name"))


def escolher_perfil(chave, preferido):
    r = requests.get(f"{API}/uploadposts/users", headers=cab(chave), timeout=60)
    if r.status_code in (401, 403):
        print("ERRO_POSTAGEM chave do Upload-Post inválida:", erro_txt(r)); sys.exit(1)
    r.raise_for_status()
    dados = r.json()
    perfis = dados.get("profiles") or []
    if preferido:
        perfis = [p for p in perfis if p.get("username") == preferido] or perfis
    for p in perfis:
        sa = p.get("social_accounts") or {}
        ok = [n for n in REDES if conectada(sa.get(n)) and not sa[n].get("reauth_required")]
        reauth = [n for n in REDES if conectada(sa.get(n)) and sa[n].get("reauth_required")]
        if ok or reauth:
            for n in reauth:
                print(f"AVISO_RECONECTAR {n}: reconecte essa conta no painel do Upload-Post")
            return p["username"], ok, dados.get("plan")
    return (perfis[0]["username"] if perfis else None), [], dados.get("plan")


def proximos_horarios(n, horarios, fuso, agora=None):
    tz = ZoneInfo(fuso)
    base = (agora or datetime.now(timezone.utc)).astimezone(tz) + timedelta(minutes=20)
    out, dia = [], base.date()
    while len(out) < n:
        for h in sorted(horarios):
            hh, mm = map(int, h.split(":"))
            t = datetime(dia.year, dia.month, dia.day, hh, mm, tzinfo=tz)
            if t >= base and len(out) < n:
                out.append(t)
        dia += timedelta(days=1)
    return out


def montar_campos(perfil, redes, c, quando, fuso, chave_id):
    legenda = (c.get("legenda") or c.get("titulo") or "").strip()
    titulo = (c.get("titulo") or legenda).strip()[:100]
    descricao = (c.get("descricao") or legenda).strip()
    tags = re.findall(r"#(\w+)", legenda + " " + descricao)
    if tags and "#" not in descricao:
        descricao += "\n\n" + " ".join("#" + t for t in tags)
    campos = [("user", perfil), ("title", legenda[:2200]), ("async_upload", "true"),
              ("request_id", chave_id), ("external_id", chave_id)]
    campos += [("platform[]", r) for r in redes]
    if "youtube" in redes:
        campos += [("youtube_title", titulo), ("youtube_description", descricao[:5000]),
                   ("privacyStatus", "public"), ("categoryId", "20"),
                   ("selfDeclaredMadeForKids", "false")]
        campos += [("tags[]", t) for t in dict.fromkeys(tags)][:15]
    if "instagram" in redes:
        campos += [("media_type", "REELS"), ("share_to_feed", "true")]
    if "facebook" in redes:
        campos += [("facebook_description", legenda)]
    if quando:
        campos += [("scheduled_date", quando.strftime("%Y-%m-%dT%H:%M:%S")), ("timezone", fuso)]
    return campos


def enviar(chave, campos, video, chave_id):
    with open(video, "rb") as f:
        return requests.post(f"{API}/upload", headers={**cab(chave), "Idempotency-Key": chave_id},
                             data=campos, files={"video": (os.path.basename(video), f, "video/mp4")},
                             timeout=900)


def esperar_status(chave, request_id=None, job_id=None, max_s=900):
    q = {"request_id": request_id} if request_id else {"job_id": job_id}
    fim = time.time() + max_s
    while time.time() < fim:
        try:
            r = requests.get(f"{API}/uploadposts/status", headers=cab(chave), params=q, timeout=60)
            if r.ok:
                j = r.json()
                if j.get("status") == "completed":
                    return j.get("results") or []
        except requests.RequestException:
            pass
        time.sleep(15)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--so", default="")
    a = ap.parse_args()

    chave = os.environ.get("UPLOADPOST_API_KEY", "").strip()
    if not chave:
        print("AVISO_SEM_CHAVE postagem automática não configurada (falta o segredo UPLOADPOST_API_KEY)")
        return

    pasta = os.path.join("jobs", a.job)
    cfg_path = os.path.join(pasta, "postagem.json")
    if not os.path.exists(cfg_path):
        print(f"ERRO_POSTAGEM falta {cfg_path}"); sys.exit(1)
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    res_path = os.path.join(pasta, "postagens.json")
    feitos = json.load(open(res_path, encoding="utf-8")) if os.path.exists(res_path) else {}

    so = {s.strip() for s in a.so.split(",") if s.strip()}
    cortes = [c for c in cfg.get("cortes", []) if not so or str(c["id"]) in so]
    cortes = [c for c in cortes if not (feitos.get(str(c["id"])) or {}).get("ok")]
    if not cortes:
        print("nada novo para postar"); return

    perfil, redes, plano = escolher_perfil(chave, os.environ.get("UPLOADPOST_USER", "").strip())
    if cfg.get("redes"):
        redes = [r for r in redes if r in cfg["redes"]]
    print(f"perfil={perfil} plano={plano} redes={','.join(redes) or '-'}", flush=True)
    if not perfil or not redes:
        print("AVISO_SEM_REDES nenhuma rede conectada no Upload-Post"); return

    fuso = cfg.get("fuso") or FUSO
    slots = proximos_horarios(len(cortes), cfg.get("horarios") or HORARIOS, fuso)
    agendar = True
    espaco_min = min(90, LIMITE_JOB_MIN // max(1, len(cortes) - 1))

    def salvar():
        json.dump(feitos, open(res_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    for i, c in enumerate(cortes):
        cid = str(c["id"])
        video = os.path.join("saida", a.job, f"corte_{cid}_vertical.mp4")
        if not os.path.exists(video):
            print(f"ERRO_POSTAGEM {cid} sem vídeo vertical"); continue
        chave_id = f"{a.job}-{cid}"[:250]
        alvo = list(redes)
        for tentativa in range(3):
            quando = slots[i] if agendar else None
            r = enviar(chave, montar_campos(perfil, alvo, c, quando, fuso, chave_id), video, chave_id)
            if r.ok:
                break
            msg = erro_txt(r)
            if r.status_code == 429:
                print(f"ERRO_LIMITE {cid} limite do plano/rede atingido: {msg}")
                salvar(); return
            if agendar and re.search(r"schedul|plan|upgrade", msg, re.I):
                print(f"AVISO_SEM_AGENDAMENTO o plano não agenda; postando agora com {espaco_min} min entre cortes")
                agendar = False; continue
            fora = [n for n in alvo if re.search(n, msg, re.I)]
            if fora and len(fora) < len(alvo):
                print(f"AVISO {cid} sem {','.join(fora)} nesta conta: {msg}")
                alvo = [n for n in alvo if n not in fora]; chave_id += "-b"; continue
            break
        if not r.ok:
            print(f"ERRO_POSTAGEM {cid} HTTP {r.status_code}: {erro_txt(r)}")
            feitos[cid] = {"ok": False, "erro": erro_txt(r)}; salvar(); continue

        j = r.json() if r.content else {}
        if quando:
            feitos[cid] = {"ok": True, "agendado": quando.isoformat(), "redes": alvo,
                           "job_id": j.get("job_id"), "request_id": j.get("request_id")}
            print(f"AGENDADO {cid} {quando.strftime('%d/%m %H:%M')} {','.join(alvo)}", flush=True)
        else:
            resultados = j.get("results")
            if not resultados and (j.get("request_id") or chave_id):
                resultados = esperar_status(chave, request_id=j.get("request_id") or chave_id)
            links = {}
            for x in resultados or []:
                rede = x.get("platform", "?")
                if x.get("success"):
                    links[rede] = x.get("post_url") or ""
                    print(f"POSTADO {cid} {rede} {x.get('post_url') or ''}", flush=True)
                else:
                    print(f"ERRO_POSTAGEM {cid} {rede}: {x.get('message')}", flush=True)
            feitos[cid] = {"ok": bool(links) or resultados is None, "postado": datetime.now(timezone.utc).isoformat(),
                           "redes": alvo, "links": links, "pendente": resultados is None}
            if resultados is None:
                print(f"POSTADO {cid} enviado (ainda processando nas redes)", flush=True)
        salvar()
        if not agendar and i < len(cortes) - 1:
            time.sleep(espaco_min * 60)


if __name__ == "__main__":
    main()
