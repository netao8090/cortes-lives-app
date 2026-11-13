#!/usr/bin/env python3
"""
Renderiza os cortes escolhidos a partir de um plano (cortes.json).

cortes.json:
{
  "formato": "vertical",            # vertical | horizontal | ambos
  "layout": "blur",                 # blur (jogo inteiro + fundo desfocado) | facecam (câmera em cima, jogo embaixo)
  "zoom": 1.3,                      # >1 aproxima o jogo no layout blur (1.0 = jogo inteiro)
  "facecam": {"x": 1500, "y": 40, "w": 380, "h": 300},   # só para layout facecam, em pixels do vídeo original
  "legenda": true,
  "cortes": [
    {"id": "01", "inicio": "12:31", "fim": "13:05", "titulo": "ELE NÃO ESPERAVA ISSO"}
  ]
}
Tempos aceitam segundos (751.5) ou "mm:ss" / "h:mm:ss".

Uso:
  python3 cortar.py live.mp4 trabalho/cortes.json --transcricao trabalho/transcricao.json --saida cortes/
"""
import argparse, json, os, re, subprocess, sys

FONTES = "/usr/share/fonts/truetype/google-fonts"
FONTE = "Poppins"


def seg(v):
    if isinstance(v, (int, float)):
        return float(v)
    p = [float(x) for x in str(v).split(":")]
    t = 0.0
    for x in p:
        t = t * 60 + x
    return t


def ts(t):
    t = max(t, 0)
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def sondar(video):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "json", video], capture_output=True, text=True, check=True)
    s = json.loads(r.stdout)["streams"][0]
    return s["width"], s["height"]


def esc_ass(t):
    return t.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def palavras_com_tempo(trans, ini, fim):
    """Distribui o tempo de cada fala entre as palavras, proporcional ao tamanho."""
    out = []
    for f in trans:
        if f["end"] <= ini or f["start"] >= fim:
            continue
        # tira marcações da transcrição: [Música], (risos), [Som de ...]
        limpo = re.sub(r"\[[^\]]*\]?|\([^)]*\)?", " ", f["text"])
        ws = limpo.split()
        if not ws:
            continue
        pesos = [len(w) + 2 for w in ws]
        tot = sum(pesos)
        t = f["start"]
        dur = f["end"] - f["start"]
        for w, p in zip(ws, pesos):
            d = dur * p / tot
            if t + d > ini and t < fim:
                out.append((max(t, ini) - ini, min(t + d, fim) - ini, w))
            t += d
    return out


def blocos(ws, max_pal=3, max_chars=16):
    grupo, out = [], []
    for w in ws:
        grupo.append(w)
        txt = " ".join(x[2] for x in grupo)
        fim_frase = re.search(r"[.!?,]$", w[2])
        if len(grupo) >= max_pal or len(txt) >= max_chars or fim_frase:
            out.append(grupo); grupo = []
    if grupo:
        out.append(grupo)
    return out


