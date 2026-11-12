#!/usr/bin/env python3
"""
Posta sozinho os cortes no Instagram Reels (API oficial da Meta) e no TikTok (API grátis do Buffer).
Tudo grátis. Cada corte ganha um horário de pico; o Buffer agenda o TikTok sozinho e o Instagram
entra numa fila que o workflow roda de hora em hora.

Modos:
  --job J [--so 01,02]   agenda os cortes do job (TikTok no Buffer, Instagram na fila)
  --job J --teste        testa as contas com o 1º corte SEM publicar nada
                         (TikTok vira rascunho no Buffer; Instagram só sobe e processa)
  --fila                 publica no Instagram o que já chegou na hora; cuida do token

Segredos (GitHub → Settings → Secrets → Actions):
  IG_TOKEN        token da API do Instagram (painel da Meta → "Generate token")
  BUFFER_API_KEY  chave da API do Buffer (publish.buffer.com/settings/api)
  GH_PAT          opcional: token do GitHub com permissão de Secrets, para renovar o IG_TOKEN sozinho

Arquivos:
  jobs/J/postagem.json        textos (o Claude escreve)  {"cortes":[{"id","titulo","legenda","descricao"}]}
  estado/fila/J.json          o que foi agendado/postado de cada job (rodar de novo não duplica)
  estado/instagram.json       quando o token foi renovado (o token em si nunca vai pro repositório)

Linhas que o Claude procura no log: AGENDADO, POSTADO, TESTE_OK, ERRO_POSTAGEM, AVISO_SEM_CHAVE,
AVISO_SEM_TIKTOK, AVISO_TOKEN_IG, BUFFER_CAMPOS.
"""
import argparse, glob, json, os, re, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

IG_API = os.environ.get("IG_API", "https://graph.instagram.com/v23.0")
IG_HOST = os.environ.get("IG_HOST", "https://graph.instagram.com")
BUFFER_API = os.environ.get("BUFFER_API", "https://api.buffer.com")
REPO = os.environ.get("GITHUB_REPOSITORY", "netao8090/cortes-lives-app")
MIDIA_BASE = os.environ.get("MIDIA_BASE") or f"https://raw.githubusercontent.com/{REPO}/midia"
HORARIOS = ["12:00", "15:00", "18:00", "21:00"]
FUSO = "America/Sao_Paulo"
PASTA_FILA = "estado/fila"
ESTADO_IG = "estado/instagram.json"


def agora():
    return datetime.now(timezone.utc)


