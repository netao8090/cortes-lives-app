---
name: cortes-de-live
description: Faz cortes virais de lives da Kick, Twitch ou YouTube só com o link do canal ou do VOD — inclusive de lives que ainda estão no ar, usando o chat como termômetro de euforia — e posta sozinho no Instagram Reels e no TikTok com legenda e hashtags (de graça), espalhando nos horários de pico. O trabalho pesado roda de graça no GitHub Actions do próprio usuário. Use quando pedirem cortes, clipes ou shorts de uma live, ou para postar cortes.
---

# Cortes de live (Kick / Twitch / YouTube)

O usuário manda **só um link**. Quem baixa, transcreve e renderiza é um "robô" no **GitHub Actions do próprio usuário** (o ambiente do Claude não acessa Kick/Twitch/YouTube). Quem **escolhe os momentos é o Claude**, lendo a transcrição, os picos de voz e os picos do chat. O chat é só termômetro: **nunca aparece no vídeo**.

Resultado: cortes verticais 9:16 em 1080p com a webcam do streamer detectada sozinha (câmera em cima + jogo embaixo, ou retrato quando a câmera está em tela cheia), título no vídeo, legenda palavra por palavra e um `publicacao.md` com título, descrição com crédito e hashtags. Se a postagem automática estiver ligada, os cortes já saem **agendados** no Instagram Reels (API oficial da Meta) e no TikTok (API grátis do Buffer), sem o usuário escolher nada.

Fale com o usuário em linguagem simples, sem jargão técnico. Ele não precisa saber de workflows, ramos ou API.

---

## 0. Primeira vez: montar o robô no GitHub do usuário

Pergunte o nome do repositório se ele ainda não disse (formato `usuario/repositorio`). Se não tiver um: peça para criar um repositório **público** vazio no GitHub (público = GitHub Actions grátis e sem limite de minutos).

