#!/usr/bin/env python3
"""
Escolhe onde a legenda fica em cada bloco para não cobrir o que importa (personagem, carro, moto...).

Usa o detector YOLOX (opencv_zoo, Apache-2.0) pelo OpenCV. Para cada bloco de legenda olha 3 quadros do trecho,
acha pessoas/veículos na área do jogo (ignora a webcam) e mede quanto a faixa da legenda cobriria deles.
A legenda fica embaixo (padrão aprovado) e só sobe quando precisa; troca de lugar o mínimo possível.

  python3 posicao_legenda.py imagem FOTO.png --topo-jogo 0.31 --saida anotada.jpg      (teste numa imagem)
  (no fluxo normal é chamado pelo legenda_inteligente.py transcrever --video-posicao)
"""
import argparse, os, sys
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
MODELO = os.path.join(AQUI, "..", "models", "yolox.onnx")
URL_MODELO = "https://github.com/opencv/opencv_zoo/raw/main/models/object_detection_yolox/object_detection_yolox_2022nov.onnx"
# COCO: pessoa, bicicleta, carro, moto, ônibus, caminhão, barco, cavalo, cachorro
PESO_CLASSE = {0: 1.0, 1: 0.7, 2: 0.6, 3: 0.8, 5: 0.5, 7: 0.5, 8: 0.5, 17: 0.7, 16: 0.7}
NOMES = {0: "pessoa", 1: "bicicleta", 2: "carro", 3: "moto", 5: "onibus", 7: "caminhao", 8: "barco", 16: "cachorro", 17: "cavalo"}
PADRAO = 0.76                     # embaixo (aprovado)
ALTERNATIVAS = [0.60, 0.46]       # meio, alto (sempre abaixo do título / webcam)
LIMIAR = 0.06                     # quanto de cobertura já justifica mudar


class Detector:
    def __init__(self, modelo=MODELO):
        import cv2
        if not os.path.exists(modelo):
            os.makedirs(os.path.dirname(modelo), exist_ok=True)
            import urllib.request
            urllib.request.urlretrieve(URL_MODELO, modelo)
        self.cv2 = cv2
        self.net = cv2.dnn.readNet(modelo)
        self.tam = 640
        grids, strides = [], []
        for s in (8, 16, 32):
            n = self.tam // s
            xv, yv = np.meshgrid(np.arange(n), np.arange(n))
            grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
            strides.append(np.full((n * n, 1), s))
        self.grids = np.concatenate(grids).astype(np.float32)
        self.strides = np.concatenate(strides).astype(np.float32)

    def detectar(self, img, conf=0.35):
        cv2 = self.cv2
        h, w = img.shape[:2]
        r = min(self.tam / h, self.tam / w)
        rs = cv2.resize(img, (int(w * r), int(h * r)))
        pad = np.full((self.tam, self.tam, 3), 114, np.uint8)
        pad[:rs.shape[0], :rs.shape[1]] = rs
        blob = np.transpose(pad, (2, 0, 1))[None].astype(np.float32)
        self.net.setInput(blob)
        out = self.net.forward()[0]
        xy = (out[:, :2] + self.grids) * self.strides
        wh = np.exp(out[:, 2:4]) * self.strides
        scores = out[:, 4:5] * out[:, 5:]
        cls = scores.argmax(1)
        sc = scores[np.arange(len(cls)), cls]
        ok = (sc > conf) & np.isin(cls, list(PESO_CLASSE))
        if not ok.any():
            return []
        xy, wh, cls, sc = xy[ok], wh[ok], cls[ok], sc[ok]
        caixas = np.concatenate([xy - wh / 2, wh], 1) / r
        idx = cv2.dnn.NMSBoxes(caixas.tolist(), sc.tolist(), conf, 0.45)
        res = []
        for i in np.array(idx).flatten():
            x, y, bw, bh = caixas[i]
            res.append({"cls": int(cls[i]), "conf": float(sc[i]),
                        "box": [max(0, x), max(0, y), min(w, x + bw), min(h, y + bh)]})
        return res


def faixa(pos, linhas, W, H, alt_linha=0.048):
    """Retângulo que a legenda ocupa com o topo em `pos` (fração da altura)."""
    y0 = pos * H
    return [W * 0.09, y0 - 0.01 * H, W * 0.91, y0 + linhas * alt_linha * H + 0.012 * H]


def custo(objs, f, topo_jogo, H):
    c = 0.0
    area_f = (f[2] - f[0]) * (f[3] - f[1])
    for o in objs:
        x0, y0, x1, y1 = o["box"]
        if (y0 + y1) / 2 < topo_jogo * H:      # está na webcam: é o streamer, não o jogo
            continue
        iw = max(0, min(x1, f[2]) - max(x0, f[0]))
        ih = max(0, min(y1, f[3]) - max(y0, f[1]))
        if iw * ih <= 0:
            continue
        a_obj = max(1, (x1 - x0) * (y1 - y0))
        # quanto do objeto some atrás da legenda (pesa mais) + quanto da faixa ele ocupa
        c += PESO_CLASSE[o["cls"]] * o["conf"] * (0.7 * iw * ih / a_obj + 0.3 * iw * ih / area_f)
    return c