def ler(path, padrao):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def gravar(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def msg_erro(r):
    try:
        j = r.json()
        e = j.get("error") or j.get("errors") or j.get("message") or j
        return (json.dumps(e, ensure_ascii=False) if not isinstance(e, str) else e)[:400]
    except Exception:
        return (r.text or "")[:400]


# ---------------------------------------------------------------- horários
def horarios_ocupados():
    occ = set()
    for f in glob.glob(os.path.join(PASTA_FILA, "*.json")):
        for it in ler(f, {}).get("itens", []):
            occ.add(it["quando"][:16])
    return occ


def proximos_horarios(n, horarios, fuso, ocupados=(), base=None):
    tz = ZoneInfo(fuso)
    base = (base or agora()).astimezone(tz) + timedelta(minutes=20)
    out, dia = [], base.date()
    while len(out) < n:
        for h in sorted(horarios):
            hh, mm = map(int, h.split(":"))
            t = datetime(dia.year, dia.month, dia.day, hh, mm, tzinfo=tz)
            chave = t.astimezone(timezone.utc).isoformat()[:16]
            if t >= base and chave not in ocupados and len(out) < n:
                out.append(t)
        dia += timedelta(days=1)
    return out


def video_local(job, cid):
    nome = f"corte_{cid}_vertical.mp4"
    path = os.path.join("saida", job, nome)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(["gh", "release", "download", job, "-p", nome, "-D", os.path.dirname(path),
                        "--clobber", "-R", REPO], check=False)
    return path if os.path.exists(path) else None


# ---------------------------------------------------------------- Instagram
def ig_conta(token):
    r = requests.get(f"{IG_API}/me", params={"fields": "user_id,username", "access_token": token}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"token do Instagram recusado: {msg_erro(r)}")
    j = r.json()
    return str(j.get("user_id") or j.get("id")), j.get("username", "?")


def ig_publicar(token, uid, video, legenda, teste=False):
    """Sobe o arquivo direto (sem precisar de link público), espera processar e publica."""
    r = requests.post(f"{IG_API}/{uid}/media", timeout=60, data={
        "media_type": "REELS", "upload_type": "resumable", "caption": legenda[:2200],
        "share_to_feed": "true", "access_token": token})
    if not r.ok:
        raise RuntimeError(f"criar Reel: {msg_erro(r)}")
    j = r.json()
    cont = j["id"]
    uri = j.get("uri") or f"https://rupload.facebook.com/ig-api-upload/v23.0/{cont}"
    tam = os.path.getsize(video)
    with open(video, "rb") as f:
        r = requests.post(uri, data=f, timeout=900, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(tam)})
    if not r.ok:
        raise RuntimeError(f"enviar vídeo: {msg_erro(r)}")
    fim, st = time.time() + 900, {}
    while time.time() < fim:
        st = requests.get(f"{IG_API}/{cont}", timeout=60,
                          params={"fields": "status_code,status", "access_token": token}).json()
        if st.get("status_code") in ("FINISHED", "ERROR", "EXPIRED"):
            break
        time.sleep(20)
    if st.get("status_code") != "FINISHED":
        raise RuntimeError(f"processamento do Reel: {st.get('status_code')} {st.get('status', '')}")
    if teste:
        return "teste"
    r = requests.post(f"{IG_API}/{uid}/media_publish", timeout=120,
                      data={"creation_id": cont, "access_token": token})
    if not r.ok:
        raise RuntimeError(f"publicar: {msg_erro(r)}")
    mid = r.json().get("id")
    link = requests.get(f"{IG_API}/{mid}", timeout=60,
                        params={"fields": "permalink", "access_token": token}).json().get("permalink", "")
    return link


def ig_cuidar_token(token):
    """Renova o token (vale 60 dias) a cada ~7 dias se houver GH_PAT; senão avisa antes de vencer."""
    est = ler(ESTADO_IG, {})
    ref = est.get("renovado_em") or est.get("visto_em")
    if not ref:
        est["visto_em"] = agora().isoformat(); gravar(ESTADO_IG, est); return
    dias = (agora() - datetime.fromisoformat(ref)).days
    pat = os.environ.get("GH_PAT", "").strip()
    if pat and dias >= 7:
        r = requests.get(f"{IG_HOST}/refresh_access_token", timeout=60,
                         params={"grant_type": "ig_refresh_token", "access_token": token})
        if r.ok and r.json().get("access_token"):
            novo = r.json()["access_token"]
            p = subprocess.run(["gh", "secret", "set", "IG_TOKEN", "-R", REPO], input=novo, text=True,
                               env={**os.environ, "GH_TOKEN": pat}, capture_output=True)
            if p.returncode == 0:
                est.update(renovado_em=agora().isoformat(), visto_em=None); gravar(ESTADO_IG, est)
                print("token do Instagram renovado"); return
            print(f"AVISO_TOKEN_IG não consegui salvar o token renovado (GH_PAT sem permissão de Secrets?): {p.stderr[:200]}")
        else:
            print(f"AVISO_TOKEN_IG renovação recusada: {msg_erro(r)}")
    if dias >= 50:
        print(f"AVISO_TOKEN_IG o token do Instagram vence em ~{max(0, 60 - dias)} dias; gere outro no painel da Meta")


# ---------------------------------------------------------------- Buffer (TikTok)
def gql(chave, query, variables=None):
    r = requests.post(BUFFER_API, timeout=120, json={"query": query, "variables": variables or {}},
                      headers={"Authorization": f"Bearer {chave}", "Content-Type": "application/json"})
    if not r.ok:
        raise RuntimeError(f"Buffer HTTP {r.status_code}: {msg_erro(r)}")
    j = r.json()
    if j.get("errors"):
        raise RuntimeError("Buffer: " + "; ".join(e.get("message", "") for e in j["errors"])[:400])
    return j["data"]


ENUMS = {"schedulingType", "mode"}