1. `add_repo` com `access: "push"`. Se recusar o push, peça para instalar o app do Claude no GitHub com acesso a esse repositório (https://github.com/apps/claude/installations/select_target) ou reconectar o GitHub nos conectores do claude.ai.
2. Clone em `/home/claude/<repositorio>`.
3. Se o repositório ainda não tem `scripts/renderizar.py`: copie **todo o conteúdo da pasta `robo/` desta skill** para a raiz do repositório (inclui `.github/workflows/`, `scripts/`, `fonts/`, `assets/`, `.gitignore`), faça commit e push.
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
| `postar.yml` | agenda os cortes: TikTok no Buffer (com link do vídeo no branch `midia`) e Instagram numa fila que o próprio workflow roda de hora em hora; `teste=sim` confere as contas sem publicar; rodar de novo não duplica | `job`, `so`, `teste` |

### Postagem automática (configuração única, feita pelo usuário, tudo grátis)
Só uma vez. Se ainda não foi feita, passe estes passos curtos, um por vez, sem jargão. Nunca peça token/chave no chat nem coloque em arquivo: eles vão só nos segredos do GitHub (`https://github.com/<usuario>/<repositorio>/settings/secrets/actions/new`).

**Instagram (API oficial da Meta):**
1. A conta do Instagram precisa ser **profissional** (Configurações → Tipo de conta → Mudar para conta profissional; de preferência "Empresa").
2. Em https://developers.facebook.com/apps → **Criar app** → caso de uso "Gerenciar mensagens e conteúdo no Instagram" (ou tipo *Business* + produto Instagram).
3. No app: Instagram → **Configuração da API com login do Instagram** → *Gerar tokens de acesso* → **Adicionar conta** (entra com o Instagram) → **Gerar token** → copiar. (O app pode ficar em modo de desenvolvimento: é para a própria conta, não precisa de análise da Meta.)
4. Segredo `IG_TOKEN` com esse token.
5. Opcional, para nunca vencer: o token dura 60 dias. Crie em https://github.com/settings/personal-access-tokens/new um token *fine-grained* só deste repositório com **Secrets: Read and write** e salve como segredo `GH_PAT`. Com ele o robô renova o `IG_TOKEN` sozinho toda semana; sem ele, o log avisa (`AVISO_TOKEN_IG`) 10 dias antes de vencer.

**TikTok (via Buffer, grátis — a API do próprio TikTok só posta como privado):**
1. Criar conta grátis em https://buffer.com e conectar o TikTok (o plano grátis tem 3 canais e fila de 10 posts por canal).
2. Em https://publish.buffer.com/settings/api criar a chave da API.
3. Segredo `BUFFER_API_KEY` com a chave.

Depois de configurar, dispare `postar.yml` com `teste=sim` num job que já tenha `postagem.json`: `TESTE_OK instagram` (o vídeo subiu e foi aceito, nada publicado) e `TESTE_OK tiktok` (vira um rascunho no Buffer, que pode apagar). Só então diga que está tudo ligado.

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
     {"formato": "vertical", "layout": "auto", "legenda": true,
      "cortes": [{"id": "01", "inicio": "6:25:21", "fim": "6:26:26", "titulo": "A DESPEDIDA DE SOLTEIRO DELE"}]}
     ```
     `titulo` aparece no vídeo: até ~35 caracteres, CAIXA ALTA, sem emoji. `formato`: vertical, horizontal ou ambos.
     Um corte pode forçar o próprio layout: `"layout": "facecam", "facecam": {"x":0,"y":0,"w":512,"h":288}` (pixels do vídeo original), `"layout": "retrato"` ou `"layout": "blur"`.
   - `publicacao.md`: por corte, título para YouTube/TikTok (≤70 caracteres, com gancho; emoji pode), descrição de 1-2 linhas com **crédito obrigatório** ("Créditos: <canal> – <link do canal>"), hashtags e ideia de thumbnail.
   - `postagem.json`: os mesmos textos no formato que o robô posta. **Sempre crie**, mesmo sem a postagem configurada:
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
   - A caixa pegou só a webcam? O título não cobre o rosto? A legenda está limpa?
   - Se errou a webcam: refaça só aquele corte com `facecam` manual (copie a caixa de outro corte da mesma live, que costuma ser igual) usando `inputs[so]=<id>`.
4. Entregue com `SendUserFile` (os .mp4 + `publicacao.md`) e uma tabela curta: corte, tempo na live, por que é viral — e siga direto para o passo 5, sem perguntar.

## 5. Postar sozinho (automático, sem perguntar)

Assim que os cortes passarem na conferência do passo 4 (só os aprovados; um corte com webcam errada só vai depois de refeito), dispare `postar.yml` com `inputs[job]=<job>` (e `inputs[so]` se for só parte). O usuário pediu automação total: **não pergunte redes, horários ou legendas** — use os padrões. Cada corte ganha o próximo horário de pico livre (12h, 15h, 18h, 21h de Brasília), sem encavalar com cortes de lives anteriores; o TikTok fica agendado no Buffer e o Instagram entra na fila (`estado/fila/<job>.json`), que o workflow roda sozinho de hora em hora (o GitHub pode atrasar uns minutos).

Leia o log (`grep -E "AGENDADO|POSTADO|TESTE_OK|ERRO|AVISO|BUFFER_CAMPOS|instagram=|tiktok="`):
- `AGENDADO <id> <dia hora> instagram,tiktok` → na entrega, acrescente a coluna "sai em" na tabela.
- `AVISO_SEM_CHAVE` → postagem ainda não configurada: entregue normalmente e, **uma vez por conversa**, ofereça em uma linha ligar a postagem grátis (seção 0).
- `AVISO_SEM_TIKTOK` → falta conectar o TikTok no Buffer; depois é só redisparar (não duplica).
- `AVISO_TOKEN_IG` → o token do Instagram está para vencer ou não foi renovado: peça para gerar outro no painel da Meta e atualizar o segredo `IG_TOKEN` (ou criar o `GH_PAT` para não acontecer de novo).
- `ERRO_POSTAGEM ... instagram` com "token" → token inválido/vencido (mesma solução acima). Com "processamento" → a Meta recusou o vídeo; confira formato (9:16, 5-90 s).
- `ERRO_POSTAGEM ... tiktok` / `BUFFER_CAMPOS` → o Buffer recusou; a linha `BUFFER_CAMPOS` lista os campos que a API aceita hoje — ajuste `buffer_postar` em `scripts/postar.py` se mudaram.
- O que já saiu fica em `estado/fila/<job>.json` (status `postado` com link, `agendado`, `na_fila`, `erro`, `perdido`). Um Reel mais de 20 h atrasado não é postado (fica `perdido`) para não sair fora de hora.

## Avisos ao usuário (uma vez, sem sermão)
- Cortar live de terceiros sem permissão pode gerar strike/desmonetização; muitos streamers liberam cortes com crédito.
- Em repositório público, as transcrições e os cortes ficam visíveis; os vídeos completos das lives não ficam salvos.
- A legenda vem da transcrição automática e erra em trechos de gritaria; dá para revisar antes de renderizar.
- Com a postagem automática ligada, os cortes vão ao ar sem revisão dele; se quiser ver antes, basta dizer "não posta ainda" e o passo 5 fica para quando ele mandar.
