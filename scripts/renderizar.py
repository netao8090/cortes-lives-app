#!/usr/bin/env python3
"""
Renderiza os cortes de um job: baixa SÓ os trechos escolhidos (não a live inteira) e gera os vídeos.

  renderizar.py --job J [--so 01,03]
Lê jobs/J/meta.json, jobs/J/cortes.json, jobs/J/transcricao.json  ->  saida/J/

Layout (cortes.json -> "layout"):
  "auto"    (padrão) acha a webcam do streamer sozinho; se achar, câmera em cima + jogo embaixo,
            senão jogo inteiro com fundo desfocado. Salva saida/J/facecam_detectada.jpg para conferência.
  "facecam" usa a caixa "facecam": {"x","y","w","h"} informada.
  "blur"    sempre jogo inteiro com fundo desfocado.
"""
import argparse, copy, json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cortar  # noqa: E402

PRE, POS = 3.0, 2.0  # folga baixada antes/depois de cada corte


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--so", default="")
    a = ap.parse_args()
    pasta = os.path.join("jobs", a.job)
    meta = json.load(open(os.path.join(pasta, "meta.json"), encoding="utf-8"))
    plano = json.load(open(os.path.join(pasta, "cortes.json"), encoding="utf-8"))
    tpath = os.path.join(pasta, "transcricao.json")
    trans = json.load(open(tpath, encoding="utf-8")) if os.path.exists(tpath) else []
    saida = os.path.abspath(os.path.join("saida", a.job))
    tmp = os.path.abspath(os.path.join("tmp", a.job))
    os.makedirs(saida, exist_ok=True); os.makedirs(tmp, exist_ok=True)
    ids = set(x for x in a.so.split(",") if x)
    formatos = ["vertical", "horizontal"] if plano.get("formato") == "ambos" else [plano.get("formato", "vertical")]
    escolhidos = [c for c in plano["cortes"] if not ids or str(c.get("id")) in ids]

    # 1) baixa todos os trechos
    falhas, baixados = [], []
    for c in escolhidos:
        cid = str(c.get("id"))
        ini, fim = cortar.seg(c["inicio"]), cortar.seg(c["fim"])
        base = max(ini - PRE, 0)
        bruto = os.path.join(tmp, f"bruto_{cid}.mp4")
        print(f"== corte {cid}: {ini:.1f}-{fim:.1f}s  baixando trecho...", flush=True)
        try:
            if not os.path.exists(bruto):
                subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "baixar.py"),
                                "trecho", meta["url"], f"{base:.2f}", f"{fim + POS:.2f}", bruto], check=True)
            baixados.append((c, ini, fim, base, bruto))
        except Exception as e:
            print(f"   FALHOU download {cid}: {e}", flush=True); falhas.append(cid)

    # 2) layout automático: procura a webcam olhando todos os trechos juntos
    layout = plano.get("layout", "auto")
    if layout == "auto" and baixados:
        try:
            import cv2, facecam
            r = facecam.detectar([b[4] for b in baixados])
        except Exception as e:
            print("   detector de facecam falhou:", e); r = None
        if r:
            cv2.imwrite(os.path.join(saida, "facecam_detectada.jpg"), r["debug"])
            plano["layout"] = "facecam"
            plano["facecam"] = {k: r[k] for k in ("x", "y", "w", "h")}
            print(f"   webcam encontrada ({r['metodo']}): {plano['facecam']}", flush=True)
        else:
            plano["layout"] = "blur"
            print("   webcam não encontrada -> layout com fundo desfocado", flush=True)

    # 3) renderiza
    for c, ini, fim, base, bruto in baixados:
        cid = str(c.get("id"))
        try:
            c2 = copy.deepcopy(c); c2["inicio"] = ini - base; c2["fim"] = fim - base
            t2 = []
            for f in trans:
                if f["end"] > ini - 1 and f["start"] < fim + 1:
                    g = dict(f); g["start"] -= base; g["end"] -= base; t2.append(g)
            sw, sh = cortar.sondar(bruto)
            for fo in formatos:
                print("   ok", cortar.render(bruto, c2, plano, t2, saida, fo, sw, sh), flush=True)
        except Exception as e:  # um corte com erro não derruba os outros
            print(f"   FALHOU corte {cid}: {e}", flush=True); falhas.append(cid)

    if falhas:
        print("cortes com falha:", ",".join(falhas))
        if len(falhas) >= len(escolhidos):
            sys.exit(1)


if __name__ == "__main__":
    main()