def literal(v, chave=""):
    """dict → literal de input GraphQL (enums sem aspas), sem depender do nome exato dos tipos."""
    if isinstance(v, dict):
        return "{" + ",".join(f"{k}:{literal(x, k)}" for k, x in v.items()) + "}"
    if isinstance(v, list):
        return "[" + ",".join(literal(x) for x in v) + "]"
    if isinstance(v, bool):
        return "true" if v else "false"
    if chave in ENUMS:
        return str(v)
    return json.dumps(v, ensure_ascii=False)


def buffer_tiktok(chave):
    orgs = gql(chave, "query{account{organizations{id name}}}")["account"]["organizations"]
    for o in orgs:
        canais = gql(chave, "query{channels(input:%s){id name service}}"
                     % literal({"organizationId": o["id"]}))["channels"]
        tt = [c for c in canais if (c.get("service") or "").lower() == "tiktok"]
        if tt:
            return tt[0]
    return None


def buffer_campos():
    """Mostra no log os campos aceitos, para corrigir rápido se o Buffer mudar algo."""
    try:
        q = ("query{a:__type(name:\"CreatePostInput\"){inputFields{name}}"
             " b:__type(name:\"TikTokPostMetadataInput\"){inputFields{name}}}")
        d = gql(os.environ["BUFFER_API_KEY"], q)
        nomes = lambda t: ",".join(f["name"] for f in ((d.get(t) or {}).get("inputFields") or []))
        print(f"BUFFER_CAMPOS CreatePostInput={nomes('a')} TikTok={nomes('b')}")
    except Exception as e:
        print(f"BUFFER_CAMPOS indisponível: {e}")


