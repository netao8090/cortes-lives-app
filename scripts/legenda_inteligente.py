#!/usr/bin/env python3
"""
Legenda inteligente: transcrição palavra por palavra + quem está falando + blocos naturais,
num formato que o Claude revisa (corrige palavras, quebras de frase e falante) antes de gravar no vídeo.

  transcrever VIDEO SAIDA.bruto.json [--lang pt] [--modelo turbo] [--prompt "..."] [--falantes 0]
      faster-whisper (tempo de cada palavra) + separação de vozes do sherpa-onnx (pyannote 3.0 + TitaNet).
      Sai: palavras com tempo e falante, e "blocos" sugeridos para revisar.

  montar BRUTO.json EDITADO.json SAIDA.json
      EDITADO = {"blocos": [{"f": 1, "texto": "..."}, ...]} na mesma ordem da fala (o Claude pode corrigir
      texto, juntar/separar blocos, trocar falante ou apagar um bloco com texto vazio).
      O texto revisado é alinhado às palavras originais para herdar o tempo exato de cada uma.
      Sai: whisper_json pronto para o legendar.py --blocos.
"""
import argparse, difflib, json, os, re, subprocess, sys, unicodedata

AQUI = os.path.dirname(os.path.abspath(__file__))
MODELOS = os.path.join(AQUI, "..", "models")
SEG_MODEL = os.path.join(MODELOS, "sherpa-onnx-pyannote-segmentation-3-0", "model.onnx")
EMB_MODEL = os.path.join(MODELOS, "nemo_en_titanet_small.onnx")
MARCA_F2 = "⁠"          # caractere invisível: marca as palavras de quem não é o falante principal
TRAVESSAO = "— "   # "— " antes da fala de outra pessoa (convenção de legenda profissional)
FRACAS = {"de", "da", "do", "das", "dos", "o", "a", "os", "as", "e", "que", "pra", "pro", "pros", "pras",
          "um", "uma", "uns", "umas", "no", "na", "nos", "nas", "num", "numa", "em", "com", "se", "por",
          "pelo", "pela", "ao", "aos", "à", "às", "mas", "ou", "nem", "meu", "minha", "seu", "sua",
          "the", "an", "of", "to", "and", "in", "on", "el", "la", "los", "las", "y", "en", "con"}


def norm(t):
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if c.isalnum())


def audio16k(video):
    import numpy as np
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0


# ------------------------------------------------------------------ transcrição
def transcrever_palavras(audio, lang, modelo, prompt):
    sys.path.insert(0, AQUI)
    from legendar import MODELOS as NOMES, limpar_repeticoes
    from faster_whisper import WhisperModel
    m = WhisperModel(NOMES.get(modelo, modelo), device="cpu", compute_type="int8")
    segs, info = m.transcribe(
        audio, language=None if lang in ("", "auto") else lang, word_timestamps=True,
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 150},
        condition_on_previous_text=False, initial_prompt=prompt or None, beam_size=5,
        hallucination_silence_threshold=2.0, temperature=[0.0, 0.2, 0.4])
    ws = []
    for s in segs:
        if s.no_speech_prob > 0.75 and s.avg_logprob < -1.0:
            continue
        for w in s.words or []:
            t = w.word.strip()
            if t and w.end > w.start and w.probability > 0.12:
                ws.append({"w": t, "s": round(w.start, 3), "e": round(w.end, 3), "p": round(w.probability, 2)})
    ws = [{"w": x["word"], "s": x["start"], "e": x["end"], "p": x["p"]}
          for x in limpar_repeticoes([{"word": y["w"], "start": y["s"], "end": y["e"], "p": y["p"]} for y in ws])]
    return ws, info.language


def separar_falantes(audio, n=0, limiar=0.6):
    if not (os.path.exists(SEG_MODEL) and os.path.exists(EMB_MODEL)):
        print("AVISO_SEM_DIARIZACAO modelos de voz ausentes; tudo como um falante só")
        return []
    import sherpa_onnx
    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=SEG_MODEL)),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=EMB_MODEL),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=n if n > 0 else -1, threshold=limiar),
        min_duration_on=0.25, min_duration_off=0.4)
    if not cfg.validate():
        print("AVISO_SEM_DIARIZACAO configuração inválida"); return []
    sd = sherpa_onnx.OfflineSpeakerDiarization(cfg)
    return [(r.start, r.end, r.speaker) for r in sd.process(audio).sort_by_start_time()]


