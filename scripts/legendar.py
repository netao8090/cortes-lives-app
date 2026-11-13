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
    font-size: 30px;
    color: #FFFFFF;
    letter-spacing: 0.5px;
    -webkit-text-stroke: 1.6px #000;
    paint-order: stroke fill;
    text-shadow:
        -2.5px -2.5px 0 #000, 2.5px -2.5px 0 #000, -2.5px 2.5px 0 #000, 2.5px 2.5px 0 #000,
        0 3px 0 #000, 0 -3px 0 #000, 3px 0 0 #000, -3px 0 0 #000,
        0 5px 8px rgba(0,0,0,0.55);
    padding: 2px 6px;
}
.word-not-narrated-yet { color: #FFFFFF; }
.word-already-narrated { color: #FFFFFF; }
.word-being-narrated { color: #FFE81F; }
.word.destaque { color: #39FF6A; font-size: 36px; }
.word.destaque.word-being-narrated { color: #39FF6A; }
"""

CSS_EXPLOSIVO = """
.word { text-transform: uppercase; font-size: 30px; }
.word.destaque { font-size: 38px; color: #FFFFFF; }
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
.word.destaque { color: #FF3DCB; font-size: 35px;
    text-shadow: 0 0 2px #000, 3px 3px 0 #000, 0 0 14px rgba(255,61,203,0.9); }
"""

ANIM_DESTAQUE = {"type": "zoom_in_primitive", "when": "narration-starts", "what": "word", "duration": 0.18,
                 "init_scale": 0.55, "overshoot": {"amount": 0.18, "peak_at": 0.6}, "tag_condition": "destaque"}

ESTILOS = {
    "viral": {"base": "hype", "css": CSS_VIRAL, "posicao": 0.66, "max_chars": 16,
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


def montar_config(estilo, trab, destaques, emojis, posicao, som):
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
        cfg["animations"] = cfg.get("animations", []) + proprio.get("extra_anim", [])
        if proprio.get("max_chars"):
            cfg["splitters"] = [{"type": "split_into_sentences"},
                                {"type": "limit_by_chars", "min_chars": 8, "max_chars": proprio["max_chars"],
                                 "avoid_finishing_segment_with_word_shorter_than": 3}]
        cfg.setdefault("layout", {})["max_number_of_lines"] = 2
    else:
        css += "\n.word.destaque { filter: brightness(1.15); font-size: 1.2em; }\n"
    css_path = os.path.join(trab, "styles.css")
    open(css_path, "w", encoding="utf-8").write(css)
    cfg["css"] = css_path
    res = os.path.join(pdir, cfg.get("resources", "resources"))
    if os.path.isdir(res):
        cfg["resources"] = res
    else:
        cfg.pop("resources", None)

    regras = list(cfg.get("tagger_rules", []))
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
    palavras = [p for p in palavras if (p["word"] or "").strip()]
    out = {"segments": [{"start": palavras[0]["start"], "end": palavras[-1]["end"],
                         "text": " ".join(p["word"].strip() for p in palavras), "words": palavras}]} if palavras \
        else {"segments": []}
    novo = os.path.join(trab, "palavras.json")
    json.dump(out, open(novo, "w", encoding="utf-8"), ensure_ascii=False)
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
        cfg = montar_config(a.estilo, trab, destaques, emojis, a.posicao, a.som)
        cmd = ["pycaps", "render", "--input", os.path.abspath(a.entrada), "--output", os.path.abspath(a.saida),
               "--config", cfg, "--video-quality", a.qualidade]
        if a.palavras:
            cmd += ["--transcript", normalizar_palavras(a.palavras, trab), "--transcript-format", "whisper_json"]
        else:
            cmd += ["--whisper-backend", "faster", "--whisper-model", a.modelo]
            if a.lang and a.lang != "auto":
                cmd += ["--lang", a.lang]
            if a.prompt:
                cmd += ["--whisper-prompt", a.prompt]
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
