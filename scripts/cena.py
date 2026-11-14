#!/usr/bin/env python3
"""
Análise de cena de um corte (usa o detector de pessoas YOLOX que a legenda já usa).

1. Janela de chamada (Ome.tv, Discord, FaceTime...): numa cena de câmera em tela cheia (IRL), acha a
   janelinha sobreposta onde aparece a pessoa do outro lado da chamada. O corte vira layout "chamada":
   a janela em cima e o streamer embaixo, os dois enquadrados.
2. Câmera vazia: acha os trechos em que ninguém aparece na câmera (o streamer saiu) e ninguém fala;
   esses trechos são cortados do vídeo (corte seco).

  python3 cena.py chamada VIDEO --ini 0 --fim 60 [--debug saida.jpg]
  python3 cena.py vazio VIDEO --ini 0 --fim 60 --regiao x,y,w,h
"""
import argparse, json, os, subprocess, sys
import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from posicao_legenda import Detector  # noqa: E402

LARG = 960  # largura usada na análise (rápido e suficiente)
_DET = None


def detector():
    global _DET
    if _DET is None:
        _DET = Detector()
    return _DET


def dimensoes(video):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", video], capture_output=True, text=True)
    w, h = r.stdout.strip().split("\n")[0].split(",")[:2]
    return int(w), int(h)


def quadros(video, ini, fim, fps):
    """Quadros (t, imagem BGR em LARG px de largura) entre ini e fim, `fps` por segundo."""
    sw, sh = dimensoes(video)
    h = int(round(sh * LARG / sw / 2)) * 2
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{ini:.3f}", "-t", f"{fim - ini:.3f}", "-i", video,
                          "-vf", f"fps={fps},scale={LARG}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                         stdout=subprocess.PIPE)
    n, tam = 0, LARG * h * 3
    while True:
        buf = p.stdout.read(tam)
        if len(buf) < tam:
            break
        yield ini + (n + 0.5) / fps, np.frombuffer(buf, np.uint8).reshape(h, LARG, 3)
        n += 1
    p.wait()


def pessoas(img, conf=0.4):
    return [o["box"] for o in detector().detectar(img, conf=conf) if o["cls"] == 0]


# ------------------------------------------------------------------ 1. janela de chamada
def _bordas(frames):
    ex, ey = [], []
    for f in frames:
        g = cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (3, 3), 0).astype(np.float32)
        ex.append(np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)))
        ey.append(np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)))
    return np.median(np.stack(ex), 0), np.median(np.stack(ey), 0)


def _forca_v(Ex, c, y0, y1):
    H, W = Ex.shape
    c, y0, y1 = int(c), int(max(0, y0)), int(min(H, y1))
    if c <= 0 or c >= W - 1:
        return 999.0  # borda da tela conta como borda perfeita
    if y1 - y0 < 8:
        return 0.0
    return float(np.percentile(Ex[y0:y1, max(0, c - 1):c + 2].max(1), 20))


def _forca_h(Ey, r, x0, x1):
    H, W = Ey.shape
    r, x0, x1 = int(r), int(max(0, x0)), int(min(W, x1))
    if r <= 0 or r >= H - 1:
        return 999.0
    if x1 - x0 < 8:
        return 0.0
    return float(np.percentile(Ey[max(0, r - 1):r + 2, x0:x1].max(0), 20))


def _picos(vals, n=6, minimo=25.0):
    """Posições com força alta (máximos locais), as n mais fortes."""
    out = []
    for i, (p, v) in enumerate(vals):
        viz = [x[1] for x in vals[max(0, i - 3):i + 4]]
        if v >= minimo and v == max(viz):
            out.append((p, v))
    return sorted(out, key=lambda t: -t[1])[:n]


def _extensao(Ey, r, x_ini, thr=22, folga=10):
    """Até onde a linha horizontal da linha r vai para a esquerda e para a direita, partindo de x_ini."""
    H, W = Ey.shape
    faixa = Ey[max(0, r - 1):r + 2].max(0)
    def andar(passo):
        x, gap, ultimo = int(x_ini), 0, int(x_ini)
        while 0 <= x < W:
            if faixa[x] >= thr:
                ultimo, gap = x, 0
            else:
                gap += 1
                if gap > folga:
                    break
            x += passo
        return ultimo
    return andar(-1), andar(1)


