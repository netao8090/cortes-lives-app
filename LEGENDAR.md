# Legenda inteligente gravada no vídeo

Legenda que parece feita por um editor, não "cara de CapCut":
- **Visual aprovado:** Montserrat Black em caixa alta, tamanho compacto ("C"), **só branco**, com o **amarelo passando na palavra no momento em que é dita**. Sem emojis, sem cores extras, sem pulinho em cada palavra (o bloco só entra e sai suave).
- **Tempo certo:** transcrição palavra por palavra (faster-whisper `turbo`, filtro de voz, limpeza de alucinação). O bloco entra junto com a primeira palavra e sai logo depois da última; nas pausas não fica nada parado na tela.
- **Quem fala:** separação de vozes (sherpa-onnx: pyannote 3.0 + TitaNet). A fala de outra pessoa aparece em **itálico** e com **travessão (—) quando muda quem fala**.
- **Posição que não cobre o que importa:** um detector (YOLOX) olha 3 quadros de cada bloco; se a legenda embaixo for cobrir personagem/veículo, ela sobe para o meio ou logo abaixo do título. Só muda quando precisa e não fica pulando. A webcam é ignorada.
- **Revisão do Claude antes de gravar:** corrigir palavras, juntar as vozes certas, quebrar as frases em pontos naturais e conferir as posições.

Tudo roda de graça no GitHub Actions (`legendar.yml`), com o pycaps (github.com/francozanardi/pycaps, MIT, versão fixa em `scripts/instalar_legendas.sh` — **nunca** o pacote `pycaps` do PyPI, que é outro projeto).

**Princípio:** não pergunte estilo, cor, tamanho nem posição — está tudo decidido. Só fale com o usuário para entregar.

## Fluxo (cortes de live ou vídeo avulso)

### 1. Ter os vídeos limpos numa Release
- **Cortes de live:** o `renderizar.yml` já publica `corte_<id>_vertical.mp4` limpo (sem frase por cima) e `corte_<id>_vertical.layout.json` (onde começa a área do jogo) na Release `<job>`.
- **Vídeo avulso:** passe `video` no passo 2 (link do YouTube/TikTok/Kick, link direto de .mp4, ou `release:<tag>/<arquivo>`; arquivo que o usuário anexou → suba antes com `gh release create entrada-<data> <arquivo>` ou `gh release upload`). Ele vira `corte_01_vertical.mp4` na Release `<job>` (escolha um nome `AAAA-MM-DD-assunto`).

### 2. Rascunho
```
gh api -X POST $R/actions/workflows/legendar.yml/dispatches -f ref=main \
  -f 'inputs[etapa]=rascunho' -f 'inputs[job]=<job>' [-f 'inputs[so]=01,03'] [-f 'inputs[video]=<link>'] \
  -f 'inputs[opcoes]={"prompt":"<canal>, <jogo>, nomes e gírias que aparecem"}'
```
- Do `cortes.json` do job vêm `vocabulario` (vira o `prompt`) e `idioma` (padrão `pt`).
- Vídeo avulso que não é corte do robô: passe `"topo_jogo"` (onde começa a área que pode receber legenda; 0.1 se o vídeo inteiro é conteúdo).
- Leva ~2-4 min por corte. Ao terminar: `git pull` e leia, para cada corte, `jobs/<job>/legendas/<id>.bruto.json` e **olhe** `<id>.posicoes.jpg` (caixa verde = pessoa/veículo achado; faixa vermelha = legenda embaixo; faixa amarela = posição escolhida).

