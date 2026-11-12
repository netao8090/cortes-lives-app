#!/usr/bin/env python3
"""
Renderiza os cortes de um job: baixa SÓ os trechos escolhidos (não a live inteira) e gera os vídeos.

  renderizar.py --job J [--so 01,03]
Lê jobs/J/meta.json, jobs/J/cortes.json, jobs/J/transcricao.json  ->  saida/J/
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

    falhas = []
    for c in plano["cortes"]:
        cid = str(c.get("id"))
        if ids and cid not in ids:
            continue
        ini, fim = cortar.seg(c["inicio"]), cortar.seg(c["fim"])
        base = max(ini - PRE, 0)
        bruto = os.path.join(tmp, f"bruto_{cid}.mp4")
        print(f"== corte {cid}: {ini:.1f}-{fim:.1f}s  baixando trecho...", flush=True)
        try:
            if not os.path.exists(bruto):
                subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "baixar.py"), "trecho",
                                meta["url"], f"{base:.2f}", f"{fim + POS:.2f}", bruto], check=True)
            # desloca tempos para o arquivo baixado
            c2 = copy.deepcopy(c); c2["inicio"] = ini - base; c2["fim"] = fim - base
            t2 = []
            for f in trans:
                if f["end"] > ini - 1 and f["start"] < fim + 1:
                    g = dict(f); g["start"] -= base; g["end"] -= base; t2.append(g)
            sw, sh = cortar.sondar(bruto)
            for fo in formatos:
                print("   ok", cortar.render(bruto, c2, plano, t2, saida, fo, sw, sh), flush=True)
        except Exception as e:  # um corte com erro não derruba os outros
            print(f"   FALHOU corte {cid}: {e}", flush=True)
            falhas.append(cid)
    if falhas:
        print("cortes com falha:", ",".join(falhas))
        sys.exit(1 if len(falhas) == len([c for c in plano["cortes"] if not ids or str(c.get('id')) in ids]) else 0)


if __name__ == "__main__":
    main()