def escolher(objs_por_bloco, linhas_por_bloco, topo_jogo, W, H):
    """Posição por bloco: fica embaixo se der; senão a alternativa que menos cobre. Com histerese."""
    cands = [PADRAO] + [p for p in ALTERNATIVAS if p >= topo_jogo + 0.08]
    escolhas, custos = [], []
    for objs, lin in zip(objs_por_bloco, linhas_por_bloco):
        cs = {p: sum(custo(o, faixa(p, lin, W, H), topo_jogo, H) for o in objs) / max(1, len(objs)) for p in cands}
        custos.append(cs)
        if cs[PADRAO] <= LIMIAR:
            escolhas.append(PADRAO)
        else:
            melhor = min(cands, key=lambda p: (round(cs[p], 3), cands.index(p)))
            escolhas.append(melhor if cs[melhor] < cs[PADRAO] * 0.6 else PADRAO)
    # histerese: bloco isolado diferente dos vizinhos iguais acompanha os vizinhos (se não cobrir muito)
    for i in range(1, len(escolhas) - 1):
        a, b, c = escolhas[i - 1], escolhas[i], escolhas[i + 1]
        if a == c != b and custos[i][a] <= max(LIMIAR * 2, custos[i][b] * 1.5):
            escolhas[i] = a
    # já subiu? fica no alto enquanto o padrão continuar arriscado (evita sobe-desce)
    for i in range(1, len(escolhas)):
        if escolhas[i] == PADRAO and escolhas[i - 1] != PADRAO and custos[i][PADRAO] > LIMIAR * 0.5:
            escolhas[i] = escolhas[i - 1]
    return escolhas, custos


def quadros(video, tempos):
    import cv2
    cap = cv2.VideoCapture(video)
    out = []
    for t in tempos:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0, t) * 1000)
        ok, fr = cap.read()
        out.append(fr if ok else None)
    cap.release()
    return out


def desenhar(img, objs, pos_escolhida, linhas, topo_jogo, rotulo=""):
    import cv2
    H, W = img.shape[:2]
    im = img.copy()
    cv2.line(im, (0, int(topo_jogo * H)), (W, int(topo_jogo * H)), (255, 255, 0), 3)
    for o in objs:
        x0, y0, x1, y1 = map(int, o["box"])
        cor = (0, 255, 0) if (y0 + y1) / 2 >= topo_jogo * H else (128, 128, 128)
        cv2.rectangle(im, (x0, y0), (x1, y1), cor, 4)
        cv2.putText(im, f"{NOMES.get(o['cls'], o['cls'])} {o['conf']:.2f}", (x0, max(30, y0 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, cor, 3)
    p = faixa(PADRAO, linhas, W, H)
    cv2.rectangle(im, (int(p[0]), int(p[1])), (int(p[2]), int(p[3])), (0, 0, 255), 3)
    f = faixa(pos_escolhida, linhas, W, H)
    ov = im.copy()
    cv2.rectangle(ov, (int(f[0]), int(f[1])), (int(f[2]), int(f[3])), (0, 230, 255), -1)
    im = cv2.addWeighted(ov, 0.35, im, 0.65, 0)
    cv2.rectangle(im, (int(f[0]), int(f[1])), (int(f[2]), int(f[3])), (0, 230, 255), 4)
    if rotulo:
        cv2.rectangle(im, (0, 0), (W, 70), (0, 0, 0), -1)
        cv2.putText(im, rotulo, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
    return im


def analisar_video(video, blocos, topo_jogo, folha=None):
    """blocos: [{"de", "ate", "texto"}] → posição de cada um (+ folha de conferência opcional)."""
    import cv2
    det = Detector()
    cap = cv2.VideoCapture(video)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    objs_por_bloco, linhas, meio = [], [], []
    for b in blocos:
        de, ate = b["de"], max(b["ate"], b["de"] + 0.2)
        ts = [de + 0.05, (de + ate) / 2, ate - 0.05]
        frs = quadros(video, ts)
        objs_por_bloco.append([det.detectar(f) if f is not None else [] for f in frs])
        linhas.append(2 if len(b["texto"]) > 17 else 1)
        meio.append(frs[1])
    escolhas, custos = escolher(objs_por_bloco, linhas, topo_jogo, W, H)
    if folha:
        thumbs = []
        for i, (b, fr) in enumerate(zip(blocos, meio)):
            if fr is None:
                continue
            im = desenhar(fr, objs_por_bloco[i][1], escolhas[i], linhas[i], topo_jogo,
                          f"{i + 1}  {b['de']:.1f}s  pos {escolhas[i]:.2f}")
            thumbs.append(cv2.resize(im, (270, 480)))
        if thumbs:
            while len(thumbs) % 6:
                thumbs.append(np.zeros_like(thumbs[0]))
            linhas_img = [np.hstack(thumbs[k:k + 6]) for k in range(0, len(thumbs), 6)]
            cv2.imwrite(folha, np.vstack(linhas_img), [cv2.IMWRITE_JPEG_QUALITY, 85])
    return escolhas, custos


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("imagem")
    i.add_argument("foto"); i.add_argument("--topo-jogo", type=float, default=0.3)
    i.add_argument("--saida", required=True); i.add_argument("--linhas", type=int, default=2)
    a = ap.parse_args()
    import cv2
    img = cv2.imread(a.foto)
    H, W = img.shape[:2]
    objs = Detector().detectar(img)
    escolhas, custos = escolher([[objs]], [a.linhas], a.topo_jogo, W, H)
    print("objetos:", [(NOMES.get(o["cls"]), round(o["conf"], 2), [int(v) for v in o["box"]]) for o in objs])
    print("custos:", {k: round(v, 3) for k, v in custos[0].items()}, "-> posição", escolhas[0])
    cv2.imwrite(a.saida, desenhar(img, objs, escolhas[0], a.linhas, a.topo_jogo, f"pos {escolhas[0]:.2f}"))


if __name__ == "__main__":
    main()
