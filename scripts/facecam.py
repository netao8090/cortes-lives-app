#!/usr/bin/env python3
"""
Acha sozinho a janela da webcam (facecam) do streamer em um ou mais vídeos.

Ideia:
  1. pega ~30 quadros espalhados pelos vídeos;
  2. acha rostos (YuNet) e fica com o rosto GRANDE que aparece sempre no mesmo lugar
     (personagens do jogo se mexem; avatares do placar são pequenos);
  3. procura as bordas retas e FIXAS em volta desse rosto (a moldura da webcam), usando
     a mediana das bordas ao longo do tempo (o jogo muda, a moldura não).

Uso como módulo: detectar([videos]) -> {"x","y","w","h","debug": frame_com_caixa} ou None
Uso direto:      facecam.py video1.mp4 [video2.mp4 ...] --debug saida.jpg
"""
import os, sys
import numpy as np
import cv2

MODELO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "yunet.onnx")


def amostrar(videos, n=30):
    frames = []
    por = max(1, n // len(videos))
    for v in videos:
        cap = cv2.VideoCapture(v)
        tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        for k in range(por):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(tot * (k + 0.5) / por))
            ok, f = cap.read()
            if ok:
                frames.append(f)
        cap.release()
    if frames:  # todos no mesmo tamanho
        H, W = frames[0].shape[:2]
        frames = [f if f.shape[:2] == (H, W) else cv2.resize(f, (W, H)) for f in frames]
    return frames


def rostos(frames):
    H, W = frames[0].shape[:2]
    det = cv2.FaceDetectorYN.create(MODELO, "", (W, H), 0.7, 0.3, 5000)
    out = []
    for i, f in enumerate(frames):
        _, fs = det.detect(f)
        if fs is None:
            continue
        for r in fs:
            x, y, w, h = r[:4]
            if h >= 0.04 * H:  # descarta avatares minúsculos do HUD
                out.append((i, x, y, w, h))
    return out


def rosto_fixo(achados, nframes, W):
    """Agrupa rostos pela posição e devolve o grupo mais constante (e maior)."""
    grupos = []
    for a in achados:
        cx = a[1] + a[3] / 2; cy = a[2] + a[4] / 2
        for g in grupos:
            if abs(g["cx"] - cx) < 0.06 * W and abs(g["cy"] - cy) < 0.06 * W:
                g["itens"].append(a); g["frames"].add(a[0]); break
        else:
            grupos.append({"cx": cx, "cy": cy, "itens": [a], "frames": {a[0]}})
    bons = [g for g in grupos if len(g["frames"]) >= max(2, 0.25 * nframes)]
    if not bons:
        return None
    # entre os rostos que aparecem com frequência (>= 60% do mais frequente), fica o MAIOR:
    # retratos de personagem no HUD são menores que o rosto real na webcam
    topo = max(len(g["frames"]) for g in bons)
    freq = [g for g in bons if len(g["frames"]) >= 0.6 * topo]
    g = max(freq, key=lambda g: np.median([i[4] for i in g["itens"]]))
    arr = np.array([i[1:] for i in g["itens"]])
    return np.median(arr, axis=0)  # x, y, w, h


