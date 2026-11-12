---
name: cortes-de-live
description: Faz cortes de lives (GTA 6 e outras) a partir só de um link da Twitch, YouTube ou Kick, usando o robô no GitHub netao8090/cortes-lives-app. Use quando o usuário mandar um link de live/VOD/canal e pedir cortes.
---

# Cortes de live a partir de um link

O usuário manda **só um link** (live, VOD ou canal da Twitch). Quem baixa e renderiza é o robô no GitHub Actions do repositório `netao8090/cortes-lives-app` (o ambiente do Claude não acessa Twitch/YouTube/Kick). Quem **escolhe os cortes é o Claude**, lendo a transcrição.

## Preparação (uma vez por sessão)
1. Anexe o repositório com `add_repo` (owner `netao8090`, repo `cortes-lives-app`, access `push`) e clone em `/home/claude/cortes-lives-app`.
2. Todos os comandos `gh` usam `-R netao8090/cortes-lives-app`.

## Passo a passo
1. **Nome do trabalho (job):** `AAAA-MM-DD-canal` (minúsculo, sem espaço; acrescente `-2`, `-3` se já existir em `jobs/`).
   - Se o usuário pedir só um pedaço ("as últimas 2 horas", "de 1:00:00 a 2:30:00"), passe `inicio`/`fim` em h:mm:ss.
   - Lives com mais de ~5 h: analise em partes (ex.: 0:00:00–3:00:00 e 3:00:00–fim, jobs `-p1`, `-p2`), porque o robô tem limite de ~5,5 h por execução.
2. **Analisar:**
   `gh workflow run analisar.yml -R netao8090/cortes-lives-app -f url="<link>" -f job="<job>"`
   Pegue o id da execução (`gh run list -R ... --workflow analisar.yml -L 1 --json databaseId,status`) e espere com
   `gh run watch <id> -R ... --exit-status` rodando em background. Tempo típico: ~¼ da duração da live (1 h de live ≈ 15 min).
   Avise o usuário em uma linha quanto tempo deve levar.
   Se falhar, leia `gh run view <id> --log-failed` e explique em linguagem simples (VOD privado/só inscritos, YouTube pedindo "não sou robô", live do YouTube/Kick ainda no ar → mandar o link quando virar VOD).
3. **Ler:** `git -C /home/claude/cortes-lives-app pull`, depois leia `jobs/<job>/meta.json`, `transcricao.txt` (em partes, se for longa) e `picos.txt`.
   - `!!` na transcrição = fala com volume muito alto (grito, susto, comemoração).
   - `picos.txt` = barulho alto sem fala (explosão, batida, risada). Combine com o que é dito logo antes/depois.
4. **Escolher 5–8 cortes** (ou quantos o usuário pedir). Critérios para GTA:
   - Reação forte (susto, raiva, gargalhada), fail/bug engraçado, perseguição/fuga com desfecho, jogada absurda, fala marcante, interação com chat/doação, plot twist.
   - O corte tem que se entender sozinho: começa 1–3 s antes do gancho (com o contexto mínimo) e termina logo depois do clímax/punchline.
   - Shorts: 20–60 s (máx. 90 s). Nunca cortar no meio de frase.
   - Evite: telas de loading/espera, publi/merchan, trechos com música tocando ao fundo (strike de direitos autorais), momentos que só fazem sentido com a imagem se a transcrição não deixa claro.
   - Prefira cortes com fala + `!!`/pico próximos.
5. **Escrever** `jobs/<job>/cortes.json`:
   ```json
   {"formato": "vertical", "layout": "blur", "zoom": 1.3, "legenda": true,
    "cortes": [{"id": "01", "inicio": "1:02:31", "fim": "1:03:05", "titulo": "ELE NÃO ESPERAVA ISSO"}]}
   ```
   - `formato`: vertical (padrão), horizontal ou ambos. `layout: facecam` + `"facecam": {"x","y","w","h"}` (pixels do vídeo original) põe a câmera do streamer em cima.
   - `titulo` aparece no vídeo: curto (até ~35 caracteres), em CAIXA ALTA, **sem emoji**.
   E `jobs/<job>/publicacao.md`, com um bloco por corte: título para YouTube/TikTok (até 70 caracteres, com gancho), descrição de 1–2 linhas com **crédito obrigatório** ("Créditos: <canal> – <link original>"), hashtags (#gta6 #gtavi #shorts #cortes + do streamer), ideia de thumbnail.
6. **Renderizar:** commit + push dos dois arquivos (`git pull --rebase` antes), depois
   `gh workflow run renderizar.yml -R netao8090/cortes-lives-app -f job="<job>"` e espere igual ao passo 2 (poucos minutos; só os trechos escolhidos são baixados).
7. **Entregar:** `gh release download <job> -R netao8090/cortes-lives-app -D /home/claude/saida/<job>`.
   Confira 1 frame de cada vídeo vertical (ffmpeg → png → Read). Envie os .mp4 e o publicacao.md com SendUserFile.
   Resposta final curta: quantos cortes, uma linha por corte (tempo na live + por que é bom), e que dá para pedir ajustes ("refaz o 03 começando 5 s antes", "troca o título do 02", "quero com facecam").

## Ajustes
- Refazer só alguns: edite `cortes.json`, push e rode `renderizar.yml` com `-f so="03,05"` (substitui os arquivos na Release).
- Legenda/fontes/cores ficam em `scripts/cortar.py` (`gerar_ass`).

## Avisos ao usuário (uma vez, sem sermão)
- Cortar live de terceiros sem permissão pode gerar strike/desmonetização; muitos streamers liberam cortes com crédito.
- YouTube às vezes bloqueia o download vindo de servidor; Twitch é o mais confiável.
