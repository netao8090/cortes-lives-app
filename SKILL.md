---
name: cortes-de-live
description: Faz cortes virais de lives da Kick, Twitch ou YouTube só com o link do canal ou do VOD — inclusive de lives que ainda estão no ar, usando o chat como termômetro de euforia — grava legenda inteligente no vídeo (palavra por palavra, quem fala, posição que não cobre o personagem) e posta sozinho no TikTok e no Instagram Reels pelo Buffer, com legenda e hashtags (de graça), espalhando nos horários de pico. O trabalho pesado roda de graça no GitHub Actions do próprio usuário. Use quando pedirem cortes, clipes ou shorts de uma live, legenda no vídeo (inclusive de um vídeo avulso), ou para postar cortes.
---

# Cortes de live (Kick / Twitch / YouTube)

O usuário manda **só um link**. Quem baixa, transcreve e renderiza é um "robô" no **GitHub Actions do próprio usuário** (o ambiente do Claude não acessa Kick/Twitch/YouTube). Quem **escolhe os momentos é o Claude**, lendo a transcrição, os picos de voz e os picos do chat. O chat é só termômetro: **nunca aparece no vídeo**.

Resultado: cortes verticais 9:16 em 1080p com a webcam do streamer detectada sozinha (câmera em cima + jogo embaixo, ou retrato quando a câmera está em tela cheia) e um `publicacao.md` com título, descrição com crédito e hashtags. **Por padrão todo corte sai com a legenda inteligente** (passo 4b, detalhes em `LEGENDAR.md`): Montserrat Black compacta, só branco com o amarelo passando na palavra dita, quem fala separado, posição que não cobre o personagem, revisada por você antes de gravar. **O título na caixa amarela fica desligado** (o usuário tirou; só ligue `"titulo_no_video": true` se ele pedir). Corte sem legenda só se o usuário pedir explicitamente. Se a postagem automática estiver ligada, os cortes já saem **agendados** no TikTok e no Instagram Reels pela API grátis do Buffer, sem o usuário escolher nada.

Fale com o usuário em linguagem simples, sem jargão técnico. Ele não precisa saber de workflows, ramos ou API.

---

## 0. Primeira vez: montar o robô no GitHub do usuário

Pergunte o nome do repositório se ele ainda não disse (formato `usuario/repositorio`). Se não tiver um: peça para criar um repositório **público** vazio no GitHub (público = GitHub Actions grátis e sem limite de minutos).

