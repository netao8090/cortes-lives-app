# Legendas gravadas no vídeo (estilo TikTok/Reels)

Legenda animada palavra por palavra, gravada no próprio vídeo, feita com o **pycaps** (github.com/francozanardi/pycaps, MIT, versão fixa e revisada em `scripts/instalar_legendas.sh`). Roda de graça no GitHub Actions do usuário.

O que sai: fonte grossa em maiúsculas com contorno preto, a palavra falada em destaque, cada palavra entrando com "pop", palavras-chave em outra cor com animação mais forte, emoji grudado nas palavras escolhidas e, opcionalmente, um "pop" sonoro nos destaques. A transcrição é feita **no próprio trecho** com faster-whisper (modelo `turbo`), com o tempo exato de cada palavra.

**Princípio:** não pergunte estilo, cor nem posição. Use `viral` e escolha você mesmo os destaques e emojis (é o papel que a IA paga do pycaps faria).

## Estilos
| Estilo | Visual | Bom para |
|---|---|---|
| `viral` (padrão) | branco com contorno preto, palavra falada amarela, destaque verde | cortes de live, humor, reação |
| `explosivo` | amarelo com brilho de fogo, palavras entrando de lado | hype, momentos épicos |
| `gamer` | branco com brilho ciano, destaque rosa neon | games, setups com luz neon |
| presets do pycaps | `hype`, `explosive`, `word-focus`, `line-focus`, `vibrant`, `retro-gaming`, `minimalist`, `neo-minimal`, `classic`, `default`, `fast` | quando o usuário pedir um desses pelo nome |

## Destaques e emojis (sua parte)
Leia o que é falado no trecho e escolha:
- **Destaques:** 3 a 6 palavras que carregam a piada ou a emoção ("recorde", "preso", "sorvete", "Deus"). Palavras soltas, como aparecem na fala. Evite palavras muito comuns ("mano", "aí", "é"), que aparecem toda hora e poluem a legenda.
- **Emojis:** 2 a 4 palavras com um emoji que combine (`{"recorde":"🏆","preso":"🚔","sorvete":"🍦"}`). No máximo um emoji a cada ~10 segundos.
- **Vocabulário:** nomes que o Whisper costuma errar (nome do streamer, do jogo, gírias), separados por vírgula.

## A. Nos cortes de live (skill de cortes)
No `cortes.json`, acrescente:
```json
{"estilo_legenda": "viral", "som_legenda": true, "vocabulario": "yuri22, GTA, Vice City",
 "cortes": [{"id": "01", "...": "...", "destaques": ["recorde", "segundos"], "emojis": {"recorde": "🏆"}}]}
```
- Opcionais: `idioma` (padrão `pt`; use `en`, `es`... se a live for em outra língua), `modelo_legenda` (padrão `turbo`).
- O `renderizar.yml` instala o pycaps sozinho quando vê `estilo_legenda`. A legenda fica na altura certa de cada layout (no meio do jogo, sem cobrir o rosto nem o título).
- Se a legenda animada falhar num corte, o log mostra `AVISO legenda animada falhou` e aquele corte sai com a legenda simples antiga: nunca se perde o corte. Leia o erro (`ERRO_LEGENDA`) e tente consertar.
- Custa uns 2 minutos a mais por corte no GitHub.

## B. Qualquer vídeo avulso
1. Coloque o vídeo onde o robô alcança:
   - link público (YouTube, TikTok, Kick, Twitch, link direto de .mp4): use direto;
   - arquivo que o usuário anexou: suba para uma Release, ex.: `gh release create entrada-<data> <arquivo> -R <usuario>/<repositorio> --title "Entrada"` (ou `gh release upload` se ela já existir) e use `release:entrada-<data>/<nome do arquivo>`.
2. Dispare `legendar.yml`:
   ```
   gh api -X POST repos/<usuario>/<repositorio>/actions/workflows/legendar.yml/dispatches -f ref=main \
     -f 'inputs[video]=<link ou release:tag/arquivo>' -f 'inputs[nome]=legendas-<data>-<assunto>' \
     -f 'inputs[estilo]=viral' -f 'inputs[destaques]=palavra1,palavra2' \
     -f 'inputs[emojis]={"palavra1":"😱"}' -f 'inputs[opcoes]={"som":true,"prompt":"nomes, gírias"}'
   ```
   Opções em `opcoes`: `posicao` (0 = topo, 1 = base; padrão 0.66), `som`, `lang` (padrão `pt`, ou `auto`), `modelo`, `prompt`, `preview` (`"3,9"` = só esse trecho, rápido, para testar um estilo).
   Para escolher destaques sem ter a transcrição, rode antes com `preview` curto ou deixe sem destaques na primeira vez.
3. Espere terminar (uns 3 a 6 minutos para 1 minuto de vídeo) e baixe da Release `<nome>` o arquivo `<nome original>_legendado.mp4`. Use a API REST para baixar (`gh api repos/.../releases/tags/<nome>` → id do asset → `gh api -H "Accept: application/octet-stream" repos/.../releases/assets/<id>`).

## Conferir antes de entregar
Extraia uns quadros (`ffmpeg -i video.mp4 -vf "fps=1/3,scale=360:-2,tile=6x2" -frames:v 1 folha.jpg`) e olhe:
- a legenda não corta nas bordas nem cobre o rosto do streamer ou o título;
- acentos certos (Ã, Ê, Ç);
- os destaques e emojis aparecem nas palavras certas.
Se algo estiver errado, ajuste (`posicao`, destaques) e rode de novo. Entregue com `SendUserFile`.

## Mensagens no log
- `LEGENDA_OK <arquivo>`: deu certo.
- `ERRO_LEGENDA estilo desconhecido`: nome de estilo errado (veja a tabela).
- `ERRO_LEGENDA pycaps falhou`: leia o erro acima dessa linha. Se faltar biblioteca do sistema (`.so`), acrescente no `apt-get` de `scripts/instalar_legendas.sh`.
