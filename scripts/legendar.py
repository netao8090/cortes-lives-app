#!/usr/bin/env python3
"""
Legenda gravada no vídeo, estilo TikTok/Reels, com o pycaps (github.com/francozanardi/pycaps, MIT):
palavra por palavra, palavra falada em destaque, animação, palavras-chave coloridas, emojis e efeitos sonoros.

As funções de "IA" do pycaps (escolher palavras importantes e emojis) pedem chave da OpenAI; aqui quem
faz esse papel é o Claude, passando --destaques e --emojis. Sem eles, a legenda sai igual, só sem esses extras.

Uso:
  python3 scripts/legendar.py ENTRADA.mp4 SAIDA.mp4
      [--estilo viral]                    viral (padrão), explosivo, gamer, ou um preset do pycaps:
                                          hype, explosive, word-focus, line-focus, vibrant, retro-gaming,
                                          minimalist, neo-minimal, classic, default, fast
      [--palavras palavras.json]          tempos por palavra já prontos (formato whisper: segments[].words[])
                                          sem isso, transcreve com faster-whisper (--modelo, --lang)
      [--destaques "recorde,polícia"]     palavras-chave: cor diferente, maiores e com "pop"
      [--emojis '{"recorde":"😱"}']       emoji grudado na palavra
      [--posicao 0.68]                    altura do topo da legenda (0 = topo, 1 = base); padrão do estilo
      [--som]                             "pop/whoosh" nas palavras de destaque
      [--lang pt] [--modelo turbo] [--qualidade very_high]
"""
import argparse, json, os, shutil, subprocess, sys, tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))

# estilos próprios = preset base do pycaps + CSS/animações por cima
CSS_VIRAL = """
.word {
    text-transform: uppercase;
    font-size: 21px;
    color: #FFFFFF;
    letter-spacing: 0.4px;
    -webkit-text-stroke: 1.2px #000;
    paint-order: stroke fill;
    text-shadow:
        -2px -2px 0 #000, 2px -2px 0 #000, -2px 2px 0 #000, 2px 2px 0 #000,
        0 2.2px 0 #000, 0 -2.2px 0 #000, 2.2px 0 0 #000, -2.2px 0 0 #000,
        0 4px 6px rgba(0,0,0,0.55);
    padding: 2px 6px;
}
.word-not-narrated-yet { color: #FFFFFF; }
.word-already-narrated { color: #FFFFFF; }
.word-being-narrated { color: #FFE81F; }
.word.destaque { color: #39FF6A; }
.word.destaque.word-being-narrated { color: #39FF6A; }
"""

CSS_EXPLOSIVO = """
.word { text-transform: uppercase; font-size: 30px; }
.word.destaque { color: #FFFFFF; }
"""

CSS_GAMER = """
.word {
    text-transform: uppercase;
    font-size: 29px;
    color: #FFFFFF;
    -webkit-text-stroke: 1.4px #000;
    paint-order: stroke fill;
    text-shadow: 0 0 2px #000, 3px 3px 0 #000, 0 0 10px rgba(0,229,255,0.55);
    padding: 2px 6px;
}
.word-being-narrated {
    color: #00E5FF;
    text-shadow: 0 0 2px #000, 3px 3px 0 #000, 0 0 14px rgba(0,229,255,0.9);
}
.word.destaque { color: #FF3DCB;
    text-shadow: 0 0 2px #000, 3px 3px 0 #000, 0 0 14px rgba(255,61,203,0.9); }
"""

ANIM_DESTAQUE = {"type": "zoom_in_primitive", "when": "narration-starts", "what": "word", "duration": 0.18,
                 "init_scale": 0.55, "overshoot": {"amount": 0.18, "peak_at": 0.6}, "tag_condition": "destaque"}

CSS_INTELIGENTE = CSS_VIRAL + """
.word.destaque, .word.destaque.word-being-narrated { color: inherit; }
.word.falante2 { font-style: italic; }
"""

ESTILOS = {
    "inteligente": {"base": "hype", "css": CSS_INTELIGENTE, "posicao": 0.76, "max_chars": 15,
                    "anim": [{"type": "fade_in", "when": "narration-starts", "what": "segment", "duration": 0.08},
                             {"type": "fade_out", "when": "narration-ends", "what": "segment", "duration": 0.1}]},
    "viral": {"base": "hype", "css": CSS_VIRAL, "posicao": 0.66, "max_chars": 15,
              "extra_anim": [ANIM_DESTAQUE]},
    "explosivo": {"base": "explosive", "css": CSS_EXPLOSIVO, "posicao": 0.64, "max_chars": 18,
                  "extra_anim": [ANIM_DESTAQUE]},
    "gamer": {"base": "word-focus", "css": CSS_GAMER, "posicao": 0.66, "max_chars": 16,
              "extra_anim": [{"type": "pop_in_primitive", "when": "narration-starts", "what": "word",
                              "duration": 0.14, "init_scale": 0.75},
                             ANIM_DESTAQUE]},
}
PRESETS = ["hype", "explosive", "word-focus", "line-focus", "vibrant", "retro-gaming",
           "minimalist", "neo-minimal", "classic", "default", "fast"]


