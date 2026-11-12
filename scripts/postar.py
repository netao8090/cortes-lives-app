#!/usr/bin/env python3
"""
Posta sozinho os cortes no TikTok e no Instagram (Reels) pela API grátis do Buffer.

Cada corte ganha um horário de pico (12h, 15h, 18h, 21h de Brasília) e é agendado no Buffer,
nas duas redes, no mesmo horário. O plano grátis do Buffer aceita só 10 posts esperando por rede;
o que passar disso fica na "reserva" (estado/fila/<job>.json) e o workflow, de hora em hora,
empurra para o Buffer conforme a fila vai esvaziando.

Modos:
  --job J [--so 01,02]   agenda os cortes do job
  --job J --teste        confere as contas com o 1º corte: vira RASCUNHO no Buffer (nada publicado)
  --fila                 empurra a reserva para o Buffer quando abre vaga
  --midia-necessaria     imprime os vídeos que precisam continuar no link público (branch midia)

Segredo: BUFFER_API_KEY (publish.buffer.com/settings/api)
Textos:  jobs/J/postagem.json  {"cortes":[{"id","titulo","legenda","descricao"}], opcionais:
         "horarios":["12:00",...], "fuso":"America/Sao_Paulo", "redes":["tiktok","instagram"]}

Linhas que o Claude procura no log: AGENDADO, RESERVA, ENVIADO_DA_RESERVA, TESTE_OK, ERRO_POSTAGEM,
AVISO_SEM_CHAVE, AVISO_SEM_REDE, BUFFER_CAMPOS.
"""
import argparse, glob, json, os, re, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

BUFFER_API = os.environ.get("BUFFER_API", "https://api.buffer.com")
REPO = os.environ.get("GITHUB_REPOSITORY", "netao8090/cortes-lives-app")
MIDIA_BASE = os.environ.get("MIDIA_BASE") or f"https://raw.githubusercontent.com/{REPO}/midia"
LIMITE_FILA = int(os.environ.get("LIMITE_FILA", "10"))
REDES = ["tiktok", "instagram"]
HORARIOS = ["12:00", "15:00", "18:00", "21:00"]
FUSO = "America/Sao_Paulo"
PASTA_FILA = "estado/fila"


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


def todas_filas():
    return {f: ler(f, {"itens": []}) for f in sorted(glob.glob(os.path.join(PASTA_FILA, "*.json")))}


def url_video(job, cid):
    return f"{MIDIA_BASE}/{job}/corte_{cid}_vertical.mp4"


# ---------------------------------------------------------------- horários
def ocupados(filas, rede):
    return {it["quando"][:16] for fl in filas.values() for it in fl["itens"]
            if it["rede"] == rede and it.get("status") != "erro"}


def proximo_horario(horarios, fuso, usados, base=None):
    tz = ZoneInfo(fuso)
    base = (base or agora()).astimezone(tz) + timedelta(minutes=20)
    dia = base.date()
    while True:
        for h in sorted(horarios):
            hh, mm = map(int, h.split(":"))
            t = datetime(dia.year, dia.month, dia.day, hh, mm, tzinfo=tz)
            if t >= base and t.astimezone(timezone.utc).isoformat()[:16] not in usados:
                return t
        dia += timedelta(days=1)


def esperando_no_buffer(filas, rede):
    return sum(1 for fl in filas.values() for it in fl["itens"]
               if it["rede"] == rede and it.get("status") == "agendado"
               and datetime.fromisoformat(it["quando"]) > agora())


# ---------------------------------------------------------------- Buffer
class BufferErro(RuntimeError):
    pass


def literal(v, enums=(), chave=""):
    """dict → literal de input GraphQL (enums sem aspas), sem depender do nome exato dos tipos."""
    if isinstance(v, dict):
        return "{" + ",".join(f"{k}:{literal(x, enums, k)}" for k, x in v.items()) + "}"
    if isinstance(v, list):
        return "[" + ",".join(literal(x, enums) for x in v) + "]"
    if isinstance(v, bool):
        return "true" if v else "false"
    if chave in enums:
        return str(v)
    return json.dumps(v, ensure_ascii=False)


