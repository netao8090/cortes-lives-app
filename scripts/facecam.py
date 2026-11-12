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
    g = max(bons, key=lambda g: len(g["frames"]) * np.median([i[4] for i in g["itens"]]))
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

    bE = 0 if cx - lim <= 0 else int(cx - lim)
    bD = W if cx + lim >= W else int(cx + lim)
    bC = 0 if cy - lim <= 0 else int(cy - lim)
    bB = H if cy + lim >= H else int(cy + lim)
    # 1) laterais usando a altura do rosto
    esq = melhor(perfil_v(fx - 2, fx - lim, -1, fy, fy + 0.9 * fh), bE)
    dir_ = melhor(perfil_v(fx + fw + 2, fx + fw + lim, 1, fy, fy + 0.9 * fh), bD)
    # 2) topo/base usando a LARGURA INTEIRA da janela (contorno do fone/cabeça não cobre tudo)
    m = 0.08 * (dir_ - esq)
    cima = melhor(perfil_h(fy - 2, fy - lim, -1, esq + m, dir_ - m), bC)
    baixo = melhor(perfil_h(fy + 0.8 * fh, fy + fh + lim, 1, esq + m, dir_ - m), bB)
    # 3) refina laterais usando a altura inteira
    m = 0.08 * (baixo - cima)
    esq = melhor(perfil_v(fx - 2, fx - lim, -1, cima + m, baixo - m), esq)
    dir_ = melhor(perfil_v(fx + fw + 2, fx + fw + lim, 1, cima + m, baixo - m), dir_)
    return int(esq), int(cima), int(dir_ - esq), int(baixo - cima)


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
    x, y, w, h = moldura(frames, face)
    fx, fy, fw, fh = face
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