def pasta_presets():
    import pycaps
    p = os.path.join(os.path.dirname(pycaps.__file__), "template", "preset")
    if not os.path.isdir(p):
        sys.exit(f"ERRO_LEGENDA presets do pycaps não encontrados em {p}")
    return p


FONTES_LEGENDA = {  # arquivo em fontes_legenda/, peso, tamanho (mesma altura de letra da prévia)
    "montserrat": ("montserrat-latin-900-normal.woff2", 900, 26.4),
    "anton": ("anton-latin-400-normal.woff2", 400, 21.5),
    "bangers": ("bangers-latin-400-normal.woff2", 400, 25.0),
}


def aplicar_fonte(cfg, css, trab, fonte):
    arq, peso, tam = FONTES_LEGENDA[fonte]
    res = os.path.join(trab, "res")
    if cfg.get("resources") and os.path.isdir(cfg["resources"]):
        shutil.copytree(cfg["resources"], res)
    else:
        os.makedirs(res)
    shutil.copy(os.path.join(AQUI, "..", "fontes_legenda", arq), res)
    cfg["resources"] = res
    return css + f"""
@font-face {{ font-family: 'Leg'; src: url('{arq}'); font-weight: {peso}; }}
.word {{ font-family: 'Leg'; font-weight: {peso}; font-size: {tam}px; }}
"""


COMPACTA = {  # menor e mais junta; o padding mínimo evita cortar o contorno (o pycaps recorta cada palavra na borda)
    "b": {"tam": 22, "ls": 0, "pad": "2px 3px", "stroke": 1.1, "sh": 1.7, "blur": 3},
    "c": {"tam": 19.5, "ls": -0.2, "pad": "2px 2.5px", "stroke": 1.0, "sh": 1.5, "blur": 2.5},
}


def css_compacta(k):
    v = COMPACTA[k]; sh = v["sh"]; s2 = round(sh * 1.1, 2)
    return f"""
.word {{ font-size: {v['tam']}px; letter-spacing: {v['ls']}px; padding: {v['pad']}; -webkit-text-stroke: {v['stroke']}px #000;
  text-shadow: -{sh}px -{sh}px 0 #000, {sh}px -{sh}px 0 #000, -{sh}px {sh}px 0 #000, {sh}px {sh}px 0 #000,
    0 {s2}px 0 #000, 0 -{s2}px 0 #000, {s2}px 0 0 #000, -{s2}px 0 0 #000, 0 {round(sh*2,2)}px {v['blur']}px rgba(0,0,0,0.55); }}
"""