class Buffer:
    def __init__(self, chave):
        self.chave = chave
        self._ig_meta = None

    def gql(self, query):
        r = requests.post(BUFFER_API, timeout=120, json={"query": query},
                          headers={"Authorization": f"Bearer {self.chave}", "Content-Type": "application/json"})
        if r.status_code in (401, 403):
            raise BufferErro(f"chave do Buffer recusada (HTTP {r.status_code})")
        if not r.ok:
            raise BufferErro(f"Buffer HTTP {r.status_code}: {r.text[:300]}")
        j = r.json()
        if j.get("errors"):
            raise BufferErro("; ".join(e.get("message", "") for e in j["errors"])[:400])
        return j["data"]

    def canais(self):
        """{rede: canal} com o primeiro canal de cada rede conectado no Buffer."""
        achados = {}
        for o in self.gql("query{account{organizations{id name}}}")["account"]["organizations"]:
            for c in self.gql("query{channels(input:%s){id name service}}"
                              % literal({"organizationId": o["id"]}))["channels"]:
                s = (c.get("service") or "").lower()
                if s in REDES and s not in achados:
                    achados[s] = c
        return achados

    def tipo(self, nome):
        q = 'query{__type(name:%s){inputFields{name type{name kind ofType{name kind}}}}}' % json.dumps(nome)
        return (self.gql(q).get("__type") or {}).get("inputFields") or []

    def enum(self, nome):
        q = 'query{__type(name:%s){enumValues{name}}}' % json.dumps(nome)
        return [e["name"] for e in ((self.gql(q).get("__type") or {}).get("enumValues") or [])]

    def meta_instagram(self):
        """Descobre na própria API como marcar o post do Instagram como Reel (e compartilhar no feed)."""
        if self._ig_meta is not None:
            return self._ig_meta
        meta, enums = {}, set()
        try:
            for f in self.tipo("InstagramPostMetadataInput"):
                t = f["type"]; base = t.get("ofType") or t
                if base.get("kind") == "ENUM":
                    reel = [v for v in self.enum(base["name"]) if v.lower() == "reel"]
                    if reel:
                        meta[f["name"]] = reel[0]; enums.add(f["name"])
                elif base.get("name") == "Boolean" and "feed" in f["name"].lower():
                    meta[f["name"]] = True
        except BufferErro as e:
            print(f"BUFFER_CAMPOS não deu para ler os campos do Instagram: {e}")
        self._ig_meta = (meta, enums)
        return self._ig_meta

    def campos(self):
        try:
            a = ",".join(f["name"] for f in self.tipo("CreatePostInput"))
            b = ",".join(f["name"] for f in self.tipo("InstagramPostMetadataInput"))
            c = ",".join(f["name"] for f in self.tipo("TikTokPostMetadataInput"))
            print(f"BUFFER_CAMPOS CreatePostInput={a} | Instagram={b} | TikTok={c}")
        except Exception as e:
            print(f"BUFFER_CAMPOS indisponível: {e}")

    def postar(self, rede, canal_id, texto, url, quando=None, teste=False):
        entrada = {"text": texto[:2200], "channelId": canal_id, "schedulingType": "automatic",
                   "assets": [{"video": {"url": url}}]}
        enums = {"schedulingType", "mode"}
        if rede == "instagram":
            meta, en = self.meta_instagram()
            if meta:
                entrada["metadata"] = {"instagram": meta}; enums |= en
        if teste:
            entrada.update(mode="addToQueue", saveToDraft=True)
        else:
            entrada.update(mode="customScheduled",
                           dueAt=quando.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
        q = ("mutation{createPost(input:%s){... on PostActionSuccess{post{id}} "
             "... on MutationError{message}}}") % literal(entrada, enums)
        try:
            res = self.gql(q)["createPost"]
        except BufferErro:
            self.campos(); raise
        if res.get("message") or not res.get("post"):
            raise BufferErro(res.get("message") or "resposta vazia")
        return res["post"]["id"]


def fila_cheia(msg):
    return bool(re.search(r"limit|queue|full|maximum|upgrade", msg, re.I))


# ---------------------------------------------------------------- modos
def preparar():
    chave = os.environ.get("BUFFER_API_KEY", "").strip()
    if not chave:
        print("AVISO_SEM_CHAVE postagem não configurada (falta o segredo BUFFER_API_KEY)")
        return None, {}
    buf = Buffer(chave)
    try:
        canais = buf.canais()
    except BufferErro as e:
        print(f"ERRO_POSTAGEM buffer: {e}"); return None, {}
    for r in REDES:
        if r in canais:
            print(f"{r}={canais[r].get('name')}")
        else:
            print(f"AVISO_SEM_REDE {r} não está conectado no Buffer")
    return buf, canais


def enviar(buf, canais, filas, f, it, job):
    """Tenta agendar um item no Buffer; se a fila de 10 estiver cheia, deixa na reserva."""
    rede = it["rede"]
    if esperando_no_buffer(filas, rede) >= LIMITE_FILA:
        it["status"] = "reserva"; return "reserva"
    try:
        it["buffer_id"] = buf.postar(rede, canais[rede]["id"], it["legenda"], url_video(job, it["id"]),
                                     datetime.fromisoformat(it["quando"]))
        it["status"] = "agendado"; it.pop("erro", None); return "agendado"
    except BufferErro as e:
        if fila_cheia(str(e)):
            it["status"] = "reserva"; return "reserva"
        it["tentativas"] = it.get("tentativas", 0) + 1
        it["erro"] = str(e)[:300]
        it["status"] = "erro" if it["tentativas"] >= 3 else "reserva"
        print(f"ERRO_POSTAGEM {job} {it['id']} {rede}: {e}")
        return "erro"


def agendar(job, so, teste):
    buf, canais = preparar()
    if not buf:
        return 0
    cfg = ler(os.path.join("jobs", job, "postagem.json"), None)
    if not cfg:
        print(f"ERRO_POSTAGEM falta jobs/{job}/postagem.json"); return 1
    redes = [r for r in REDES if r in canais and (not cfg.get("redes") or r in cfg["redes"])]
    if not redes:
        return 1
    filtro = {s.strip() for s in so.split(",") if s.strip()}
    cortes = [c for c in cfg.get("cortes", []) if not filtro or str(c["id"]) in filtro]
    if not cortes:
        print("ERRO_POSTAGEM nenhum corte em postagem.json"); return 1

    if teste:
        c = cortes[0]; falhou = 0
        for rede in redes:
            try:
                buf.postar(rede, canais[rede]["id"], c.get("legenda", ""), url_video(job, c["id"]), teste=True)
                print(f"TESTE_OK {rede}: rascunho criado no Buffer (nada publicado; pode apagar)")
            except BufferErro as e:
                falhou = 1; print(f"ERRO_POSTAGEM teste {rede}: {e}"); buf.campos()
        return falhou

    f = os.path.join(PASTA_FILA, f"{job}.json")
    filas = todas_filas()
    fila = filas.setdefault(f, {"job": job, "itens": []})
    fila["job"] = job
    ja = {(it["id"], it["rede"]) for it in fila["itens"]}
    fuso, horarios = cfg.get("fuso") or FUSO, cfg.get("horarios") or HORARIOS
    rc = 0
    for c in cortes:
        cid = str(c["id"]); legenda = (c.get("legenda") or c.get("titulo") or "").strip()
        faltam = [r for r in redes if (cid, r) not in ja]
        if not faltam:
            continue
        usados = set().union(*(ocupados(filas, r) for r in faltam))
        quando = proximo_horario(horarios, fuso, usados)
        res = {}
        for rede in faltam:
            it = {"id": cid, "rede": rede, "quando": quando.astimezone(timezone.utc).isoformat(),
                  "legenda": legenda}
            fila["itens"].append(it)
            res[rede] = enviar(buf, canais, filas, f, it, job)
            gravar(f, fila)
        ag = [r for r, s in res.items() if s == "agendado"]
        rs = [r for r, s in res.items() if s == "reserva"]
        hora = quando.strftime("%d/%m %H:%M")
        if ag:
            print(f"AGENDADO {cid} {hora} {','.join(ag)}", flush=True)
        if rs:
            print(f"RESERVA {cid} {hora} {','.join(rs)} (fila do Buffer cheia; entra sozinho quando vagar)", flush=True)
        if any(s == "erro" for s in res.values()):
            rc = 1
    return rc


def rodar_fila():
    filas = todas_filas()
    pend = [(f, it) for f, fl in filas.items() for it in fl["itens"] if it.get("status") == "reserva"]
    if not pend:
        print("fila: reserva vazia"); return 0
    buf, canais = preparar()
    if not buf:
        return 0
    pend.sort(key=lambda x: x[1]["quando"])
    mudou = set()
    for f, it in pend:
        if it["rede"] not in canais:
            continue
        job = filas[f]["job"]
        if datetime.fromisoformat(it["quando"]) < agora() + timedelta(minutes=15):
            # o horário original passou enquanto esperava vaga: pega o próximo livre desta rede
            cfg = ler(os.path.join("jobs", job, "postagem.json"), {})
            novo = proximo_horario(cfg.get("horarios") or HORARIOS, cfg.get("fuso") or FUSO,
                                   ocupados(filas, it["rede"]))
            it["quando"] = novo.astimezone(timezone.utc).isoformat()
        st = enviar(buf, canais, filas, f, it, job)
        mudou.add(f)
        if st == "agendado":
            q = datetime.fromisoformat(it["quando"]).astimezone(ZoneInfo(FUSO)).strftime("%d/%m %H:%M")
            print(f"ENVIADO_DA_RESERVA {job} {it['id']} {it['rede']} {q}", flush=True)
    for f in mudou:
        gravar(f, filas[f])
    return 0


def midia_necessaria(job_novo=""):
    """Vídeos que o Buffer ainda vai buscar: reserva, ou agendado até 1 dia depois do horário."""
    precisa = set()
    for fl in todas_filas().values():
        for it in fl["itens"]:
            st = it.get("status")
            if st == "reserva" or (st == "agendado" and
                                   datetime.fromisoformat(it["quando"]) > agora() - timedelta(days=1)):
                precisa.add(f"{fl['job']}/corte_{it['id']}_vertical.mp4")
    if job_novo:
        for p in glob.glob(os.path.join("saida", job_novo, "corte_*_vertical.mp4")):
            precisa.add(f"{job_novo}/{os.path.basename(p)}")
    print("\n".join(sorted(precisa)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default="")
    ap.add_argument("--so", default="")
    ap.add_argument("--teste", action="store_true")
    ap.add_argument("--fila", action="store_true")
    ap.add_argument("--midia-necessaria", action="store_true")
    a = ap.parse_args()
    if a.midia_necessaria:
        midia_necessaria(a.job); return
    rc = agendar(a.job, a.so, a.teste) if a.job else 0
    if a.fila or not a.job:
        rc = rodar_fila() or rc
    sys.exit(rc)


if __name__ == "__main__":
    main()
