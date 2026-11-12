# Postar cortes no TikTok e no Instagram (grátis, pelo Buffer)

Este é o passo a passo da postagem automática. Vale tanto logo depois de fazer cortes (skill de cortes, passo 5) quanto quando o usuário pede só para postar cortes que já existem.

**Princípio:** o usuário quer automação total. Não pergunte redes, horários nem legendas — use os padrões abaixo. Só fale com ele para a configuração única, para avisos e para entregar o resultado.

## Como funciona
- Tudo passa pela **API grátis do Buffer**: TikTok e Instagram (como **Reel**, também compartilhado no feed).
- Cada corte ganha o próximo **horário de pico livre**: 12h, 15h, 18h e 21h de Brasília. As duas redes saem no mesmo horário. Cortes de lives diferentes nunca caem no mesmo horário.
- O Buffer grátis aceita só **10 posts esperando por rede**. O que passar disso fica na **reserva** (`estado/fila/<job>.json`), e o workflow `postar.yml` roda sozinho **de hora em hora** e manda o próximo para o Buffer quando abre vaga. Se o horário de um corte passar enquanto ele espera, ele pega o próximo horário livre.
- O Buffer só aceita o vídeo por **link público direto**, então o workflow mantém no branch `midia` só os vídeos que o Buffer ainda vai buscar (o repositório já é público; os vídeos saem de lá depois de postados).
- Rodar de novo para o mesmo job **não duplica** nada.

## Configuração única (o usuário faz, uma vez)
Se `postar.yml` responder `AVISO_SEM_CHAVE`, passe estes passos, curtos e sem jargão:
1. Criar conta grátis em https://buffer.com.
2. Conectar o **TikTok** e o **Instagram** no Buffer. O Instagram precisa ser conta **profissional** (Configurações → Tipo de conta → Mudar para conta profissional). O plano grátis tem 3 canais; esses dois ocupam 2.
3. Em https://publish.buffer.com/settings/api, criar a chave da API.
4. No GitHub, salvar a chave como segredo `BUFFER_API_KEY` em `https://github.com/<usuario>/<repositorio>/settings/secrets/actions/new`.

**Nunca** peça a chave no chat nem a coloque em arquivo do repositório.

Depois de configurado, rode o **teste**: dispare `postar.yml` com `inputs[job]=<um job com postagem.json>` e `inputs[teste]=sim`. O 1º corte vira **rascunho** no Buffer nas duas redes (nada é publicado; o usuário pode apagar os rascunhos). Só diga que está tudo ligado depois de ver `TESTE_OK tiktok` e `TESTE_OK instagram`.

## Postar um job
1. **Textos:** crie (ou confira) `jobs/<job>/postagem.json`, ordenando os cortes do mais forte para o mais fraco (o mais forte sai primeiro):
   ```json
   {"cortes": [{"id": "01",
     "titulo": "Faltou 2 SEGUNDOS pro recorde… e o yuri22 surtou 😱",
     "legenda": "Faltou 2 segundos pro recorde 😱 Você aguentaria? Créditos: yuri22 (kick.com/yuri22) #yuri22 #gta #kick #cortes",
     "descricao": "Na maratona pra zerar todos os GTAs, o desafio escapa por um triz.\nCréditos: yuri22 – https://kick.com/yuri22"}]}
   ```
   - `legenda` é o que vai embaixo do vídeo nas duas redes: uma frase de gancho ou pergunta que puxe comentário, crédito curto do streamer e 3 a 5 hashtags (canal, jogo, plataforma, `#cortes`). Até uns 150 caracteres antes das hashtags. **O crédito é obrigatório.**
   - `titulo` e `descricao` ficam guardados para o `publicacao.md` (não são usados pelo TikTok nem pelo Instagram).
   - Opcionais, só se o usuário pedir: `horarios`, `fuso` (padrão `America/Sao_Paulo`), `redes` (padrão: as duas).
   - Os vídeos precisam estar na Release do job como `corte_<id>_vertical.mp4` (é o que o `renderizar.yml` gera).
2. Faça commit e push do `postagem.json`.
3. Dispare: `gh api -X POST repos/<usuario>/<repositorio>/actions/workflows/postar.yml/dispatches -f ref=main -f 'inputs[job]=<job>'` (e `-f 'inputs[so]=01,03'` se for só parte).
4. Espere terminar (1 a 3 minutos) e leia o log: `grep -E "AGENDADO|RESERVA|TESTE_OK|ERRO|AVISO|BUFFER_CAMPOS|tiktok=|instagram="`.

## Ler o resultado
- `AGENDADO <id> <dia hora> tiktok,instagram` → na entrega, mostre uma tabela curta: corte, quando sai.
- `RESERVA <id> <dia hora> ...` → a fila do Buffer está cheia; o corte entra sozinho quando abrir vaga (pode mudar de horário). Diga isso em uma linha.
- `AVISO_SEM_CHAVE` → falta a configuração única (acima). Ofereça **uma vez por conversa**, em uma linha.
- `AVISO_SEM_REDE tiktok|instagram` → aquela rede não está conectada no Buffer; peça para conectar e redispare (não duplica).
- `ERRO_POSTAGEM ... chave do Buffer recusada` → chave errada ou apagada; peça para criar outra e atualizar o segredo.
- `ERRO_POSTAGEM` com `BUFFER_CAMPOS` → o Buffer recusou o post. A linha `BUFFER_CAMPOS` lista os campos que a API aceita hoje; ajuste `Buffer.postar` em `scripts/postar.py` se mudaram, faça push e redispare. Um item que falha 3 vezes fica com status `erro`.
- Para responder "o que já saiu / o que está agendado": leia `estado/fila/*.json` (`agendado` com horário, `reserva`, `erro`).

## Avisos (uma vez, sem sermão)
- Os cortes vão ao ar sem o usuário revisar. Se ele disser "não posta ainda", pule a postagem até ele mandar.
- Perfil de cortes de um streamer funciona melhor com a permissão dele, e sempre com crédito.