def _avaliar_janela(Ex, Ey, por_quadro, pessoa, r, xa, xb, nq):
    """Confere uma janela candidata (topo r, laterais xa/xb). Devolve ((x, y, w, h), nota) ou None."""
    H, W = Ey.shape
    bx0, by0, bx1, by1 = pessoa
    bw, bh = bx1 - bx0, by1 - by0
    dbg = os.environ.get("CENA_DEBUG")
    if xa > bx0 + 0.15 * bw or xb < bx1 - 0.15 * bw:
        return None
    if by1 > 0.88 * H:
        fundo = H
    else:
        baixo = _picos([(y, _forca_h(Ey, y, xa, xb)) for y in range(int(by1 - 3), int(by1 + 0.6 * bh), 2) if 0 < y < H],
                       n=1, minimo=30)
        if not baixo:
            return None
        fundo = baixo[0][0]
    w, h = xb - xa, fundo - r
    if w < 0.12 * W or h < 0.15 * H:
        return None
    area = w * h / (W * H)
    if not 0.03 <= area <= 0.45 or not 0.7 <= w / h <= 2.8:
        return None
    forca_topo = _forca_h(Ey, r, xa, xb)
    if forca_topo < 30:
        return None
    # quem está dentro da janela, inteiro; quem atravessa a borda não pode existir (seria cena, não janela)
    dentro = atravessa = 0
    for q in por_quadro:
        ok_q = cruza_q = False
        for x0, y0, x1, y1 in q:
            ix = max(0, min(xb, x1) - max(xa, x0)) * max(0, min(fundo, y1) - max(r, y0))
            ab = (x1 - x0) * (y1 - y0)
            if not ab or not ix:
                continue
            tx, ty = max(8, 0.12 * (x1 - x0)), max(6, 0.06 * (y1 - y0))  # a caixa do detector varia um pouco
            if y0 >= r - ty and x0 >= xa - tx and x1 <= xb + tx and y1 <= fundo + 8:
                ok_q = True
            elif ix >= 0.35 * ab and ab - ix >= 0.25 * ab:
                cruza_q = True
        dentro += ok_q
        atravessa += cruza_q
    sup, cru = dentro / nq, atravessa / nq
    if sup < 0.3 or cru > 0.3:
        if dbg:
            print("  recusada", (int(xa), int(r), int(w), int(h)), "dentro", round(sup, 2), "cruza", round(cru, 2))
        return None
    lados = [_forca_v(Ex, xa, r, fundo), _forca_v(Ex, xb, r, fundo)]
    # janela de verdade: a borda de cima fica logo acima da cabeça de quem está na chamada
    folga_cabeca = max(0.0, by0 - r) / H * 540
    nota = (min(forca_topo, 90) + 0.3 * sum(min(v, 120) for v in lados) + 60 * sup - 80 * cru - 30 * area
            - 0.35 * folga_cabeca + 40 * w / W)
    if dbg:
        print("  candidata", (int(xa), int(r), int(w), int(h)), "topo", round(forca_topo), "lados",
              [round(v) for v in lados], "dentro", round(sup, 2), "cruza", round(cru, 2), "nota", round(nota))
    return (xa, r, w, h), nota