def montar_config(estilo, trab, destaques, emojis, posicao, som, fonte=None, blocos=False, compacta=None):
    presets = pasta_presets()
    proprio = ESTILOS.get(estilo)
    base = proprio["base"] if proprio else estilo
    if base not in PRESETS:
        sys.exit(f"ERRO_LEGENDA estilo desconhecido: {estilo}")
    pdir = os.path.join(presets, base)
    cfg = json.load(open(os.path.join(pdir, "pycaps.template.json"), encoding="utf-8"))

    # sem chave da OpenAI as regras de IA do pycaps não fazem nada: tira e usa o que o Claude mandou
    tem_ia = bool(os.environ.get("PYCAPS_OPENAI_API_KEY"))
    if not tem_ia:
        cfg["tagger_rules"] = [r for r in cfg.get("tagger_rules", []) if r.get("type") != "ai"]
        cfg["effects"] = [e for e in cfg.get("effects", [])
                          if e.get("type") not in ("emoji_in_segment", "animate_segment_emojis")]

    css = open(os.path.join(pdir, cfg.get("css", "styles.css")), encoding="utf-8").read()
    if proprio:
        css += "\n" + proprio["css"]
        cfg["animations"] = proprio["anim"] if "anim" in proprio else \
            cfg.get("animations", []) + proprio.get("extra_anim", [])
        if proprio.get("max_chars"):
            cfg["splitters"] = [{"type": "split_into_sentences"},
                                {"type": "limit_by_chars", "min_chars": 6, "max_chars": proprio["max_chars"],
                                 "avoid_finishing_segment_with_word_shorter_than": 2}]
        cfg.setdefault("layout", {})["max_number_of_lines"] = 2
        cfg["layout"]["max_width_ratio"] = 0.78
    else:
        css += "\n.word.destaque { filter: brightness(1.15); }\n"
    res = os.path.join(pdir, cfg.get("resources", "resources"))
    if os.path.isdir(res):
        cfg["resources"] = res
    else:
        cfg.pop("resources", None)
    if fonte:
        css = aplicar_fonte(cfg, css, trab, fonte)
    if compacta:
        css += css_compacta(compacta)
    css_path = os.path.join(trab, "styles.css")
    open(css_path, "w", encoding="utf-8").write(css)
    cfg["css"] = css_path

    regras = list(cfg.get("tagger_rules", []))
    if blocos:
        cfg["splitters"] = []
        regras.append({"type": "regex", "tag": "falante2", "regex": "[^ ]*\u2060[^ ]*"})
    if destaques:
        f = os.path.join(trab, "destaques.txt")
        open(f, "w", encoding="utf-8").write("\n".join(destaques))
        regras.append({"type": "wordlist", "tag": "destaque", "filename": f})
        if base == "explosive":  # o CSS do explosive usa a tag "highlighted"
            regras.append({"type": "wordlist", "tag": "highlighted", "filename": f})
    efeitos = list(cfg.get("effects", []))
    for i, (emoji, palavras) in enumerate(agrupar_emojis(emojis).items()):
        f = os.path.join(trab, f"emoji_{i}.txt")
        open(f, "w", encoding="utf-8").write("\n".join(palavras))
        regras.append({"type": "wordlist", "tag": f"emoji{i}", "filename": f})
        efeitos.append({"type": "emoji_in_word", "emojis": [emoji], "tag_condition": f"emoji{i}",
                        "avoid_use_same_emoji_in_a_row": False})
    cfg["tagger_rules"], cfg["effects"] = regras, efeitos

    if som and destaques:
        cfg["sound_effects"] = cfg.get("sound_effects", []) + [
            {"type": "preset", "name": "pop", "when": "narration-starts", "what": "word",
             "tag_condition": "destaque", "volume": 0.35}]

    pos = posicao if posicao is not None else (proprio or {}).get("posicao")
    if pos is not None:
        cfg.setdefault("layout", {})["vertical_align"] = {"align": "top", "offset": max(0.0, min(0.95, pos))}
    cfg.pop("input", None); cfg.pop("output", None); cfg.pop("whisper", None)
    path = os.path.join(trab, "config.json")
    json.dump(cfg, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return path


def agrupar_emojis(emojis):
    g = {}
    for palavra, emoji in (emojis or {}).items():
        g.setdefault(emoji, []).append(palavra)
    return g


MODELOS = {"turbo": "large-v3-turbo", "large": "large-v3"}


def limpar_repeticoes(ws, max_rep=3):
    """Corta laços de alucinação do Whisper ("aí e aí e aí e..." / "vai vai vai vai vai...")."""
    norm = lambda w: "".join(ch for ch in w["word"].lower() if ch.isalnum())
    out = []
    for w in ws:
        out.append(w)
        for n in (1, 2, 3):  # padrão de 1, 2 ou 3 palavras repetido
            k = n * (max_rep + 1)
            if len(out) >= k:
                bloco = [norm(x) for x in out[-k:]]
                if all(bloco[i] == bloco[i % n] for i in range(k)):
                    out = out[:-n]
                    break
    return out


def em_blocos(ws, max_chars=24, pausa=0.6):
    """Agrupa as palavras em falas curtas (pontuação, pausa ou tamanho), para a legenda nunca virar paredão."""
    segs, atual = [], []
    for w in ws:
        if atual and (w["start"] - atual[-1]["end"] > pausa or
                      len(" ".join(x["word"] for x in atual + [w])) > max_chars):
            segs.append(atual); atual = []
        atual.append(w)
        if w["word"].rstrip().endswith((".", "!", "?")):
            segs.append(atual); atual = []
    if atual:
        segs.append(atual)
    return {"segments": [{"start": s[0]["start"], "end": s[-1]["end"],
                          "text": " ".join(x["word"] for x in s), "words": s} for s in segs]}


def transcrever(video, lang, modelo, prompt, trab):
    """faster-whisper com filtro de voz e sem herdar o texto anterior (evita alucinação em barulho de jogo)."""
    import numpy as np
    from faster_whisper import WhisperModel
    # áudio pelo ffmpeg (16 kHz mono), sem depender da versão do PyAV
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
    m = WhisperModel(MODELOS.get(modelo, modelo), device="cpu", compute_type="int8")
    segs, info = m.transcribe(
        audio, language=None if lang in ("", "auto") else lang, word_timestamps=True,
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 400, "speech_pad_ms": 200},
        condition_on_previous_text=False, initial_prompt=prompt or None, beam_size=5,
        hallucination_silence_threshold=2.0, temperature=[0.0, 0.2, 0.4])
    ws = []
    for s in segs:
        if s.no_speech_prob > 0.75 and s.avg_logprob < -1.0:
            continue
        for w in s.words or []:
            t = w.word.strip()
            if t and w.end > w.start and w.probability > 0.15:
                ws.append({"word": t, "start": round(w.start, 3), "end": round(w.end, 3)})
    antes = len(ws)
    ws = limpar_repeticoes(ws)
    print(f"transcrição: {len(ws)} palavras, idioma {info.language}"
          + (f" ({antes - len(ws)} repetidas cortadas)" if antes > len(ws) else ""), flush=True)
    path = os.path.join(trab, "palavras.json")
    json.dump(em_blocos(ws), open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return path


def normalizar_palavras(path, trab):
    """Aceita whisper_json (segments[].words[]) ou lista simples [{word,start,end}] / [[s,e,w]]."""
    d = json.load(open(path, encoding="utf-8"))
    if isinstance(d, dict) and d.get("segments"):
        return path
    palavras = []
    for x in d:
        if isinstance(x, dict):
            palavras.append({"word": x.get("word") or x.get("text"), "start": x["start"], "end": x["end"]})
        else:
            palavras.append({"word": x[2], "start": x[0], "end": x[1]})
    palavras = [dict(p, word=p["word"].strip()) for p in palavras if (p["word"] or "").strip()]
    novo = os.path.join(trab, "palavras.json")
    json.dump(em_blocos(limpar_repeticoes(palavras)), open(novo, "w", encoding="utf-8"), ensure_ascii=False)
    return novo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entrada"); ap.add_argument("saida")
    ap.add_argument("--estilo", default="viral")
    ap.add_argument("--palavras")
    ap.add_argument("--destaques", default="")
    ap.add_argument("--emojis", default="")
    ap.add_argument("--posicao", type=float)
    ap.add_argument("--som", action="store_true")
    ap.add_argument("--fonte", choices=sorted(FONTES_LEGENDA))
    ap.add_argument("--compacta", choices=sorted(COMPACTA))
    ap.add_argument("--blocos", action="store_true", help="--palavras já vem em blocos revisados (legenda_inteligente.py montar)")
    ap.add_argument("--lang", default="pt")
    ap.add_argument("--modelo", default="turbo")
    ap.add_argument("--prompt", default="")
    ap.add_argument("--qualidade", default="very_high")
    ap.add_argument("--preview", default="", help="ex.: 3,9 (só esse trecho, baixa qualidade)")
    a = ap.parse_args()

    destaques = [w.strip() for w in a.destaques.split(",") if w.strip()]
    emojis = json.loads(a.emojis) if a.emojis.strip() else {}
    trab = tempfile.mkdtemp(prefix="legenda_")
    try:
        cfg = montar_config(a.estilo, trab, destaques, emojis, a.posicao, a.som, a.fonte, a.blocos, a.compacta)
        cmd = ["pycaps", "render", "--input", os.path.abspath(a.entrada), "--output", os.path.abspath(a.saida),
               "--config", cfg, "--video-quality", a.qualidade]
        palavras = normalizar_palavras(os.path.abspath(a.palavras), trab) if a.palavras else \
            transcrever(a.entrada, a.lang, a.modelo, a.prompt, trab)
        if not json.load(open(palavras, encoding="utf-8"))["segments"]:
            print("AVISO_SEM_FALA nenhuma fala detectada; vídeo copiado sem legenda")
            shutil.copyfile(a.entrada, a.saida); print(f"LEGENDA_OK {a.saida}"); return
        cmd += ["--transcript", palavras, "--transcript-format", "whisper_json"]
        if a.preview:
            cmd += ["--preview-time", a.preview]
        print("legendando:", os.path.basename(a.entrada), "estilo", a.estilo, flush=True)
        r = subprocess.run(cmd, cwd=trab)
        if r.returncode != 0 or not os.path.exists(a.saida):
            sys.exit(f"ERRO_LEGENDA pycaps falhou (código {r.returncode})")
        print(f"LEGENDA_OK {a.saida}")
    finally:
        shutil.rmtree(trab, ignore_errors=True)


if __name__ == "__main__":
    main()
