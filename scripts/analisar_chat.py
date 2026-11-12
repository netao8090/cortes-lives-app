#!/usr/bin/env python3
"""
Acha os momentos em que o CHAT explodiu (euforia, risada, hype).

  analisar_chat.py jobs/J
Lê jobs/J/chat.jsonl e escreve jobs/J/chat_picos.txt:
  - atividade por minuto (para ver o ritmo da live)
  - os maiores picos (janelas de 20 s) com nota, tipo de reação e exemplos de mensagens
"""
import collections, json, os, re, sys

RISO = re.compile(r"(k{4,}|kkk|haha|hehe|rsrs|lul|kekw|omegalul|lmao|lol|😂|🤣|:kekw:|:lul:|xd\b|jaja)", re.I)
HYPE = re.compile(r"(pog|poggers|letsgo|let'?s go|vamo+|bora+|caralho|carai|mds|meu deus|absurdo|insano|"
                  r"brabo|monstro|\bclipa?\b|\bw+\b|\bgg+\b|\bez\b|🔥|😱|😮|🤯|!!+|\?\?+|nossa|que isso|pqp)", re.I)
TRISTE = re.compile(r"(\bf+\b|\brip\b|\bno{3,}\b|ohno|sadge|😭|💀|\bperdeu\b|\bmorreu\b)", re.I)


def fmt(t):
    t = int(t)
    return f"{t//3600}:{t%3600//60:02d}:{t%60:02d}" if t >= 3600 else f"{t//60:02d}:{t%60:02d}"


def main(pasta):
    arq = os.path.join(pasta, "chat.jsonl")
    if not os.path.exists(arq):
        print("sem chat"); return
    msgs = [json.loads(l) for l in open(arq, encoding="utf-8") if l.strip()]
    saida = os.path.join(pasta, "chat_picos.txt")
    if len(msgs) < 20:
        open(saida, "w").write(f"chat com poucas mensagens ({len(msgs)})\n"); return
    fim = max(m["t"] for m in msgs)
    JAN, PASSO = 20, 5
    por_min = collections.Counter(int(m["t"] // 60) for m in msgs)
    media = len(msgs) / max(fim / JAN, 1)  # mensagens por janela, em média

    janelas = []
    t = 0.0
    while t <= fim:
        dentro = [m for m in msgs if t <= m["t"] < t + JAN]
        if dentro:
            n = len(dentro)
            riso = sum(1 for m in dentro if RISO.search(m["m"]))
            hype = sum(1 for m in dentro if HYPE.search(m["m"]))
            triste = sum(1 for m in dentro if TRISTE.search(m["m"]))
            caps = sum(1 for m in dentro if len(m["m"]) > 3 and m["m"].upper() == m["m"])
            repet = n - len(set(m["m"].lower().strip() for m in dentro))  # spam igual
            nota = n / max(media, 1) + 1.5 * (riso + hype + triste) / max(media, 1) + 0.5 * (caps + repet) / max(media, 1)
            janelas.append((nota, t, n, riso, hype, triste, dentro))
        t += PASSO

    janelas.sort(key=lambda x: -x[0])
    escolhidas = []
    for j in janelas:
        if all(abs(j[1] - e[1]) >= 45 for e in escolhidas):
            escolhidas.append(j)
        if len(escolhidas) >= 15:
            break
    escolhidas.sort(key=lambda x: x[1])

    with open(saida, "w", encoding="utf-8") as f:
        f.write(f"{len(msgs)} mensagens em {fmt(fim)} (média {media:.1f} por 20 s)\n\n")
        f.write("ATIVIDADE POR MINUTO (mensagens):\n")
        f.write("  ".join(f"{m:02d}:{por_min.get(m,0)}" for m in range(int(fim // 60) + 1)) + "\n\n")
        f.write("PICOS DO CHAT (nota = quantas vezes acima do normal; tipo = riso/hype/triste)\n")
        for nota, t, n, riso, hype, triste, dentro in escolhidas:
            tipo = max([("riso", riso), ("hype", hype), ("triste/fail", triste)], key=lambda x: x[1])
            tipo = tipo[0] if tipo[1] else "volume"
            # exemplos: primeiro as mensagens de reação, depois as mais repetidas
            cont = collections.Counter(m["m"][:60] for m in dentro)
            reac = [m["m"][:60] for m in dentro if RISO.search(m["m"]) or HYPE.search(m["m"]) or TRISTE.search(m["m"])]
            ex = []
            for txt in [x for x, _ in collections.Counter(reac).most_common()] + [x for x, _ in cont.most_common()]:
                if txt not in ex:
                    ex.append(txt)
                if len(ex) >= 6:
                    break
            f.write(f"[{fmt(t)}-{fmt(t+JAN)}] nota {nota:.1f}  {n} msgs  {tipo}  | " + " | ".join(ex) + "\n")
    print(open(saida, encoding="utf-8").read()[:3000])


if __name__ == "__main__":
    main(sys.argv[1])
