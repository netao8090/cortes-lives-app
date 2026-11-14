#!/usr/bin/env python3
"""
Vigia: confere os canais de canais.txt e, se algum está AO VIVO sem gravação em andamento,
dispara o gravador de blocos (gravar-bloco.yml).

canais.txt (uma linha por canal; # comenta):
  https://kick.com/yuri22            60
  https://www.twitch.tv/gaules       90
  (o número é o tamanho do bloco em minutos; padrão 60 = 1 hora)
"""
import datetime, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gravar_chat import status  # noqa: E402

REPO = os.environ["GITHUB_REPOSITORY"]
WF = "gravar-bloco.yml"


def gh(*a):
    return subprocess.run(["gh", "api", *a], capture_output=True, text=True)


def slug(url):
    return re.sub(r"[^a-z0-9_-]", "", url.rstrip("/").split("/")[-1].lower())


def gravando(canal, bloco):
    """Há gravação deste canal na fase de gravação (criada há menos de bloco+2 min)?"""
    r = gh(f"repos/{REPO}/actions/workflows/{WF}/runs?per_page=50")
    try:
        runs = json.loads(r.stdout)["workflow_runs"]
    except Exception:
        return True  # na dúvida, não duplica
    agora = datetime.datetime.now(datetime.timezone.utc)
    for x in runs:
        if x["status"] not in ("queued", "in_progress", "waiting", "pending", "requested"):
            continue
        if x.get("display_title", "").split()[-1:] != [canal]:
            continue
        t = datetime.datetime.fromisoformat(x["created_at"].replace("Z", "+00:00"))
        if (agora - t).total_seconds() < (bloco + 2) * 60:
            return True
    return False


def main():
    if not os.path.exists("canais.txt"):
        print("sem canais.txt"); return
    for ln in open("canais.txt", encoding="utf-8"):
        ln = ln.split("#")[0].strip()
        if not ln:
            continue
        partes = ln.split()
        url, bloco = partes[0], int(partes[1]) if len(partes) > 1 else 60
        if not url.startswith("http"):
            url = "https://" + url
        canal = slug(url)
        try:
            vivo = status(url).get("ao_vivo")
        except SystemExit as e:
            print(canal, "erro:", e); continue
        except Exception as e:
            print(canal, "erro checando:", str(e)[:120]); continue
        if not vivo:
            print(f"{canal}: offline"); continue
        if gravando(canal, bloco):
            print(f"{canal}: ao vivo, já está gravando"); continue
        r = gh("-X", "POST", f"repos/{REPO}/actions/workflows/{WF}/dispatches", "-f", "ref=main",
               "-f", f"inputs[url]={url}", "-f", f"inputs[canal]={canal}", "-f", f"inputs[bloco]={bloco}")
        print(f"{canal}: AO VIVO -> gravação iniciada" if r.returncode == 0 else f"{canal}: falha ao disparar {r.stderr[:200]}")


if __name__ == "__main__":
    main()
