#!/usr/bin/env python3
"""
Legenda inteligente de um job inteiro (cortes de uma live ou um vídeo avulso), com a revisão do Claude no meio.

  rascunho --job J [--so 01,03] [--video LINK|release:tag/arquivo]
      Pega os cortes da Release J (corte_<id>_vertical.mp4; se já existir corte_<id>_limpo.mp4, usa esse;
      o renderizar.yml apaga o limpo quando refaz o corte),
      transcreve palavra por palavra, separa as vozes e escolhe a posição de cada bloco (sem cobrir personagem).
      Salva jobs/J/legendas/<id>.bruto.json e <id>.posicoes.jpg (o workflow faz o commit).
      Com --video: antes, coloca esse vídeo na Release J como corte_01_vertical.mp4 (vídeo avulso).

  gravar --job J [--so 01,03] [--estilo inteligente]
      Para cada jobs/J/legendas/<id>.json (que o Claude montou com legenda_inteligente.py montar):
      guarda o vídeo limpo como corte_<id>_limpo.mp4 (uma vez só) e publica o legendado como corte_<id>_vertical.mp4.

  direto --job J [--so] [--video] [--estilo]
      Atalho sem revisão: transcreve e grava direto (para quando ninguém vai revisar).

Opções (JSON em --opcoes): lang, prompt, falantes, topo_jogo, posicao, destaques, emojis, som.
Do cortes.json do job (se existir) vêm "vocabulario" (dicas para o Whisper) e "idioma".
"""
import argparse, glob, json, os, re, subprocess, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("GITHUB_REPOSITORY", "")


def gh(*args, check=True, **kw):
    return subprocess.run(["gh", *args], check=check, text=True, capture_output=True, **kw)


def assets(job):
    r = gh("api", f"repos/{REPO}/releases/tags/{job}", check=False)
    if r.returncode != 0:
        return None
    return {a["name"] for a in json.loads(r.stdout).get("assets", [])}


def garantir_release(job):
    if assets(job) is None:
        gh("release", "create", job, "--title", f"Legendas: {job}", "--notes", "Vídeos legendados automaticamente.")


def baixar(job, nome, pasta):
    os.makedirs(pasta, exist_ok=True)
    gh("release", "download", job, "-p", nome, "-D", pasta, "--clobber")
    return os.path.join(pasta, nome)


def subir(job, arquivo, nome=None):
    alvo = arquivo
    if nome and os.path.basename(arquivo) != nome:
        alvo = os.path.join(os.path.dirname(arquivo), nome)
        os.replace(arquivo, alvo)
    gh("release", "upload", job, alvo, "--clobber")
    return alvo


def video_avulso(job, fonte, pasta="entrada"):
    """Coloca um vídeo qualquer na Release do job como corte_01_vertical.mp4."""
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, "corte_01_vertical.mp4")
    if fonte.startswith("release:"):
        tag, arq = fonte[8:].split("/", 1)
        os.replace(baixar(tag, arq, pasta), destino)
    elif re.search(r"\.(mp4|mov|mkv|webm)(\?|$)", fonte):
        subprocess.run(["curl", "-sSL", "--fail", "-o", destino, fonte], check=True)
    else:
        subprocess.run(["yt-dlp", "-q", "--no-playlist", "-f", "bv*[height<=1920]+ba/b", "--merge-output-format",
                        "mp4", "-o", destino, fonte], check=True)
    garantir_release(job)
    subir(job, destino)
    print(f"vídeo avulso colocado na Release {job} como corte_01_vertical.mp4")


def ids_do_job(job, so):
    nomes = assets(job) or set()
    ids = sorted({m.group(1) for n in nomes for m in [re.match(r"corte_(.+?)_(?:vertical|limpo)\.mp4$", n)] if m})
    filtro = {x.strip() for x in so.split(",") if x.strip()}
    return [i for i in ids if not filtro or i in filtro], nomes


def clipe_limpo(job, cid, nomes, pasta):
    """Vídeo sem legenda do corte (o limpo guardado, se já houver; senão o vertical atual)."""
    nome = f"corte_{cid}_limpo.mp4" if f"corte_{cid}_limpo.mp4" in nomes else f"corte_{cid}_vertical.mp4"
    return baixar(job, nome, pasta), nome


