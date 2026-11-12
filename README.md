# cortes-lives-app

Robô de cortes de live: você manda **só o link** (Twitch, YouTube ou Kick) e saem cortes verticais prontos, com título e legenda palavra por palavra.

## Como funciona
1. **Analisar** (`.github/workflows/analisar.yml`) – baixa só o **áudio** da live, transcreve com Whisper (rodando aqui mesmo, sem API paga) e marca picos de volume. Salva tudo em `jobs/<nome>/`.
2. **Escolher** – o Claude lê a transcrição e escreve `jobs/<nome>/cortes.json` com os melhores momentos.
3. **Renderizar** (`.github/workflows/renderizar.yml`) – baixa **só os trechos escolhidos** em até 1080p, monta o vídeo vertical 9:16 com legenda e publica tudo numa **Release** com o nome do trabalho.

4. **Postar** (`.github/workflows/postar.yml`) – agenda cada corte no **Instagram Reels** (API oficial da Meta) e no **TikTok** (API grátis do Buffer), com a legenda e as hashtags que o Claude escreve em `jobs/<nome>/postagem.json`. Um corte por horário de pico (12h, 15h, 18h, 21h de Brasília); o Instagram sai pela fila que o workflow roda de hora em hora. Tudo grátis, e rodar de novo não posta duas vezes.

Os cortes ficam em **Releases** (lado direito da página do repositório).

### Ligar a postagem automática (uma vez só, grátis)
Segredos em **Settings → Secrets and variables → Actions → New repository secret**:

| Segredo | De onde vem |
|---|---|
| `IG_TOKEN` | developers.facebook.com → seu app → Instagram → *Configuração da API com login do Instagram* → Gerar token (conta do Instagram profissional) |
| `BUFFER_API_KEY` | buffer.com (grátis) com o TikTok conectado → publish.buffer.com/settings/api |
| `GH_PAT` (opcional) | token *fine-grained* do GitHub só deste repositório com **Secrets: Read and write** — renova o `IG_TOKEN` sozinho (ele dura 60 dias) |

Depois rode **3 - Postar cortes** com `teste = sim` para conferir as contas sem publicar nada.

## Usar pelo Claude
Mande o link e diga "faz os cortes". Exemplos:
- `https://www.twitch.tv/nomedocanal` → pega a live atual (o que já foi transmitido) ou a última
- `https://www.twitch.tv/videos/123456789`
- `https://kick.com/nomedocanal` → pega o último VOD (a live atual só aparece quando termina)
- `https://www.youtube.com/watch?v=...` (depois que a live terminar; o YouTube costuma bloquear)

## Usar na mão
Aba **Actions** → "1 - Analisar live" → **Run workflow** → link + nome. Depois crie `jobs/<nome>/cortes.json` e rode "2 - Renderizar cortes".

## Limites
- Twitch: funciona durante e depois da live (enquanto o VOD existir e for público).
- YouTube/Kick: mande depois que a live virar VOD. O YouTube às vezes bloqueia downloads vindos de servidores.
- Cada análise roda até ~5,5 h no GitHub; lives maiores são analisadas em partes.

Respeite os direitos dos streamers: dê crédito e prefira canais que liberam cortes.