def moldura(frames, face):
    H, W = frames[0].shape[:2]
    ex, ey = [], []
    for f in frames:
        g = cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (3, 3), 0).astype(np.float32)
        ex.append(np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)))
        ey.append(np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)))
    Ex = np.median(np.stack(ex), axis=0); Ey = np.median(np.stack(ey), axis=0)
    fx, fy, fw, fh = face
    cx, cy = fx + fw / 2, fy + fh / 2
    lim = 4.0 * max(fw, fh)

    # Moldura = linha reta CONTÍNUA e forte. Nota de cada linha candidata = percentil 20 da
    # força da borda ao longo dela (uma linha forte só em pedaços tira nota baixa).
    def perfil_v(c0, c1, passo, r0, r1):
        r0, r1 = int(max(0, r0)), int(min(H, r1))
        out = []
        for c in range(int(c0), int(c1), passo):
            if 0 <= c < W and r1 - r0 > 4:
                col = Ex[r0:r1, max(0, c - 1):c + 2].max(axis=1)
                out.append((c, float(np.percentile(col, 20))))
        return out

    def perfil_h(r0_, r1_, passo, c0, c1):
        c0, c1 = int(max(0, c0)), int(min(W, c1))
        out = []
        for r in range(int(r0_), int(r1_), passo):
            if 0 <= r < H and c1 - c0 > 4:
                row = Ey[max(0, r - 1):r + 2, c0:c1].max(axis=0)
                out.append((r, float(np.percentile(row, 20))))
        return out

    def melhor(perfil, borda):
        if not perfil:
            return borda
        c, n = max(perfil, key=lambda t: t[1])
        return c if n >= 40 else borda

    def picos(perfil, borda_tela, perto):
        """Até 4 linhas fortes (máximos locais) + a borda da tela, se estiver perto."""
        cands = []
        for i, (c, n) in enumerate(perfil):
            viz = [x[1] for x in perfil[max(0, i - 4):i + 5]]
            if n >= 18 and n == max(viz):
                cands.append((c, n))
        cands = sorted(cands, key=lambda t: -t[1])[:5]
        if perto:
            cands.append((borda_tela, 60.0))
        return cands or [(None, 0.0)]

    lim_h = 6.5 * fw
    lim_v = 4.0 * fh
    # 1) candidatos das laterais (altura do rosto) e de topo/base (largura do rosto)
    L = picos(perfil_v(fx - 2, fx - lim_h, -1, fy, fy + 0.9 * fh), 0, fx - lim_h <= 0)
    R = picos(perfil_v(fx + fw + 2, fx + fw + lim_h, 1, fy, fy + 0.9 * fh), W, fx + fw + lim_h >= W)
    T = picos(perfil_h(fy - 2, fy - lim_v, -1, fx - fw, fx + 2 * fw), 0, fy - lim_v <= 0)
    B = picos(perfil_h(fy + 0.8 * fh, fy + fh + lim_v, 1, fx - fw, fx + 2 * fw), H, fy + fh + lim_v >= H)

    if os.environ.get("FC_DEBUG"):
        print("L", L, "\nR", R, "\nT", T, "\nB", B)
    # 2) escolhe a combinação com bordas fortes E formato de webcam (16:9 ou 4:3)
    import math
    melhor_comb, melhor_nota = None, -1e9
    for l, nl in L:
        for r, nr in R:
            for t, nt in T:
                if None in (l, r, t):
                    continue
                # base: as linhas achadas + as posições que dariam formato 16:9 / 4:3
                extras = [(int(t + (r - l) / a), 0.0) for a in (16 / 9, 4 / 3) if t + (r - l) / a <= H]
                for bb, nb in B + extras:
                    if bb is None:
                        continue
                    w, h = r - l, bb - t
                    if w < 1.5 * fw or h < 1.3 * fh:
                        continue
                    # a caixa precisa conter o rosto com folga
                    if l > fx - 0.3 * fw or r < fx + 1.3 * fw or t > fy - 0.15 * fh or bb < fy + 0.85 * fh:
                        continue
                    asp = w / h
                    desvio = min(abs(math.log(asp / (16 / 9))), abs(math.log(asp / (4 / 3))))
                    # confirma as bordas ao longo da caixa inteira (não só perto do rosto)
                    conf = 0.0
                    for c in (l, r):
                        if 0 < c < W:
                            col = Ex[int(t):int(bb), max(0, c - 1):c + 2].max(axis=1)
                            conf += float(np.percentile(col, 20)) if len(col) else 0
                        else:
                            conf += 60
                    for rr in (t, bb):
                        if 0 < rr < H:
                            row = Ey[max(0, rr - 1):rr + 2, int(l):int(r)].max(axis=0)
                            conf += float(np.percentile(row, 20)) if row.size else 0
                        else:
                            conf += 60
                    # rosto costuma ocupar 10-30% da largura da webcam
                    prop = fw / w
                    pen_rosto = 400 * max(0.0, math.log(0.10 / prop)) + 400 * max(0.0, math.log(prop / 0.35))
                    nota = conf - 400 * desvio - pen_rosto
                    if os.environ.get("FC_DEBUG") and nota > melhor_nota - 50:
                        print("  comb", (l, t, w, h), round(conf), round(desvio, 2), round(nota))
                    if nota > melhor_nota:
                        melhor_comb, melhor_nota = (l, t, w, h), nota
    if melhor_comb is None:
        return int(fx - fw), int(fy - fh), int(3 * fw), int(3 * fh)
    return tuple(int(v) for v in melhor_comb)


def heuristica(face, W, H):
    fx, fy, fw, fh = face
    w = 3.2 * fw; h = w / 1.6
    cx = fx + fw / 2; cy = fy + fh / 2 + 0.1 * h
    x = int(np.clip(cx - w / 2, 0, W - w)); y = int(np.clip(cy - h / 2, 0, H - h))
    return x, y, int(w), int(h)


def detectar(videos, n=30):
    frames = amostrar(videos, n)
    if len(frames) < 2:
        return None
    H, W = frames[0].shape[:2]
    face = rosto_fixo(rostos(frames), len(frames), W)
    if face is None:
        return None
    fx, fy, fw, fh = face
    if fh > 0.12 * H:  # rosto enorme = cena de câmera em tela cheia (não é janelinha de webcam)
        dbg = frames[len(frames) // 2].copy()
        return {"x": 0, "y": 0, "w": W, "h": H, "metodo": "tela_cheia", "W": W, "H": H, "debug": dbg,
                "cx": int(fx + fw / 2)}
    x, y, w, h = moldura(frames, face)
    ok = (w > 1.3 * fw and h > 1.2 * fh and 0.6 < w / max(h, 1) < 2.6 and w * h < 0.3 * W * H
          and x <= fx and y <= fy + 0.3 * fh and x + w >= fx + fw and y + h >= fy + 0.7 * fh)
    metodo = "moldura"
    if not ok:
        x, y, w, h = heuristica(face, W, H); metodo = "estimada"
    x, y, w, h = max(0, x), max(0, y), min(w, W - max(0, x)), min(h, H - max(0, y))
    w -= w % 2; h -= h % 2
    dbg = frames[len(frames) // 2].copy()
    cv2.rectangle(dbg, (x, y), (x + w, y + h), (0, 255, 255), 4)
    cv2.rectangle(dbg, (int(fx), int(fy)), (int(fx + fw), int(fy + fh)), (0, 0, 255), 2)
    return {"x": x, "y": y, "w": w, "h": h, "metodo": metodo, "W": W, "H": H, "debug": dbg}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dbg = sys.argv[sys.argv.index("--debug") + 1] if "--debug" in sys.argv else None
    if dbg in args:
        args.remove(dbg)
    r = detectar(args)
    if r is None:
        print("nenhuma facecam encontrada")
    else:
        if dbg:
            cv2.imwrite(dbg, r["debug"])
        print({k: v for k, v in r.items() if k != "debug"})
