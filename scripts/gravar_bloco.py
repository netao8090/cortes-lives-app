#!/usr/bin/env python3
"""
Grava UM bloco de uma live ao vivo (Kick ou Twitch) e prepara tudo para o Claude escolher os cortes.

  gravar_bloco.py <url_do_canal> --canal <slug> --bloco 60 [--sobreposicao 3] [--espera 150]

O que faz, na ordem:
  1. grava o vídeo (qualidade original, sem recompressão) em pedaços de 10 min + o chat;
  2. TRANSCREVE cada pedaço assim que ele fica pronto (a análise já está quase pronta quando o bloco fecha);
  3. ~3 min antes do fim do bloco, dispara o PRÓXIMO bloco (outra máquina), para não ficar buraco;
  4. quando o bloco fecha: junta tudo, analisa o chat e salva jobs/<job>/ no repositório
     (status.json = {"etapa": "aguardando_cortes"});
  5. espera o Claude escrever jobs/<job>/cortes.json; renderiza e publica numa Release com o nome do job;
  6. status.json = {"etapa": "renderizado"}.

Saída "offline" (live acabou / não está no ar) termina sem erro.
"""
import argparse, datetime, glob, json, os, subprocess, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gravar  # noqa: E402  (resolver, chat_kick, chat_twitch, PARAR)

SEG = int(os.environ.get("SEG_SEGUNDOS", 600))  # pedaço de 10 min
TESTE = os.environ.get("TESTE_STREAM")  # testes locais: arquivo tocado em tempo real
SEM_GIT = bool(os.environ.get("SEM_GIT"))
REPO = os.environ.get("GITHUB_REPOSITORY", "")
RUN_ID = os.environ.get("GITHUB_RUN_ID", "")
WORKFLOW = "gravar-bloco.yml"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def gh(*args, check=False):
    r = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr[:300])
    return r


def duracao(arq):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", arq],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def git_salvar(caminho, msg):
    if SEM_GIT:
        return True
    subprocess.run(["git", "add", caminho])
    if subprocess.run(["git", "commit", "-q", "-m", msg]).returncode != 0:
        return True
    for i in range(8):
        if subprocess.run(["git", "pull", "-q", "--rebase", "--autostash"]).returncode == 0 and \
           subprocess.run(["git", "push", "-q"]).returncode == 0:
            return True
        time.sleep(5 * (i + 1))
    return False


def ao_vivo(url):
    if TESTE:
        return {"plataforma": "teste", "canal": "teste", "titulo": "live de teste", "m3u8": TESTE, "chatroom": None}
    try:
        return gravar.resolver(url)
    except SystemExit:
        return None


def duplicado(canal):
    """Outra gravação do mesmo canal começou quase junto (vigia + sucessor ao mesmo tempo)? A mais antiga fica."""
    if not (REPO and RUN_ID):
        return False
    r = gh(f"repos/{REPO}/actions/workflows/{WORKFLOW}/runs?per_page=30")
    try:
        runs = json.loads(r.stdout)["workflow_runs"]
    except Exception:
        return False
    eu = next((x for x in runs if str(x["id"]) == RUN_ID), None)
    if not eu:
        return False
    t_eu = datetime.datetime.fromisoformat(eu["created_at"].replace("Z", "+00:00"))
    for x in runs:
        if str(x["id"]) == RUN_ID or x["status"] not in ("queued", "in_progress"):
            continue
        if x.get("display_title", "").split()[-1:] != [canal]:
            continue
        t = datetime.datetime.fromisoformat(x["created_at"].replace("Z", "+00:00"))
        if abs((t - t_eu).total_seconds()) < 240 and x["id"] < int(RUN_ID):
            return True
    return False


def disparar_sucessor(url, canal, bloco, espera):
    r = gh("-X", "POST", f"repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches", "-f", "ref=main",
           "-f", f"inputs[url]={url}", "-f", f"inputs[canal]={canal}",
           "-f", f"inputs[bloco]={bloco}", "-f", f"inputs[espera]={espera}")
    log("próximo bloco disparado" if r.returncode == 0 else f"falha ao disparar próximo bloco: {r.stderr[:200]}")