def gerar_ass(caminho, W, H, titulo, ws, y_legenda, y_titulo, dur, legenda=True):
    fs = int(W * 0.085) if W < H else int(H * 0.07)
    ft = int(W * 0.06) if W < H else int(H * 0.05)
    L = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Leg,{FONTE},{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,{max(4, fs//12)},3,8,40,40,0,1",
        f"Style: Tit,{FONTE},{ft},&H00000000,&H00000000,&H0000E5FF,&H0000E5FF,-1,0,0,0,100,100,0,0,3,{max(10, ft//4)},0,8,60,60,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if titulo:
        L.append(f"Dialogue: 1,{ts(0)},{ts(dur)},Tit,,0,0,0,,{{\\pos({W//2},{y_titulo})}}{esc_ass(titulo.upper())}")
    if legenda:
        for b in blocos(ws):
            ini_b, fim_b = b[0][0], b[-1][1]
            for k, (s, e, _) in enumerate(b):
                partes = []
                for j, (_, _, w) in enumerate(b):
                    w = esc_ass(w.upper())
                    partes.append("{\\c&H0000E5FF&}" + w + "{\\c&H00FFFFFF&}" if j == k else w)
                s0 = ini_b if k == 0 else s
                e0 = fim_b if k == len(b) - 1 else b[k + 1][0]
                pop = "{\\fscx108\\fscy108\\t(0,80,\\fscx100\\fscy100)}" if k == 0 else ""
                L.append(f"Dialogue: 0,{ts(s0)},{ts(e0)},Leg,,0,0,0,,{{\\pos({W//2},{y_legenda})}}{pop}" + " ".join(partes))
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def render(video, c, plano, trans, saida, fmt_out, sw, sh):
    ini, fim = seg(c["inicio"]), seg(c["fim"])
    dur = fim - ini
    cid = str(c.get("id", "x"))
    titulo = c.get("titulo", "")
    ws = palavras_com_tempo(trans, ini, fim) if trans else []
    legenda = plano.get("legenda", True) and bool(ws)
    ass = os.path.join(saida, f"corte_{cid}_{fmt_out}.ass")

    if fmt_out == "vertical":
        W, H = 1080, 1920
        if plano.get("layout") == "retrato":
            # câmera em tela cheia: recorte vertical centrado no streamer
            cw = int(sh * W / H) // 2 * 2
            cx = int(plano.get("retrato_cx", sw // 2))
            x0 = max(0, min(sw - cw, cx - cw // 2))
            vf = f"[0:v]crop={cw}:{sh}:{x0}:0,scale={W}:{H}:flags=lanczos,unsharp=5:5:0.5:5:5:0[v0]"
            y_tit, y_leg = 230, int(H * 0.72)
        elif plano.get("layout") == "facecam" and plano.get("facecam"):
            fc = plano["facecam"]
            # altura da câmera segue o formato da janela da webcam (sem distorcer)
            hc = int(min(max(W * fc["h"] / max(fc["w"], 1), 520), 820)) // 2 * 2
            hg = H - hc
            gw = int(sh * W / hg) // 2 * 2
            gw = min(gw, sw)
            # webcam costuma ser pequena na tela: tira blocos de compressão, amplia com lanczos e realça
            vf = (f"[0:v]crop={fc['w']}:{fc['h']}:{fc['x']}:{fc['y']},deblock=filter=strong:block=8,hqdn3d=1.5:1.5:3:3,"
                  f"scale={W}:{hc}:force_original_aspect_ratio=increase:flags=lanczos,"
                  f"crop={W}:{hc},unsharp=7:7:0.9:5:5:0,eq=contrast=1.03:saturation=1.06[cam];"
                  f"[0:v]crop={gw}:{sh}:(iw-{gw})/2:0,scale={W}:{hg}:flags=lanczos[jogo];"
                  f"[cam][jogo]vstack[v0]")
            # título na emenda câmera/jogo (não cobre o rosto); legenda no meio do jogo
            y_tit, y_leg = hc - 48, int(H * 0.70)
        else:
            z = float(plano.get("zoom", 1.3))
            fh = int(W / (sw / sh) * z) // 2 * 2
            fh = min(fh, int(H * 0.62))
            cw = int(sw / z) // 2 * 2
            vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:2,"
                  f"eq=brightness=-0.12[bg];"
                  f"[0:v]crop={cw}:ih:(iw-{cw})/2:0,scale={W}:{fh}[fg];"
                  f"[bg][fg]overlay=0:(H-h)/2[v0]")
            topo_fg = (H - fh) // 2
            y_tit = max(topo_fg - 230, 120)
            y_leg = topo_fg + fh + 70
    else:
        W, H = 1920, 1080
        vf = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2[v0]"
        y_tit, y_leg = 50, H - 230
        titulo = titulo if plano.get("titulo_horizontal") else ""

    # legenda animada (pycaps): aqui só o título; a legenda entra depois, com tempo exato de cada palavra
    estilo = plano.get("estilo_legenda") if legenda else None
    gerar_ass(ass, W, H, titulo, ws, y_leg, y_tit, dur, legenda and not estilo)
    vf += f";[v0]subtitles={os.path.basename(ass)}:fontsdir={FONTES}[v]"
    out = os.path.join(saida, f"corte_{cid}_{fmt_out}.mp4")
    fade = min(0.25, dur / 4)
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{ini:.2f}", "-t", f"{dur:.2f}", "-i", os.path.abspath(video),
           "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
           "-af", f"afade=t=in:d={fade},afade=t=out:st={dur-fade:.2f}:d={fade}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
           "-r", "30", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", os.path.basename(out)]
    subprocess.run(cmd, check=True, cwd=saida)

    if estilo:
        final = out[:-4] + "_leg.mp4"
        lcmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "legendar.py"),
                out, final, "--estilo", estilo, "--posicao", f"{c.get('posicao_legenda', y_leg / H):.3f}",
                "--lang", plano.get("idioma", "pt"), "--modelo", plano.get("modelo_legenda", "turbo"),
                "--destaques", ",".join(c.get("destaques", [])),
                "--emojis", json.dumps(c.get("emojis", {}), ensure_ascii=False)]
        if plano.get("vocabulario"):
            lcmd += ["--prompt", plano["vocabulario"]]
        if plano.get("som_legenda"):
            lcmd += ["--som"]
        if c.get("legenda_arquivo"):  # legenda inteligente já revisada pelo Claude
            lcmd += ["--palavras", c["legenda_arquivo"], "--blocos"]
        if c.get("fonte_legenda") or plano.get("fonte_legenda"):
            lcmd += ["--fonte", c.get("fonte_legenda") or plano["fonte_legenda"]]
        r = subprocess.run(lcmd)
        if r.returncode == 0 and os.path.exists(final):
            os.replace(final, out)
        else:
            # não perde o corte: refaz com a legenda simples
            print(f"AVISO legenda animada falhou no corte {cid}; usando a legenda simples", flush=True)
            plano_simples = {k: v for k, v in plano.items() if k != "estilo_legenda"}
            return render(video, c, plano_simples, trans, saida, fmt_out, sw, sh)

    # miniatura: frame no pico de energia do corte
    pico = ini + dur / 2
    if trans:
        dentro = [f for f in trans if ini <= f["start"] < fim]
        if dentro:
            m = max(dentro, key=lambda f: f.get("energia", 0))
            pico = (m["start"] + m["end"]) / 2
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{pico:.2f}", "-i", os.path.abspath(video),
                    "-frames:v", "1", "-q:v", "3", "-vf", "scale=1280:-2", f"thumb_{cid}.jpg"], check=True, cwd=saida)
    os.remove(ass)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("plano")
    ap.add_argument("--transcricao")
    ap.add_argument("--saida", default="cortes")
    ap.add_argument("--so", help="renderiza só estes ids, separados por vírgula")
    a = ap.parse_args()
    plano = json.load(open(a.plano, encoding="utf-8"))
    trans = json.load(open(a.transcricao, encoding="utf-8")) if a.transcricao else []
    os.makedirs(a.saida, exist_ok=True)
    sw, sh = sondar(a.video)
    formatos = ["vertical", "horizontal"] if plano.get("formato") == "ambos" else [plano.get("formato", "vertical")]
    ids = set(a.so.split(",")) if a.so else None
    for c in plano["cortes"]:
        if ids and str(c.get("id")) not in ids:
            continue
        for f in formatos:
            o = render(a.video, c, plano, trans, a.saida, f, sw, sh)
            print("ok", o, flush=True)


if __name__ == "__main__":
    main()