1. `add_repo` com `access: "push"`. Se recusar o push, peça para instalar o app do Claude no GitHub com acesso a esse repositório (https://github.com/apps/claude/installations/select_target) ou reconectar o GitHub nos conectores do claude.ai.
2. Clone em `/home/claude/<repositorio>`.
3. Se o repositório ainda não tem `scripts/renderizar.py`: copie para a raiz dele **todos os arquivos do repositório modelo público `netao8090/cortes-lives-app`** (versão mais nova do robô: `.github/workflows/`, `scripts/`, `fonts/`, `fontes_legenda/`, `assets/`, `*.md`, `canais.txt`, `.gitignore`), **menos a pasta `jobs/`** (crie `jobs/.gitkeep`), faça commit e push. Se não conseguir acessar o modelo e esta skill tiver uma pasta `robo/`, use-a.
4. Daqui pra frente, use **só a API REST**: `R=repos/<usuario>/<repositorio>`. `gh workflow run`, `gh run watch` e `gh release download` usam GraphQL e falham nesta sessão.

Comandos que você vai usar:
- Disparar: `gh api -X POST $R/actions/workflows/<arquivo>.yml/dispatches -f ref=main -f 'inputs[chave]=valor' ...`
- Último run: `gh api "$R/actions/workflows/<arquivo>.yml/runs?per_page=1" --jq '.workflow_runs[0] | "\(.id) \(.status) \(.conclusion)"'`
- Esperar: loop de checagem a cada ~20 s (`timeout 20 tail -f /dev/null` no lugar de `sleep`) até `completed`.
- Log (só depois de terminar): `J=$(gh api $R/actions/runs/<id>/jobs --jq '.jobs[0].id'); gh api $R/actions/jobs/$J/logs | grep -E "ERRO|webcam|layout|ok /|fonte"`
- Baixar a Release: `gh api $R/releases/tags/<job> --jq '.assets[] | "\(.id) \(.name)"' | while read id n; do gh api -H "Accept: application/octet-stream" $R/releases/assets/$id > pasta/$n; done`

Os workflows do robô:
| Arquivo | Para quê | Entradas |
|---|---|---|
| `analisar.yml` | baixa **só o áudio** do VOD, transcreve (Whisper, idioma automático), marca gritos e junta o chat capturado | `url`, `job`, `inicio`, `fim` (h:mm:ss), `modelo` (small/base), `idioma` (auto), `depois_de` (unix: só aceita VOD que começou depois disso), `chat_de` (job de onde vem o chat) |
| `renderizar.yml` | baixa **só os trechos escolhidos** em 1080p, detecta a webcam **em cada corte**, renderiza e publica numa Release com o nome do job | `job`, `so` (ex.: `01,03`) |
| `chat.yml` | captura o chat de uma live **ao vivo** até ela acabar (salva no ramo `chat-<job>` a cada 10 min; limite ~5h40 por execução) | `url` (canal), `job`, `max_minutos` |
| `gravar.yml` | grava vídeo+chat de uma live ao vivo e renderiza do próprio arquivo (use só se o VOD não ficar disponível) | `url`, `job`, `minutos`, `espera` |
| `gravar-bloco.yml` | grava um bloco ao vivo, transcreve durante, encadeia o próximo bloco, espera os cortes e renderiza (ver 2b) | `url`, `canal`, `bloco` (min), `espera` (min) |
| `vigia.yml` | a cada ~10 min, liga `gravar-bloco.yml` para os canais de `canais.txt` que entraram ao vivo | — |
| `legendar.yml` | legenda inteligente em duas etapas: `rascunho` (transcreve palavra por palavra, separa vozes, escolhe posição) → você revisa → `gravar` (publica o legendado por cima de `corte_<id>_vertical.mp4`, guardando o `corte_<id>_limpo.mp4`); também legenda vídeo avulso (`video`) | `etapa`, `job`, `video`, `so`, `estilo`, `opcoes` |
| `postar.yml` | agenda os cortes no TikTok e no Instagram pelo Buffer; roda sozinho de hora em hora para empurrar a reserva quando a fila de 10 do Buffer abre vaga; `teste=sim` confere as contas sem publicar | `job`, `so`, `teste` |

### Postagem automática
Configuração única (conta grátis no Buffer + segredo `BUFFER_API_KEY`) e todo o resto estão em **`POSTAR.md`**.

---

## 1. Live que JÁ ACABOU (ou VOD) — o caso mais comum

1. Nome do job: `AAAA-MM-DD-canal` (minúsculo, sem espaço).
2. Link do canal → o robô pega o último VOD. Twitch: funciona até durante a live. Kick: só depois que a live termina. YouTube: costuma bloquear servidores (`ERRO_YOUTUBE_BLOQUEOU`) — sugira Twitch/Kick.
3. Live curta (até ~4 h): um `analisar.yml`. Live longa: **divida em partes de ~3 h em paralelo** (jobs `<job>-p1`, `-p2`..., com `inicio`/`fim`; a última sem `fim`). Cada 1 h de áudio leva ~20-25 min.
4. Para teste rápido ou se o usuário pedir um trecho, use `inicio`/`fim`.

## 2. Live que está AO VIVO agora (Kick)

A Kick não deixa baixar o passado de uma live em andamento; o VOD completo só aparece quando ela acaba. Então:
1. Dispare `chat.yml` (url do canal, job `AAAA-MM-DD-canal`). Ele para sozinho quando a live acaba.
2. Diga ao usuário que ele pode desligar o PC; agende checagens com `send_later` a cada ~30 min (mensagem autoexplicativa, com os nomes dos jobs e o que fazer em cada caso).
3. Em cada checagem: `git fetch origin chat-<job>` e veja `jobs/<job>/live.json` nesse ramo.
   - `live_acabou: true` → disparar `analisar.yml` com `depois_de` = `inicio_live_ts` do live.json e `chat_de` = job do chat (em partes, se for longa).
   - Run terminou por tempo com a live no ar → redisparar `chat.yml` com o mesmo job (o arquivo é acrescentado).
   - **Se `inicio_live_ts` mudou** entre checagens, a live **reiniciou** (duas sessões). A sessão antiga já virou VOD: separe o chat dela (mensagens com `ts` < novo início) num ramo `chat-<job>-a` com um `live.json` contendo o início antigo, e analise essa sessão com `chat_de=<job>-a`.
4. Twitch ao vivo: dá para analisar o VOD direto (já existe durante a live); use `chat.yml` só se quiser o chat como termômetro.

## 2b. Vigia automático + cortes em blocos (live ao vivo, sem ninguém mandar link)

Para quem quer cortes **durante** a live, de bloco em bloco, sem precisar avisar:
- `canais.txt` na raiz do repositório: uma linha por canal, `link minutos_por_bloco` (ex.: `https://kick.com/yuri22 120`). Para ligar/desligar um canal, edite esse arquivo (commit + push).
- `vigia.yml` roda sozinho a cada ~10 min: se um canal está ao vivo e não há gravação, dispara `gravar-bloco.yml`.
- `gravar-bloco.yml` (run-name `gravar <canal>`): grava UM bloco (vídeo + chat), já transcrevendo em pedaços de 10 min durante a gravação; 3 min antes do fim dispara o próximo bloco (sem buraco); ao fechar, salva `jobs/<AAAA-MM-DD-HHMM>-<canal>/` com `transcricao.txt`, `picos.txt`, `chat_picos.txt`, `meta.json` e `status.json` = `{"etapa": "aguardando_cortes"}`. Depois espera até `espera` min (padrão 150) por `cortes.json`; renderiza do próprio arquivo gravado, publica a Release `<job>` e marca `"etapa": "renderizado"`. `cortes.json` com `"cortes": []` = bloco sem nada bom (marca `sem_cortes`).
- Parar tudo de um canal: tire-o do `canais.txt` e cancele os runs `gravar <canal>` em andamento (`gh api -X POST $R/actions/runs/<id>/cancel`).

**Parte do Claude (tarefa agendada de hora em hora):**
1. `git pull`; liste `jobs/*/status.json` com `"etapa": "aguardando_cortes"` e sem `cortes.json`.
2. Para cada bloco: leia `meta.json`, `transcricao.txt`, `picos.txt`, `chat_picos.txt` e escolha os cortes (padrão **3 por bloco**, os mais virais; critérios da seção 3). Tempos são do vídeo do bloco (começam em 00:00). Escreva `cortes.json` (vídeo limpo: `"legenda": false, "titulo_no_video": false`, `"layout": "auto"`) e `publicacao.md`; commit e push **logo**, um bloco por vez (o gravador está esperando).
3. Espere `status.json` virar `renderizado` (≈5-10 min) e faça o passo 4b (legenda inteligente) nesse job. Baixe a Release `<job>`, confira 1 quadro de cada corte e entregue com `SendUserFile` (status proactive) com uma linha por corte. Depois crie `jobs/<job>/entregue` (commit + push) para não entregar de novo.
4. Releases `renderizado` sem o arquivo `entregue` (de execuções anteriores): baixe e entregue também.

## 3. Escolher os cortes (a parte do Claude)

Depois do `analisar.yml`: `git pull` e leia de cada parte:
- `transcricao.txt` — `[h:mm:ss-h:mm:ss] texto`; `!!` = fala com volume muito alto.
- `picos.txt` — barulho alto sem fala (explosão, risada).
- `chat_picos.txt` — janelas em que o chat explodiu (nota = vezes acima do normal; tipo riso/hype/triste) com exemplos de mensagens. Diz a partir de quando o chat existe.
- `meta.json` — confira título e duração para ter certeza de que é o VOD certo.

Transcrições longas: ranqueie janelas de ~40 s por energia (`transcricao.json` tem `energia` 0-1) e por exclamações, e leia o texto em volta das melhores + dos picos do chat.

Critérios de um corte viral:
- Reação forte do streamer (susto, grito, gargalhada, raiva) **coincidindo** com explosão do chat, quando houver chat.
- Fail, jogada absurda, plot twist, resenha engraçada, interação com chat/convidado.
- Entende-se sozinho: começa 1-3 s antes do gancho (com o mínimo de contexto) e termina logo após o clímax. Shorts de 20-60 s (máx. ~65 s). Nunca cortar no meio da frase.
- Evite: loading/espera, publi, música tocando ao fundo (direitos autorais), trechos de conteúdo sexual explícito ou ofensas pesadas.
- Se o chat for constante sem picos (live muito movimentada), pese mais a voz e a história do momento.
- Quantidade: o que o usuário pedir (padrão 5; se pedir "os mais virais", 3).

## 4. Renderizar

1. Crie o job `<job>-cortes` (ou use o próprio job se foi uma parte só) com:
   - `meta.json` copiado de uma parte, com `"offset": 0`.
   - `transcricao.json` juntando as transcrições de todas as partes (ordenado por `start`).
   - `cortes.json`:
     ```json
     {"formato": "vertical", "layout": "auto", "legenda": false, "titulo_no_video": false,
      "vocabulario": "<canal>, <jogo>, <nomes e gírias que aparecem>",
      "cortes": [{"id": "01", "inicio": "6:25:21", "fim": "6:26:26", "titulo": "A DESPEDIDA DE SOLTEIRO DELE"}]}
     ```
     `titulo` é um nome curto do corte (não aparece no vídeo: a caixa amarela de título fica desligada, a não ser que o usuário peça `titulo_no_video: true`; aí: até ~35 caracteres, CAIXA ALTA, sem emoji). `formato`: vertical, horizontal ou ambos.
     Deixe sempre `"legenda": false` aqui: a legenda entra depois, no passo 4b (legenda inteligente revisada). `vocabulario` ajuda a transcrição a acertar nomes. Live em outra língua: `"idioma": "en"` etc.
     Um corte pode forçar o próprio layout: `"layout": "facecam", "facecam": {"x":0,"y":0,"w":512,"h":288}` (pixels do vídeo original), `"layout": "retrato"` ou `"layout": "blur"`.
     **Automático em cada corte (não precisa pedir):**
     - **Chamada de vídeo** (Ome.tv, Discord, FaceTime na tela): em cena de câmera (retrato), o robô acha a janela da chamada e usa o layout `chamada` — **quem está do outro lado em cima, o streamer embaixo**. Log: `CHAMADA na janela {...}`; conferência em `chamada_<id>.jpg`. Errou a janela: force `"layout": "chamada", "janela": {"x","y","w","h"}` (pixels do original) ou desligue com `"chamada": false`.
     - **Câmera vazia**: trecho em que o streamer sai da câmera e ninguém fala é cortado sozinho (só tira pausa ≥1,2 s; nunca corta fala; não corta se sobrariam <8 s ou se a câmera ficou vazia em >60% do corte). Padrão ligado em `retrato`/`chamada`; no layout de jogo+webcam só com `"cortar_vazio": true` (desligue com `false`). Log: `CAMERA_VAZIA removido 22.6-41.9s (19.2s)`.
     - Cada corte publica `corte_<id>.cena.json` (layout, janela, linha de presença `#`=na câmera `.`=fora, trechos removidos).
   - `publicacao.md`: por corte, título para YouTube/TikTok (≤70 caracteres, com gancho; emoji pode), descrição de 1-2 linhas com **crédito obrigatório** ("Créditos: <canal> – <link do canal>"), hashtags e ideia de thumbnail.
   - `postagem.json`: os textos no formato que o robô posta (detalhes em `POSTAR.md`). **Sempre crie**, mesmo sem a postagem configurada:
     ```json
     {"cortes": [{"id": "01",
       "titulo": "Faltou 2 SEGUNDOS pro recorde… e o yuri22 surtou 😱",
       "legenda": "Faltou 2 segundos pro recorde 😱 Quem aguentaria? Créditos: yuri22 (kick.com/yuri22) #yuri22 #gta #kick #cortes #shorts",
       "descricao": "Na maratona pra zerar todos os GTAs, o desafio escapa por um triz.\nCréditos: yuri22 – https://kick.com/yuri22"}]}
     ```
     - `titulo` → título do YouTube Shorts (≤70, gancho forte).
     - `legenda` → legenda do TikTok/Reels: 1 frase de gancho ou pergunta que puxe comentário + crédito curto + 3-5 hashtags (canal, jogo, plataforma, `#cortes`, `#shorts`). Até ~150 caracteres antes das hashtags.
     - `descricao` → descrição do YouTube com o crédito completo (as hashtags da legenda são acrescentadas sozinhas).
     - Opcionais (não pergunte ao usuário; use o padrão): `horarios` (padrão `["12:00","15:00","18:00","21:00"]`, 1 corte por horário, a partir do próximo), `fuso` (padrão `America/Sao_Paulo`), `redes` (padrão: todas conectadas). Ordene os cortes do mais forte para o mais fraco — o mais forte sai primeiro.
2. Commit, `git pull --rebase`, push, dispare `renderizar.yml` (3-6 min).
3. Baixe a Release e **confira 1-2 quadros de cada corte** (ffmpeg → png → Read) e os `facecam_<id>.jpg` (caixa amarela = webcam achada):
   - A caixa pegou só a webcam? Não ficou nenhuma frase por cima do vídeo (a menos que o usuário tenha pedido)?
   - Se errou a webcam: refaça só aquele corte com `facecam` manual (copie a caixa de outro corte da mesma live, que costuma ser igual) usando `inputs[so]=<id>`.
   - Cena de chamada: os dois rostos aparecem (o de quem está na chamada em cima)? Se o streamer saiu da câmera, o trecho vazio sumiu?
   - **Re-renderizou um corte que já tinha legenda?** Apague antes o `corte_<id>_limpo.mp4` antigo da Release (`gh api $R/releases/tags/<job> --jq '.assets[]|"\(.id) \(.name)"'` → `gh api -X DELETE $R/releases/assets/<id>`), senão o `legendar.yml` legenda o vídeo velho. E refaça a revisão da legenda: se a câmera vazia tirou um trecho, os tempos mudaram.
4. Faça o passo 4b (legenda inteligente) antes de entregar — é o padrão; pule só se o usuário pedir corte sem legenda. Entregue com `SendUserFile` (os .mp4 + `publicacao.md`) e uma tabela curta: corte, tempo na live, por que é viral — e siga direto para o passo 5, sem perguntar.

## 4b. Legenda inteligente (padrão em todo corte)

Siga **`LEGENDAR.md`**. Resumo:
1. `legendar.yml` com `etapa=rascunho` e `job=<job>` (todos os cortes da Release; `so` para só alguns). ~2-4 min por corte.
2. `git pull`; para cada corte leia `jobs/<job>/legendas/<id>.bruto.json` e olhe `<id>.posicoes.jpg`. Escreva `<id>.editado.json` (corrigir palavras, juntar as vozes em 2 pelo sentido da conversa, quebrar frases em pontos naturais, tirar o que não dá para entender, conferir posição), rode `legenda_inteligente.py montar` e faça commit + push dos `<id>.json`.
3. `legendar.yml` com `etapa=gravar` e `job=<job>`. O legendado substitui `corte_<id>_vertical.mp4` na Release (o original fica como `corte_<id>_limpo.mp4`), então o passo 5 já posta com legenda.
4. Confira 2-3 quadros de cada corte antes de entregar.
Não pergunte estilo, tamanho, cor nem posição: está tudo decidido (Montserrat Black compacta, branco + amarelo na palavra dita, embaixo, subindo só quando cobriria o personagem). **Vídeo avulso** (não é corte de live): mesmo fluxo, passando `video=<link>` no rascunho e um `job` novo (`AAAA-MM-DD-assunto`).

## 5. Postar sozinho (automático, sem perguntar)

Assim que os cortes passarem na conferência do passo 4 (e do 4b; só os aprovados; um corte com webcam errada só vai depois de refeito), siga **`POSTAR.md`**: confirme o `postagem.json`, dispare `postar.yml` e acrescente na tabela de entrega quando cada corte sai. Não pergunte redes, horários nem legendas.

## Avisos ao usuário (uma vez, sem sermão)
- Cortar live de terceiros sem permissão pode gerar strike/desmonetização; muitos streamers liberam cortes com crédito.
- Em repositório público, as transcrições e os cortes ficam visíveis; os vídeos completos das lives não ficam salvos.
- A legenda vem da transcrição automática revisada por você, que lê o texto mas não escuta o áudio: em gritaria, uma palavra ou outra pode escapar.
- Com a postagem automática ligada, os cortes vão ao ar sem revisão dele; se quiser ver antes, basta dizer "não posta ainda" e o passo 5 fica para quando ele mandar.