class Transcritor(threading.Thread):
    """Transcreve os pedaços de 10 min conforme ficam prontos."""

    def __init__(self, pasta, saida):
        super().__init__(daemon=True)
        self.fila, self.pasta, self.saida = [], pasta, saida
        self.lock = threading.Lock()
        self.fim = threading.Event()
        self.feitos = []  # (offset, pasta_resultado)

    def add(self, arq, offset):
        with self.lock:
            self.fila.append((arq, offset))

    def run(self):
        aqui = os.path.dirname(os.path.abspath(__file__))
        while True:
            with self.lock:
                item = self.fila.pop(0) if self.fila else None
            if item is None:
                if self.fim.is_set():
                    return
                time.sleep(5)
                continue
            arq, off = item
            out = os.path.join(self.pasta, "tr_" + os.path.basename(arq).replace(".ts", ""))
            log(f"transcrevendo pedaço {os.path.basename(arq)} (início {off/60:.1f} min)")
            r = subprocess.run([sys.executable, os.path.join(aqui, "transcrever.py"), arq, "--saida", out,
                                "--offset", f"{off:.2f}", "--threads", "3"], capture_output=True, text=True)
            if r.returncode != 0:
                log("falha transcrevendo:", r.stderr[-300:])
            self.feitos.append((off, out))

    def juntar(self):
        trans, txt, picos = [], [], []
        for off, out in sorted(self.feitos):
            try:
                trans += json.load(open(os.path.join(out, "transcricao.json"), encoding="utf-8"))
                txt.append(open(os.path.join(out, "transcricao.txt"), encoding="utf-8").read())
                picos.append(open(os.path.join(out, "picos.txt"), encoding="utf-8").read())
            except Exception as e:
                log("pedaço sem transcrição:", out, e)
        os.makedirs(self.saida, exist_ok=True)
        json.dump(trans, open(os.path.join(self.saida, "transcricao.json"), "w", encoding="utf-8"), ensure_ascii=False)
        open(os.path.join(self.saida, "transcricao.txt"), "w", encoding="utf-8").write("".join(txt))
        open(os.path.join(self.saida, "picos.txt"), "w", encoding="utf-8").write("".join(picos))
        return len(trans)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--canal", required=True)
    ap.add_argument("--bloco", type=float, default=60, help="minutos por bloco (padrão 1 hora)")
    ap.add_argument("--sobreposicao", type=float, default=3, help="minutos de sobra entre blocos")
    ap.add_argument("--espera", type=float, default=150, help="minutos esperando o Claude escolher os cortes")
    ap.add_argument("--pasta", default="/mnt/rec")
    a = ap.parse_args()

    info = ao_vivo(a.url)
    if not info:
        log(f"{a.canal} não está ao vivo. Nada a fazer.")
        return
    if duplicado(a.canal):
        log("outra gravação deste canal começou junto; esta sai para não duplicar.")
        return

    inicio = time.time()
    job = time.strftime("%Y-%m-%d-%H%M", time.gmtime(inicio)) + f"-{a.canal}"
    jobdir = os.path.join("jobs", job)
    pasta = os.path.join(a.pasta, job)
    os.makedirs(jobdir, exist_ok=True); os.makedirs(pasta, exist_ok=True)
    log(f"bloco {job}: {info.get('titulo')!r}, {a.bloco:.0f} min")

    # relógio: horário real -> segundos no vídeo gravado. Cada vez que o ffmpeg (re)conecta, anota
    # o horário em que começou e quanto vídeo já existia antes; quedas de conexão não contam.
    estado = {"parede": None, "base": 0.0}

    def relogio(agora):
        # mensagens de antes da gravação (a API da Kick devolve as últimas) ou durante quedas: descarta
        if estado["parede"] is None or agora < estado["parede"]:
            return None
        return estado["base"] + (agora - estado["parede"])

    chat = gravar.Chat(os.path.join(jobdir, "chat.jsonl"), relogio)
    if info["plataforma"] in ("kick", "twitch"):
        alvo = gravar.chat_kick if info["plataforma"] == "kick" else gravar.chat_twitch
        threading.Thread(target=alvo, args=(info["chatroom"], chat), daemon=True).start()

    tr = Transcritor(pasta, jobdir)
    tr.start()

    fim_bloco = inicio + a.bloco * 60
    sucessor_em = fim_bloco - a.sobreposicao * 60
    sucessor_feito = False
    pedacos = []  # (arquivo, offset no vídeo do bloco)
    run_n, offline = 0, 0
    while time.time() < fim_bloco - 5:
        resta = fim_bloco - time.time()
        padrao = os.path.join(pasta, f"r{run_n:02d}_%03d.ts")
        estado["parede"] = time.time()
        entrada = ["-re", "-i", info["m3u8"]] if TESTE else ["-i", info["m3u8"]]
        p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", *entrada, "-map", "0:v:0", "-map", "0:a:0?",
                              "-c", "copy", "-t", f"{resta:.0f}", "-f", "segment", "-segment_time", str(SEG),
                              "-reset_timestamps", "1", padrao])
        entregues, acc = set(), [0.0]  # acc = vídeo já fechado neste run

        def entregar_prontos(final=False):
            arqs = sorted(glob.glob(os.path.join(pasta, f"r{run_n:02d}_*.ts")))
            for f in (arqs if final else arqs[:-1]):  # o último ainda está sendo escrito
                if f in entregues:
                    continue
                entregues.add(f)
                d = duracao(f)
                if d < 1:
                    continue
                off = estado["base"] + acc[0]
                acc[0] += d
                pedacos.append((f, off))
                tr.add(f, off)

        while p.poll() is None:
            time.sleep(15)
            entregar_prontos()
            if not sucessor_feito and time.time() >= sucessor_em:
                if ao_vivo(a.url) and not TESTE:
                    disparar_sucessor(a.url, a.canal, int(a.bloco), int(a.espera))
                sucessor_feito = True
        entregar_prontos(final=True)
        estado["base"] += acc[0]
        estado["parede"] = None
        run_n += 1
        if time.time() >= fim_bloco - 5:
            break
        time.sleep(5)
        novo = ao_vivo(a.url)
        if not novo:
            offline += 1
            if offline >= 3:
                log("live acabou.")
                break
            time.sleep(20)
            continue
        offline = 0
        info["m3u8"] = novo["m3u8"]
        log("reconectando ao stream...")

    gravar.PARAR.set(); time.sleep(1); chat.f.flush()
    total = sum(duracao(f) for f, _ in pedacos)
    log(f"gravado: {total/60:.1f} min em {len(pedacos)} pedaços; {chat.n} mensagens de chat")
    if total < float(os.environ.get("MIN_SEGUNDOS", 300)):
        log("bloco curto demais (< 5 min); não vale cortar.")
        return

    # junta o vídeo do bloco
    lista = os.path.join(pasta, "lista.txt")
    with open(lista, "w") as f:
        for arq, _ in pedacos:
            f.write(f"file '{arq}'\n")
    video = os.path.join(pasta, "bloco.ts")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lista, "-c", "copy", video], check=True)

    tr.fim.set(); tr.join()
    n = tr.juntar()
    for arq, _ in pedacos:
        os.remove(arq)
    subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "analisar_chat.py"), jobdir])

    meta = {"url_original": a.url, "url": "file://" + video, "titulo": info.get("titulo"), "canal": info["canal"],
            "plataforma": info["plataforma"], "gravado_ao_vivo": True, "bloco": True,
            "inicio_bloco_utc": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(inicio)),
            "duracao": total, "falas": n, "mensagens_chat": chat.n, "offset": 0.0}
    json.dump(meta, open(os.path.join(jobdir, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"etapa": "aguardando_cortes", "desde": time.time()},
              open(os.path.join(jobdir, "status.json"), "w"), indent=1)
    git_salvar(jobdir, f"bloco gravado: {job}")
    log(f"análise salva em {jobdir}; esperando o Claude escolher os cortes (até {a.espera:.0f} min)")

    limite = time.time() + a.espera * 60
    cortes = os.path.join(jobdir, "cortes.json")
    while time.time() < limite:
        if not SEM_GIT:
            subprocess.run(["git", "pull", "-q", "--rebase", "--autostash"], capture_output=True)
        if os.path.exists(cortes):
            break
        time.sleep(60)
    if not os.path.exists(cortes):
        log("ninguém escolheu os cortes a tempo.")
        json.dump({"etapa": "sem_cortes"}, open(os.path.join(jobdir, "status.json"), "w"))
        git_salvar(jobdir, f"bloco sem cortes: {job}")
        return
    plano = json.load(open(cortes, encoding="utf-8"))
    if not plano.get("cortes"):
        log("o Claude não achou nada que valesse corte neste bloco.")
        json.dump({"etapa": "sem_cortes"}, open(os.path.join(jobdir, "status.json"), "w"))
        git_salvar(jobdir, f"bloco sem cortes: {job}")
        return

    subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "renderizar.py"),
                    "--job", job], check=True)
    saida = os.path.join("saida", job)
    pub = os.path.join(jobdir, "publicacao.md")
    if os.path.exists(pub):
        subprocess.run(["cp", pub, saida])
    arqs = sorted(glob.glob(os.path.join(saida, "*")))
    if SEM_GIT:
        log("teste: cortes em", saida, sorted(os.listdir(saida)))
        return
    r = subprocess.run(["gh", "release", "create", job, *arqs, "--title", f"Cortes: {job}",
                        "--notes-file", pub if os.path.exists(pub) else "/dev/null"])
    if r.returncode != 0:
        subprocess.run(["gh", "release", "upload", job, *arqs, "--clobber"])
    json.dump({"etapa": "renderizado", "quando": time.time()}, open(os.path.join(jobdir, "status.json"), "w"), indent=1)
    git_salvar(jobdir, f"bloco renderizado: {job}")
    log("cortes publicados na Release", job)


if __name__ == "__main__":
    main()