### 3. Revisão (a sua parte)
O `bruto.json` traz `palavras` (com tempo, confiança `p` e falante `f`) e `blocos` sugeridos (`f`, `texto`, `de`, `ate`, `pos`). Escreva `jobs/<job>/legendas/<id>.editado.json`:
```json
{"blocos": [{"f": 1, "texto": "E agora, cadê o caminhão", "pos": 0.46},
            {"f": 1, "texto": "de sorvete, mano?", "pos": 0.46},
            {"f": 2, "texto": "Eu tenho vendido 20 já, mano!", "pos": 0.46}]}
```
Regras:
- **Mesma ordem da fala.** Pode corrigir palavras, juntar/separar blocos, trocar falante e apagar um bloco (deixe fora). O texto é realinhado às palavras originais e herda o tempo exato de cada uma.
- **Falantes:** a separação automática costuma achar vozes demais em gritaria. Junte pelo **sentido da conversa** (quem explica, quem zoa, quem reage) em 2 falantes, no máximo 3. Falante 1 = quem mais fala (texto normal); os outros saem em itálico com travessão na troca.
- **Correções:** só o que é claramente erro de transcrição (gramática que não fecha, palavra parecida que faz sentido no contexto, palavras de baixa confiança). Nomes que você não conhece: mantenha como as duas transcrições ouviram. **Frase que não dá para entender: tire** — melhor sem legenda do que legenda errada. Não censure palavrão.
- **Blocos:** 1-2 linhas, até ~24 caracteres por bloco (frases maiores: divida em pontos naturais — vírgula, fim de ideia; nunca termine bloco em "de", "o", "que"). Junte trechos muito rápidos para ninguém ficar menos de ~0,5 s na tela.
- **Posição (`pos`):** confira na folha. Use a sugerida; troque só se a folha mostrar erro (0.76 = embaixo, 0.60 = meio, 0.46 = alto). Mantenha a mesma posição em sequência (não deixe pular sem motivo).

Depois monte e salve:
```
python3 scripts/legenda_inteligente.py montar jobs/<job>/legendas/<id>.bruto.json \
  jobs/<job>/legendas/<id>.editado.json jobs/<job>/legendas/<id>.json
git add jobs/<job>/legendas && git commit -m "legenda revisada: <job>" && git pull --rebase && git push
```
(O `montar` imprime os blocos com tempo de tela; se algum ficou com menos de 0,5 s, junte e rode de novo.)

### 4. Gravar
```
gh api -X POST $R/actions/workflows/legendar.yml/dispatches -f ref=main -f 'inputs[etapa]=gravar' -f 'inputs[job]=<job>'
```
Para cada `<id>.json`, guarda o vídeo sem legenda como `corte_<id>_limpo.mp4` (uma vez só, para poder refazer) e publica o legendado por cima de `corte_<id>_vertical.mp4` — é esse que o `postar.yml` posta. ~2-3 min por corte (mais uma passada para cada posição diferente).

### 5. Conferir e entregar
Baixe o `corte_<id>_vertical.mp4` e olhe uns quadros (`ffmpeg -ss <t> -i v.mp4 -frames:v 1 q.png`): legenda branca com a palavra em amarelo, sem cortar nas bordas, sem cobrir personagem nem rosto, acentos certos, segunda pessoa em itálico. Entregue com `SendUserFile` (vídeo avulso: versão em 720p se for grande).

## Atalho sem revisão
`inputs[etapa]=direto` transcreve e grava de uma vez (sem separar vozes, sem posição automática). Use só quando ninguém vai revisar (ex.: execução automática sem o Claude).

## Mensagens no log
- `TRANSCRITO N palavras, K falante(s), B blocos` e `POSICOES x de B bloco(s) fora de baixo`: rascunho pronto.
- `AVISO_SEM_DIARIZACAO`: modelos de voz não baixaram; tudo como um falante (revise os falantes à mão).
- `LEGENDADO <id>`: gravado e publicado.
- `ERRO_LEGENDA ...`: leia a linha de cima. Falta de biblioteca do sistema (`.so`) → acrescente no `apt-get` de `scripts/instalar_legendas.sh`. Corte que falhou continua na Release sem legenda (nunca se perde).

## Outros estilos (só se o usuário pedir)
`--estilo viral` (Komika, amarelo, verde nos destaques, emojis), `explosivo`, `gamer`, ou um preset do pycaps (`hype`, `explosive`, `word-focus`, `line-focus`, `vibrant`, `retro-gaming`, `minimalist`, `neo-minimal`, `classic`, `default`, `fast`). Fontes extras prontas em `fontes_legenda/` (Montserrat Black, Anton, Bangers; licença OFL).
