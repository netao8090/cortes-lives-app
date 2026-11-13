# cortes-lives-app

Robô de cortes de live: você manda **só o link** (Twitch, YouTube ou Kick) e saem cortes verticais prontos, com título e legenda palavra por palavra.

## Como funciona
1. **Analisar** (`.github/workflows/analisar.yml`) – baixa só o **áudio** da live, transcreve com Whisper (rodando aqui mesmo, sem API paga) e marca picos de volume. Salva tudo em `jobs/<nome>/`.
2. **Escolher** – o Claude lê a transcrição e escreve `jobs/<nome>/cortes.json` com os melhores momentos.
3. **Renderizar** (`.github/workflows/renderizar.yml`) – baixa **só os trechos escolhidos** em até 1080p, monta o vídeo vertical 9:16 com legenda e publica tudo numa **Release** com o nome do trabalho.

- **Legenda inteligente** (`.github/workflows/legendar.yml`) – legenda gravada no vídeo como de editor: palavra por palavra, só branco com o amarelo passando na palavra dita, quem fala separado (itálico e travessão na troca), posição que sobe sozinha quando cobriria o personagem, e revisão do Claude antes de gravar. Serve para os cortes e para qualquer vídeo avulso. Detalhes em `LEGENDAR.md`.
4. **Postar** (`.github/workflows/postar.yml`) – agenda cada corte no **TikTok** e no **Instagram Reels** pela API grátis do Buffer, com a legenda e as hashtags que o Claude escreve em `jobs/<nome>/postagem.json`. Um corte por horário de pico (12h, 15h, 18h, 21h de Brasília). O que passar do limite de 10 da fila grátis do Buffer fica numa reserva e entra sozinho quando vagar. Rodar de novo não posta duas vezes. Detalhes em `POSTAR.md`.

Os cortes ficam em **Releases** (lado direito da página do repositório).

### Ligar a postagem automática (uma vez só, grátis)
1. Crie conta grátis no [Buffer](https://buffer.com) e conecte o TikTok e o Instagram (conta profissional).
2. Crie a chave em [publish.buffer.com/settings/api](https://publish.buffer.com/settings/api).
3. Aqui no GitHub: **Settings → Secrets and variables → Actions → New repository secret**, nome `BUFFER_API_KEY`, cole a chave.
4. Rode **3 - Postar cortes** com `teste = sim`: o 1º corte vira rascunho no Buffer, nada é publicado.

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
