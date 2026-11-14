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

    # 2) layout automático: a webcam é procurada EM CADA CORTE (o streamer pode trocar de cena)
    layout = plano.get("layout", "auto")
    planos = {}
    if layout == "auto" and baixados:
        import cv2, facecam
        geral = None
        for c, ini, fim, base, bruto in baixados:
            cid = str(c.get("id"))
            p2 = dict(plano)
            try:
                r = facecam.detectar([bruto])
            except Exception as e:
                print("   detector falhou:", e); r = None
            if r is None:
                # sem rosto achado: se uma pessoa grande ocupa a câmera, é cena em tela cheia (retrato nela)
                try:
                    import cena
                    cxp = cena.pessoa_principal(bruto, max(0, ini - base), fim - base)
                except Exception as e:
                    print("   detector de pessoas falhou:", e); cxp = None
                if cxp is not None:
                    r = {"metodo": "tela_cheia", "cx": cxp, "debug": None}
            if r is None:
                if geral is None:
                    try:
                        geral = facecam.detectar([b[4] for b in baixados]) or False
                    except Exception:
                        geral = False
                r = geral or None
            if r and r["metodo"] == "tela_cheia":
                p2["layout"] = "retrato"; p2["retrato_cx"] = r["cx"]
            elif r:
                p2["layout"] = "facecam"; p2["facecam"] = {k: r[k] for k in ("x", "y", "w", "h")}
            else:
                p2["layout"] = "blur"
            if r and r.get("debug") is not None:
                cv2.imwrite(os.path.join(saida, f"facecam_{cid}.jpg"), r["debug"])
            print(f"   corte {cid}: layout {p2['layout']} {p2.get('facecam', '')}", flush=True)
            planos[cid] = p2
    # um corte pode forçar o próprio layout no cortes.json ("layout", "facecam", "zoom")
    for c in plano["cortes"]:
        cid = str(c.get("id"))
        base_p = planos.get(cid, dict(plano))
        for k in ("layout", "facecam", "zoom", "retrato_cx", "janela", "cortar_vazio", "chamada"):
            if k in c:
                base_p[k] = c[k]
        planos[cid] = base_p

    # 2b) cena: chamada de vídeo (enquadrar quem está do outro lado) e câmera vazia (cortar)
    editados = {}
    for c, ini, fim, base, bruto in baixados:
        cid = str(c.get("id"))
        p2 = planos[cid]
        a, b = ini - base, fim - base
        info = {"layout": p2.get("layout")}
        try:
            import cena
            sw, sh = cortar.sondar(bruto)
            if p2.get("layout") == "retrato" and not p2.get("janela") and p2.get("chamada", True):
                jan = cena.achar_chamada(bruto, a, b, debug=os.path.join(saida, f"chamada_{cid}.jpg"))
                if jan:
                    p2["layout"], p2["janela"] = "chamada", {k: jan[k] for k in ("x", "y", "w", "h")}
                    print(f"   corte {cid}: CHAMADA na janela {p2['janela']} -> chamada em cima, streamer embaixo", flush=True)
            if p2.get("layout") == "chamada" and p2.get("janela") and "retrato_cx" not in c:
                # janela atrás do streamer: a parte de baixo usa só o que fica acima dela (recorte estreito),
                # então enquadra pelo rosto de quem está no estúdio
                if cortar.geo_chamada(p2, sw, sh)[4] < sh:
                    cxr = cena.rosto_acima(bruto, a, b, p2["janela"]["y"], fora=p2["janela"])
                    if cxr is not None:
                        p2["retrato_cx"] = cxr
                        print(f"   corte {cid}: streamer enquadrado pelo rosto (x={cxr})", flush=True)
            info.update(layout=p2.get("layout"), janela=p2.get("janela"))
            # câmera vazia: padrão nas cenas de câmera (IRL); no layout de jogo+webcam só se pedir
            if p2.get("cortar_vazio", p2.get("layout") in ("retrato", "chamada")):
                reg = cortar.regiao_principal(p2, sw, sh)
                if reg:
                    falas = [(f["start"] - base, f["end"] - base) for f in trans if f["end"] > ini and f["start"] < fim]
                    rem, linha = cena.tempo_morto(bruto, a, b, reg, falas)
                    info["presenca"] = "".join("#" if ok else "." for _, ok in linha)
                    if rem:
                        ed = os.path.join(tmp, f"editado_{cid}.mp4")
                        manter = cena.aplicar_cortes(bruto, a, b, rem, ed)
                        editados[cid] = (ed, manter)
                        info["removidos"] = [[round(x - a, 1), round(y - a, 1)] for x, y in rem]
                        tot = sum(y - x for x, y in rem)
                        print(f"   corte {cid}: CAMERA_VAZIA removido " +
                              ", ".join(f"{x - a:.1f}-{y - a:.1f}s" for x, y in rem) + f" ({tot:.1f}s)", flush=True)
        except Exception as e:
            print(f"   análise de cena do corte {cid} falhou (segue sem): {e}", flush=True)
        with open(os.path.join(saida, f"corte_{cid}.cena.json"), "w") as f:
            json.dump(info, f, ensure_ascii=False)

    # 3) renderiza
    for c, ini, fim, base, bruto in baixados:
        cid = str(c.get("id"))
        try:
            c2 = copy.deepcopy(c); c2["inicio"] = ini - base; c2["fim"] = fim - base
            t2 = []
            for f in trans:
                if f["end"] > ini - 1 and f["start"] < fim + 1:
                    g = dict(f); g["start"] -= base; g["end"] -= base; t2.append(g)
            if cid in editados:  # trechos de câmera vazia já tirados: o vídeo editado começa no início do corte
                import cena
                bruto, manter = editados[cid]
                c2["inicio"], c2["fim"] = 0.0, sum(y - x for x, y in manter)
                t3 = []
                for g in t2:
                    s0, e0 = cena.remapear_perto(g["start"], manter), cena.remapear_perto(g["end"], manter)
                    if e0 - s0 > 0.05:
                        g = dict(g); g["start"], g["end"] = s0, e0; t3.append(g)
                t2 = t3
            sw, sh = cortar.sondar(bruto)
            for fo in formatos:
                print("   ok", cortar.render(bruto, c2, planos.get(cid, plano), t2, saida, fo, sw, sh), flush=True)
        except Exception as e:  # um corte com erro não derruba os outros
            print(f"   FALHOU corte {cid}: {e}", flush=True); falhas.append(cid)

    if falhas:
        print("cortes com falha:", ",".join(falhas))
        if len(falhas) >= len(escolhidos):
            sys.exit(1)


if __name__ == "__main__":
    main()
