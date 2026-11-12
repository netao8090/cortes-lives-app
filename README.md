# cortes-lives-app

Robô de cortes de live: você manda **só o link** (Twitch, YouTube ou Kick) e saem cortes verticais prontos, com título e legenda palavra por palavra.

## Como funciona
1. **Analisar** (`.github/workflows/analisar.yml`) – baixa só o **áudio** da live, transcreve com Whisper (rodando aqui mesmo, sem API paga) e marca picos de volume. Salva tudo em `jobs/<nome>/`.
2. **Escolher** – o Claude lê a transcrição e escreve `jobs/<nome>/cortes.json` com os melhores momentos.
3. **Renderizar** (`.github/workflows/renderizar.yml`) – baixa **só os trechos escolhidos** em até 1080p, monta o vídeo vertical 9:16 com legenda e publica tudo numa **Release** com o nome do trabalho.

4. **Postar** (`.github/workflows/postar.yml`) – posta ou agenda cada corte no TikTok, Instagram Reels e YouTube Shorts (as contas conectadas no [Upload-Post](https://upload-post.com)), com a legenda, título e hashtags que o Claude escreve em `jobs/<nome>/postagem.json`. Um corte por horário de pico (12h, 15h, 18h, 21h de Brasília). Rodar de novo não posta duas vezes.

Os cortes ficam em **Releases** (lado direito da página do repositório).

### Ligar a postagem automática (uma vez só)
1. Crie conta no [Upload-Post](https://upload-post.com) e conecte TikTok, Instagram e YouTube.
2. Copie a chave da API no painel deles.
3. Aqui no GitHub: **Settings → Secrets and variables → Actions → New repository secret**, nome `UPLOADPOST_API_KEY`, cole a chave.

No plano grátis do Upload-Post não tem TikTok nem agendamento (o robô posta nas outras redes e espaça sozinho); o plano pago libera os dois.

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