def achar_chamada(video, ini, fim, n=14, debug=None):
    """Janela de chamada sobreposta (presa embaixo ou num canto de baixo) com uma pessoa dentro.
    Devolve {"x","y","w","h"} em pixels do vídeo original, ou None."""
    sw, sh = dimensoes(video)
    passo = max((fim - ini) / n, 0.5)
    frames = [f for _, f in quadros(video, ini, fim, 1.0 / passo)][:n]
    if len(frames) < 3:
        return None
    H, W = frames[0].shape[:2]
    Ex, Ey = _bordas(frames)
    por_quadro = [pessoas(f) for f in frames]
    todas = [b for q in por_quadro for b in q]
    melhor, nota_melhor = None, -1e9
    vistos = []
    for bx0, by0, bx1, by1 in todas:
        bw, bh = bx1 - bx0, by1 - by0
        if bh > 0.8 * H or bw < 0.04 * W:
            continue
        if any(abs(bx0 - v[0]) < 20 and abs(by0 - v[1]) < 20 for v in vistos):
            continue
        vistos.append((bx0, by0))
        # linha de cima da janela: acima da cabeça (ou rente a ela)
        topos = _picos([(r, _forca_h(Ey, r, bx0, bx1)) for r in range(int(by0 + 3), int(by0 - 0.9 * bh), -2) if 0 < r < H],
                       n=8, minimo=35)
        # linhas vizinhas (±6 px) também: duas bordas paralelas próximas se escondem uma atrás da outra
        linhas = sorted({rr for r, _ in topos for rr in range(r - 6, r + 7) if 0 < rr < H})
        cx_int = (bx0 + bx1) / 2
        for r in linhas:
            xa0, xb0 = _extensao(Ey, r, cx_int)
            if xa0 <= 3: xa0 = 0
            if xb0 >= W - 4: xb0 = W
            # a linha pode emendar em outra borda da cena; quem está atrás da janela aparece cortado
            # na lateral dela, então uma 2ª versão da janela fecha a lateral onde essas pessoas terminam
            xa1, xb1 = xa0, xb0
            for x0, y0, x1, y1 in todas:
                if y1 <= r + 4 or (x0 >= bx0 - 4 and x1 <= bx1 + 4 and y0 >= by0 - 4):
                    continue
                if (x0 + x1) / 2 < cx_int and xa1 < x1 <= bx0 + 0.15 * bw:
                    xa1 = x1
                elif (x0 + x1) / 2 > cx_int and bx1 - 0.15 * bw <= x0 < xb1:
                    xb1 = x0
            for xa, xb in {(xa0, xb0), (xa1, xb1)}:
                c = _avaliar_janela(Ex, Ey, por_quadro, (bx0, by0, bx1, by1), r, xa, xb, len(frames))
                if c and c[1] > nota_melhor:
                    melhor, nota_melhor = c
    if not melhor:
        return None
    k = sw / W
    x, y, w, h = [int(round(v * k)) for v in melhor]
    x, y = max(0, x), max(0, y)
    w, h = min(w, sw - x) // 2 * 2, min(h, sh - y) // 2 * 2
    if debug:
        im = frames[len(frames) // 2].copy()
        l, t, ww, hh = melhor
        cv2.rectangle(im, (int(l), int(t)), (int(l + ww), int(t + hh)), (255, 0, 255), 4)
        cv2.imwrite(debug, im)
    return {"x": x, "y": y, "w": w, "h": h, "nota": round(float(nota_melhor), 1)}


# ------------------------------------------------------------------ 2. câmera vazia
def tempo_morto(video, ini, fim, regiao, falas=(), fps=2.0, minimo=1.2, margem=0.15):
    """Trechos [(a, b)] (tempo do vídeo) sem ninguém na `regiao` (x,y,w,h em px do original) e sem fala.
    Devolve também a linha do tempo de presença, para conferência."""
    sw, sh = dimensoes(video)
    k = LARG / sw
    rx, ry, rw, rh = [v * k for v in regiao]
    linha = []
    for t, f in quadros(video, ini, fim, fps):
        ok = False
        for x0, y0, x1, y1 in pessoas(f, conf=0.35):
            iw = max(0, min(x1, rx + rw) - max(x0, rx))
            ih = max(0, min(y1, ry + rh) - max(y0, ry))
            a = (x1 - x0) * (y1 - y0)
            if iw * ih >= 0.02 * rw * rh or (a and iw * ih >= 0.4 * a):
                ok = True
                break
        linha.append((round(t, 2), ok))
    # trechos sem ninguém
    vazios, i = [], 0
    meio = 0.5 / fps
    while i < len(linha):
        if linha[i][1]:
            i += 1
            continue
        j = i
        while j + 1 < len(linha) and not linha[j + 1][1]:
            j += 1
        vazios.append((max(ini, linha[i][0] - meio), min(fim, linha[j][0] + meio)))
        i = j + 1
    # tira as falas (se alguém fala fora da câmera, a fala fica)
    pedacos = []
    for a, b in vazios:
        partes = [(a, b)]
        for s, e in falas:
            s, e = s - 0.2, e + 0.2
            novo = []
            for x, y in partes:
                if e <= x or s >= y:
                    novo.append((x, y))
                else:
                    if s > x: novo.append((x, s))
                    if e < y: novo.append((e, y))
            partes = novo
        pedacos += partes
    remover = [(round(a + margem, 2), round(b - margem, 2)) for a, b in pedacos if b - a >= minimo]
    total = sum(b - a for a, b in remover)
    vazio_total = sum(1 for _, ok in linha if not ok) / max(1, len(linha))
    # segurança: detector que não acha ninguém em quase todo o corte = algo errado, não corta nada
    if vazio_total > 0.6 or (fim - ini) - total < 8:
        return [], linha
    return remover, linha


def aplicar_cortes(video, ini, fim, remover, saida):
    """Gera `saida` só com o trecho [ini, fim] menos os pedaços `remover`. Devolve os pedaços mantidos."""
    manter, t = [], ini
    for a, b in sorted(remover):
        if a > t:
            manter.append((t, a))
        t = max(t, b)
    if fim > t:
        manter.append((t, fim))
    tem_audio = bool(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                                     "-of", "csv=p=0", video], capture_output=True, text=True).stdout.strip())
    fc = ""
    for i, (a, b) in enumerate(manter):
        fc += f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[v{i}];"
        if tem_audio:
            fc += f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS[a{i}];"
    n = len(manter)
    fc += "".join(f"[v{i}]" + (f"[a{i}]" if tem_audio else "") for i in range(n))
    fc += f"concat=n={n}:v=1:a={1 if tem_audio else 0}[v]" + ("[a]" if tem_audio else "")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", video, "-filter_complex", fc, "-map", "[v]"]
    if tem_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", saida]
    subprocess.run(cmd, check=True)
    return manter