def atribuir_falantes(ws, segs):
    if not segs:
        for w in ws:
            w["f"] = 1
        return 1
    for i, w in enumerate(ws):
        sobre = {}
        for s, e, k in segs:
            o = min(w["e"], e) - max(w["s"], s)
            if o > 0:
                sobre[k] = sobre.get(k, 0) + o
        if sobre:
            w["f"] = max(sobre, key=sobre.get)
        else:
            perto = min(segs, key=lambda x: min(abs(x[0] - w["e"]), abs(x[1] - w["s"])))
            dist = min(abs(perto[0] - w["e"]), abs(perto[1] - w["s"]))
            w["f"] = perto[2] if dist < 0.6 else (ws[i - 1]["f"] if i else perto[2])
    # suaviza: troca de falante numa palavra solta (< 0.5 s) entre falas do mesmo falante é ruído
    for i in range(1, len(ws) - 1):
        if ws[i - 1]["f"] == ws[i + 1]["f"] != ws[i]["f"] and ws[i]["e"] - ws[i]["s"] < 0.5:
            ws[i]["f"] = ws[i - 1]["f"]
    # falante principal (mais palavras) vira 1, o resto 2, 3...
    cont = {}
    for w in ws:
        cont[w["f"]] = cont.get(w["f"], 0) + 1
    ordem = {k: i + 1 for i, k in enumerate(sorted(cont, key=lambda k: -cont[k]))}
    for w in ws:
        w["f"] = ordem[w["f"]]
    return len(ordem)


def sugerir_blocos(ws, max_chars=20, max_pal=4, pausa=0.45):
    """Blocos curtos e naturais: quebra em troca de falante, pausa, fim de frase; não termina em palavra fraca."""
    blocos, atual = [], []

    def fechar():
        if atual:
            blocos.append(list(atual)); atual.clear()

    for i, w in enumerate(ws):
        if atual:
            ant = atual[-1]
            txt = " ".join(x["w"] for x in atual + [w])
            if (w["f"] != ant["f"] or w["s"] - ant["e"] >= pausa or len(atual) >= max_pal
                    or len(txt) > max_chars):
                # não deixa a linha acabar em "de", "o", "que"... : leva a palavra fraca junto
                if (w["f"] == ant["f"] and w["s"] - ant["e"] < pausa and len(atual) >= 2
                        and norm(ant["w"]) in FRACAS):
                    leva = atual.pop()
                    fechar(); atual.append(leva)
                else:
                    fechar()
        atual.append(w)
        if re.search(r"[.!?]$", w["w"]):
            fechar()
    fechar()
    return [{"f": b[0]["f"], "texto": " ".join(x["w"] for x in b),
             "de": round(b[0]["s"], 2), "ate": round(b[-1]["e"], 2)} for b in blocos]