def plano(job):
    p = os.path.join("jobs", job, "cortes.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def topo_do_corte(job, cid, nomes, op, pasta):
    if "topo_jogo" in op:
        return float(op["topo_jogo"])
    nome = f"corte_{cid}_vertical.layout.json"
    if nome in nomes:
        return float(json.load(open(baixar(job, nome, pasta)))["topo_jogo"])
    return 0.1


def cmd_rascunho(a, op):
    if a.video:
        video_avulso(a.job, a.video)
    ids, nomes = ids_do_job(a.job, a.so)
    if not ids:
        sys.exit(f"ERRO_LEGENDA nenhum corte na Release {a.job}")
    pl = plano(a.job)
    prompt = op.get("prompt") or pl.get("vocabulario", "")
    lang = op.get("lang") or pl.get("idioma", "pt")
    rc = 0
    for cid in ids:
        video, _ = clipe_limpo(a.job, cid, nomes, "entrada")
        topo = topo_do_corte(a.job, cid, nomes, op, "entrada")
        saida = os.path.join("jobs", a.job, "legendas", f"{cid}.bruto.json")
        cmd = [sys.executable, os.path.join(AQUI, "legenda_inteligente.py"), "transcrever", video, saida,
               "--lang", lang, "--topo-jogo", str(topo)]
        if prompt:
            cmd += ["--prompt", prompt]
        if op.get("falantes"):
            cmd += ["--falantes", str(op["falantes"])]
        print(f"== corte {cid} (área do jogo a partir de {topo:.2f})", flush=True)
        rc = subprocess.run(cmd).returncode or rc
    print("RASCUNHO_OK" if rc == 0 else "ERRO_LEGENDA algum corte falhou no rascunho")
    sys.exit(rc)


def gravar_um(a, cid, nomes, extra):
    limpo, nome_origem = clipe_limpo(a.job, cid, nomes, "entrada")
    if f"corte_{cid}_limpo.mp4" not in nomes:  # guarda o original sem legenda (para poder refazer)
        tmp = os.path.join("entrada", f"corte_{cid}_limpo.mp4")
        subprocess.run(["cp", limpo, tmp], check=True)
        subir(a.job, tmp)
    os.makedirs("saida_legenda", exist_ok=True)
    saida = os.path.join("saida_legenda", f"corte_{cid}_vertical.mp4")
    cmd = [sys.executable, os.path.join(AQUI, "legendar.py"), limpo, saida, "--estilo", a.estilo] + extra
    r = subprocess.run(cmd)
    if r.returncode != 0 or not os.path.exists(saida):
        print(f"ERRO_LEGENDA corte {cid}: não gravou (o vídeo na Release continua sem legenda)")
        return 1
    subir(a.job, saida)
    print(f"LEGENDADO {cid}")
    return 0


def cmd_gravar(a, op):
    ids, nomes = ids_do_job(a.job, a.so)
    rc, feitos = 0, 0
    for cid in ids:
        arq = os.path.join("jobs", a.job, "legendas", f"{cid}.json")
        if not os.path.exists(arq):
            print(f"pulando {cid}: falta {arq} (revisão do Claude)")
            continue
        rc = gravar_um(a, cid, nomes, ["--palavras", arq, "--blocos"]) or rc
        feitos += 1
    if not feitos:
        sys.exit(f"ERRO_LEGENDA nenhum jobs/{a.job}/legendas/<id>.json para gravar")
    sys.exit(rc)


def cmd_direto(a, op):
    if a.video:
        video_avulso(a.job, a.video)
    ids, nomes = ids_do_job(a.job, a.so)
    pl = plano(a.job)
    extra = ["--lang", op.get("lang") or pl.get("idioma", "pt")]
    if op.get("prompt") or pl.get("vocabulario"):
        extra += ["--prompt", op.get("prompt") or pl["vocabulario"]]
    if "posicao" in op:
        extra += ["--posicao", str(op["posicao"])]
    if op.get("destaques"):
        extra += ["--destaques", ",".join(op["destaques"]) if isinstance(op["destaques"], list) else op["destaques"]]
    if op.get("emojis"):
        extra += ["--emojis", json.dumps(op["emojis"], ensure_ascii=False)]
    if op.get("som"):
        extra += ["--som"]
    rc = 0
    for cid in ids:
        rc = gravar_um(a, cid, nomes, extra) or rc
    sys.exit(rc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("etapa", choices=["rascunho", "gravar", "direto"])
    ap.add_argument("--job", required=True)
    ap.add_argument("--so", default="")
    ap.add_argument("--video", default="")
    ap.add_argument("--estilo", default="inteligente")
    ap.add_argument("--opcoes", default="")
    a = ap.parse_args()
    op = json.loads(a.opcoes) if a.opcoes.strip() else {}
    {"rascunho": cmd_rascunho, "gravar": cmd_gravar, "direto": cmd_direto}[a.etapa](a, op)


if __name__ == "__main__":
    main()