def buffer_postar(chave, canal_id, texto, url, quando=None, teste=False):
    entrada = {"text": texto[:2200], "channelId": canal_id, "schedulingType": "automatic",
               "assets": [{"video": {"url": url}}]}
    if teste:
        entrada.update(mode="addToQueue", saveToDraft=True)
    else:
        entrada.update(mode="customScheduled",
                       dueAt=quando.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    q = ("mutation{createPost(input:%s){"
         "... on PostActionSuccess{post{id}} ... on MutationError{message}}}") % literal(entrada)
    try:
        res = gql(chave, q)["createPost"]
    except RuntimeError:
        buffer_campos(); raise
    if res.get("message") or not res.get("post"):
        buffer_campos()
        raise RuntimeError(f"Buffer recusou: {res.get('message')}")
    return res["post"]["id"]


# ---------------------------------------------------------------- modos
def agendar(job, so, teste):
    ig_tok = os.environ.get("IG_TOKEN", "").strip()
    buf = os.environ.get("BUFFER_API_KEY", "").strip()
    if not ig_tok and not buf:
        print("AVISO_SEM_CHAVE postagem não configurada (faltam IG_TOKEN e/ou BUFFER_API_KEY)"); return 0

    cfg = ler(os.path.join("jobs", job, "postagem.json"), None)
    if not cfg:
        print(f"ERRO_POSTAGEM falta jobs/{job}/postagem.json"); return 1
    fila_path = os.path.join(PASTA_FILA, f"{job}.json")
    fila = ler(fila_path, {"job": job, "itens": []})
    ja = {(it["id"], it["rede"]) for it in fila["itens"]}

    redes, uid, canal = [], None, None
    if ig_tok:
        try:
            uid, nome = ig_conta(ig_tok); redes.append("instagram"); print(f"instagram=@{nome}")
        except Exception as e:
            print(f"ERRO_POSTAGEM instagram: {e}")
    if buf:
        try:
            canal = buffer_tiktok(buf)
            if canal:
                redes.append("tiktok"); print(f"tiktok={canal.get('name')} (Buffer)")
            else:
                print("AVISO_SEM_TIKTOK nenhum TikTok conectado no Buffer")
        except Exception as e:
            print(f"ERRO_POSTAGEM buffer: {e}")
    if not redes:
        return 1
    if cfg.get("redes"):
        redes = [r for r in redes if r in cfg["redes"]]

    filtro = {s.strip() for s in so.split(",") if s.strip()}
    cortes = [c for c in cfg.get("cortes", []) if not filtro or str(c["id"]) in filtro]

    if teste:
        c = cortes[0]; cid = str(c["id"]); video = video_local(job, cid)
        if not video:
            print(f"ERRO_POSTAGEM {cid} sem vídeo"); return 1
        falhou = 0
        for rede in redes:
            try:
                if rede == "instagram":
                    ig_publicar(ig_tok, uid, video, c.get("legenda", ""), teste=True)
                    print("TESTE_OK instagram: vídeo subiu e foi aceito (nada publicado)")
                else:
                    buffer_postar(buf, canal["id"], c.get("legenda", ""),
                                  f"{MIDIA_BASE}/{job}/corte_{cid}_vertical.mp4", teste=True)
                    print("TESTE_OK tiktok: rascunho criado no Buffer (nada publicado; pode apagar)")
            except Exception as e:
                falhou = 1; print(f"ERRO_POSTAGEM teste {rede}: {e}")
        return falhou

    pend = [c for c in cortes if any((str(c["id"]), r) not in ja for r in redes)]
    if not pend:
        print("nada novo para agendar"); return 0
    slots = proximos_horarios(len(pend), cfg.get("horarios") or HORARIOS, cfg.get("fuso") or FUSO,
                              horarios_ocupados())
    for c, quando in zip(pend, slots):
        cid = str(c["id"]); legenda = (c.get("legenda") or c.get("titulo") or "").strip()
        feitas = []
        for rede in redes:
            if (cid, rede) in ja:
                continue
            item = {"id": cid, "rede": rede, "quando": quando.astimezone(timezone.utc).isoformat(),
                    "legenda": legenda}
            if rede == "tiktok":
                try:
                    item["buffer_id"] = buffer_postar(buf, canal["id"], legenda,
                                                      f"{MIDIA_BASE}/{job}/corte_{cid}_vertical.mp4", quando)
                    item["status"] = "agendado"
                except Exception as e:
                    print(f"ERRO_POSTAGEM {cid} tiktok: {e}"); continue
            else:
                item["status"] = "na_fila"
            fila["itens"].append(item); feitas.append(rede)
            gravar(fila_path, fila)
        if feitas:
            print(f"AGENDADO {cid} {quando.strftime('%d/%m %H:%M')} {','.join(feitas)}", flush=True)
    return 0


def rodar_fila():
    tok = os.environ.get("IG_TOKEN", "").strip()
    arquivos = sorted(glob.glob(os.path.join(PASTA_FILA, "*.json")))
    vencidos = [(f, i) for f in arquivos for i, it in enumerate(ler(f, {}).get("itens", []))
                if it["rede"] == "instagram" and it.get("status") == "na_fila"
                and datetime.fromisoformat(it["quando"]) <= agora()]
    if not tok:
        if vencidos:
            print("AVISO_SEM_CHAVE há Reels na fila mas falta o IG_TOKEN")
        return 0
    ig_cuidar_token(tok)
    if not vencidos:
        print("fila: nada na hora"); return 0
    uid, nome = ig_conta(tok)
    for f, i in vencidos:
        fila = ler(f, {}); it = fila["itens"][i]; job = fila["job"]
        atraso = agora() - datetime.fromisoformat(it["quando"])
        if atraso > timedelta(hours=20):
            it["status"] = "perdido"; gravar(f, fila)
            print(f"ERRO_POSTAGEM {job} {it['id']} instagram: horário passou há mais de 20 h (não postei)"); continue
        video = video_local(job, it["id"])
        try:
            if not video:
                raise RuntimeError("vídeo não encontrado na Release")
            it["link"] = ig_publicar(tok, uid, video, it.get("legenda", ""))
            it["status"] = "postado"; it["postado_em"] = agora().isoformat()
            print(f"POSTADO {job} {it['id']} instagram {it['link']}", flush=True)
        except Exception as e:
            it["tentativas"] = it.get("tentativas", 0) + 1
            if it["tentativas"] >= 3:
                it["status"] = "erro"
            it["erro"] = str(e)[:300]
            print(f"ERRO_POSTAGEM {job} {it['id']} instagram: {e}", flush=True)
        gravar(f, fila)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default="")
    ap.add_argument("--so", default="")
    ap.add_argument("--teste", action="store_true")
    ap.add_argument("--fila", action="store_true")
    a = ap.parse_args()
    rc = 0
    if a.job:
        rc = agendar(a.job, a.so, a.teste)
    if a.fila or not a.job:
        rc = rodar_fila() or rc
    sys.exit(rc)


if __name__ == "__main__":
    main()