def cmd_transcrever(a):
    audio = audio16k(a.video)
    ws, lang = transcrever_palavras(audio, a.lang, a.modelo, a.prompt)
    segs = separar_falantes(audio, a.falantes, a.limiar)
    n = atribuir_falantes(ws, segs)
    blocos = sugerir_blocos(ws)
    out = {"duracao": round(len(audio) / 16000, 2), "idioma": lang, "falantes": n,
           "palavras": ws, "blocos": blocos}
    os.makedirs(os.path.dirname(os.path.abspath(a.saida)), exist_ok=True)
    json.dump(out, open(a.saida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"TRANSCRITO {len(ws)} palavras, {n} falante(s), {len(blocos)} blocos, idioma {lang}")
    for b in blocos:
        print(f"  [{b['de']:6.2f}-{b['ate']:6.2f}] F{b['f']}: {b['texto']}")


# ------------------------------------------------------------------ montagem
def alinhar(orig, edit_tokens):
    """Dá a cada palavra revisada o tempo da palavra original correspondente (ou interpola)."""
    a = [norm(w["w"]) for w in orig]
    b = [norm(t) for t, _ in edit_tokens]
    tempos = [None] * len(edit_tokens)
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                tempos[j1 + k] = (orig[i1 + k]["s"], orig[i1 + k]["e"])
        elif op == "replace":
            s, e = orig[i1]["s"], orig[i2 - 1]["e"]
            pesos = [len(edit_tokens[j][0]) + 1 for j in range(j1, j2)]
            tot, t = sum(pesos), s
            for j, p in zip(range(j1, j2), pesos):
                d = (e - s) * p / tot
                tempos[j] = (t, t + d); t += d
    # inseridas: espremidas entre as vizinhas
    for j in range(len(tempos)):
        if tempos[j] is None:
            ant = next((tempos[k][1] for k in range(j - 1, -1, -1) if tempos[k]), 0.0)
            prox = next((tempos[k][0] for k in range(j + 1, len(tempos)) if tempos[k]), ant + 0.3)
            n_seq = 1
            while j + n_seq < len(tempos) and tempos[j + n_seq] is None:
                n_seq += 1
            d = max(0.12, (prox - ant) / n_seq) if prox > ant else 0.15
            for k in range(n_seq):
                tempos[j + k] = (ant + k * d, ant + (k + 1) * d)
    return tempos


def cmd_montar(a):
    bruto = json.load(open(a.bruto, encoding="utf-8"))
    edit = json.load(open(a.editado, encoding="utf-8"))
    blocos = [b for b in edit["blocos"] if (b.get("texto") or "").strip()]
    tokens = [(t, bi) for bi, b in enumerate(blocos) for t in b["texto"].split()]
    tempos = alinhar(bruto["palavras"], tokens)

    segs = []
    for bi, b in enumerate(blocos):
        ws = [{"word": t, "start": tempos[k][0], "end": tempos[k][1]}
              for k, (t, i) in enumerate(tokens) if i == bi]
        for k in range(1, len(ws)):  # tempos sempre em ordem
            ws[k]["start"] = max(ws[k]["start"], ws[k - 1]["end"])
            ws[k]["end"] = max(ws[k]["end"], ws[k]["start"] + 0.05)
        ws[-1]["word"] = re.sub(r"[,.;:]+$", "", ws[-1]["word"]) or ws[-1]["word"]
        if b.get("f", 1) != 1:
            ws[0]["word"] = TRAVESSAO + ws[0]["word"]
            for w in ws:
                w["word"] += MARCA_F2
        segs.append(ws)

    # tempo de tela: entra junto com a 1ª palavra; segura um pouco no fim, sem invadir o próximo bloco
    for i, ws in enumerate(segs):
        prox = segs[i + 1][0]["start"] if i + 1 < len(segs) else ws[-1]["end"] + 5
        if i + 1 < len(segs) and ws[-1]["end"] > prox - 0.04:
            ws[-1]["end"] = max(ws[-1]["start"] + 0.05, prox - 0.04)
        fim = min(ws[-1]["end"] + a.segurar, prox - 0.04)
        fim = max(fim, min(ws[0]["start"] + a.minimo, prox - 0.04), ws[-1]["end"])
        ws[-1]["end"] = round(fim, 3)
        for w in ws:
            w["start"], w["end"] = round(w["start"], 3), round(w["end"], 3)

    out = {"segments": [{"start": ws[0]["start"], "end": ws[-1]["end"],
                         "text": " ".join(w["word"] for w in ws), "words": ws} for ws in segs]}
    json.dump(out, open(a.saida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"MONTADO {len(segs)} blocos -> {a.saida}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("transcrever")
    t.add_argument("video"); t.add_argument("saida")
    t.add_argument("--lang", default="pt"); t.add_argument("--modelo", default="turbo")
    t.add_argument("--prompt", default=""); t.add_argument("--falantes", type=int, default=0)
    t.add_argument("--limiar", type=float, default=0.6)
    m = sub.add_parser("montar")
    m.add_argument("bruto"); m.add_argument("editado"); m.add_argument("saida")
    m.add_argument("--segurar", type=float, default=0.25, help="segundos que o bloco fica depois da última palavra")
    m.add_argument("--minimo", type=float, default=0.6, help="tempo mínimo de tela de um bloco")
    a = ap.parse_args()
    cmd_transcrever(a) if a.cmd == "transcrever" else cmd_montar(a)


if __name__ == "__main__":
    main()