def remapear(t, manter):
    """Tempo do vídeo original -> tempo no vídeo cortado (None se caiu num pedaço removido)."""
    acc = 0.0
    for a, b in manter:
        if t < a:
            return None
        if t <= b:
            return acc + (t - a)
        acc += b - a
    return None


def pessoa_principal(video, ini, fim, n=10):
    """Cena de câmera em tela cheia sem rosto achado (pessoa em pé, de lado...): se uma pessoa grande aparece
    na maior parte do corte, devolve o centro horizontal dela (px do original) para o retrato; senão None."""
    sw, sh = dimensoes(video)
    passo = max((fim - ini) / n, 0.5)
    cxs, vistos = [], 0
    for _, f in quadros(video, ini, fim, 1.0 / passo):
        H, W = f.shape[:2]
        grandes = [b for b in pessoas(f) if (b[3] - b[1]) >= 0.4 * H]
        vistos += 1
        if grandes:
            b = max(grandes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
            cxs.append((b[0] + b[2]) / 2 * sw / W)
    if vistos and len(cxs) >= 0.5 * vistos:
        return int(np.median(cxs))
    return None


def remapear_perto(t, manter):
    """Como remapear, mas um tempo que caiu num pedaço removido vai para o começo do próximo pedaço mantido."""
    acc = 0.0
    for a, b in manter:
        if t < a:
            return acc
        if t <= b:
            return acc + (t - a)
        acc += b - a
    return acc


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=["chamada", "vazio"])
    ap.add_argument("video")
    ap.add_argument("--ini", type=float, default=0)
    ap.add_argument("--fim", type=float, default=60)
    ap.add_argument("--regiao", default="")
    ap.add_argument("--debug")
    a = ap.parse_args()
    if a.modo == "chamada":
        print(json.dumps(achar_chamada(a.video, a.ini, a.fim, debug=a.debug)))
    else:
        sw, sh = dimensoes(a.video)
        reg = [int(v) for v in a.regiao.split(",")] if a.regiao else [0, 0, sw, sh]
        rem, linha = tempo_morto(a.video, a.ini, a.fim, reg)
        print("presença:", "".join("#" if ok else "." for _, ok in linha))
        print("remover:", rem)
