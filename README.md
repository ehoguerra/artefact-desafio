# Empório da Música — Agente de Atendimento

Protótipo de um agente de atendimento por mensagens de texto para a **Empório da Música**, loja de
instrumentos musicais em Campo Grande/MS. A assistente virtual, **Lia**, responde clientes em português
com o tom da loja ("informal mas profissional"). Ela consulta catálogo, promoções e pedidos em tempo real,
aplica o manual de políticas e recusa assuntos fora do escopo.

## Exemplos de interação

Conversas reais com o agente, geradas pela suíte de testes ponta a ponta:

| Exemplo | O que demonstra |
|---|---|
| [Violões até R$ 1.000](examples/01-catalogo-violoes.md) | busca no catálogo com filtro de categoria e preço; esgotados e descontinuados ficam de fora |
| [Endereço e horário](examples/02-endereco-e-horario.md) | política da loja combinada com o relógio: "estão abertos agora?" |
| [Preço do Takamine GD20](examples/03-preco-takamine-gd20.md) | preço, PIX e parcelamento calculados no código; a promoção inativa de 12% é ignorada |
| [Direito de arrependimento](examples/04-arrependimento-de-compra.md) | **não trivial:** verifica a identidade, consulta o pedido e aplica a política às datas reais |
| [Fora do escopo](examples/05-fora-do-escopo.md) | acessórios redirecionados com educação e assunto alheio recusado |

As transcrições dos 20 cenários, com as notas do juiz, estão no
[relatório E2E](reports/e2e/latest/report.md).

## Como rodar

Pré-requisitos: Python ≥ 3.11 e [uv](https://docs.astral.sh/uv/). Também é preciso uma chave da API da
Anthropic.

```bash
uv sync                                  # cria o .venv e instala as dependências
cp .env.example .env                     # e preencha ANTHROPIC_API_KEY
uv run emporio-agent chat                # conversa efêmera
uv run emporio-agent chat --session ana  # histórico persistido em .sessions/ana.json
```

Dentro do chat, `/nova` reinicia a conversa e `/sair` encerra. `--trace arquivo.jsonl` registra cada
chamada de ferramenta, o que ajuda na depuração.

| Variável | Padrão | Uso |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | credencial (obrigatória) |
| `EMPORIO_MODEL` | `claude-opus-5-5` | modelo |
| `EMPORIO_EFFORT` | `low` | profundidade de raciocínio (`low` … `max`) |
| `EMPORIO_SESSIONS_DIR` | `.sessions` | onde ficam os históricos |
| `EMPORIO_NOW` | relógio real | congela o "agora" da loja (ISO 8601 com fuso); usado nos testes |
| `EMPORIO_JUDGE` | ligado | `off` desliga o juiz LLM da suíte E2E (execuções mais baratas) |
| `EMPORIO_JUDGE_MODEL` | `claude-sonnet-5-5` | modelo do juiz, diferente do modelo do agente |

### Testes ponta a ponta

```bash
uv run pytest tests/e2e -v
```

A suíte executa a **CLI real**, como subprocesso, contra o **LLM real**. Ela gera um artefato verificável a
cada execução:

- `reports/e2e/latest/report.md` e `report.json`: cada cenário, cada verificação com o detalhe
  (passou/falhou), as notas do juiz com justificativa, as ferramentas chamadas com argumentos, o
  modelo e o relógio simulado.
- `reports/e2e/latest/transcripts/*.md`: a conversa completa de cada cenário.
- `examples/*.md`: as conversas de exemplo, regeneradas pela própria suíte.

Uma execução completa leva cerca de 5 minutos. Ela faz chamadas pagas à API: as 20 conversas do agente e
uma avaliação do juiz por cenário. Com `EMPORIO_JUDGE=off`, a execução fica mais barata. Sem
`ANTHROPIC_API_KEY`, a suíte é pulada com uma mensagem explicando o motivo.

## Arquitetura

```
 cliente ─► cli.py ─► agent.py ◄────── Anthropic Messages API (Claude)
                         │  loop de tool use
                         ▼
                      tools.py ─► store/catalog.py   CSVs tratados e tipados
                                ─► store/pricing.py   promoção, PIX, parcelamento (Decimal)
                                ─► store/policies.py  knowledge/politicas_da_loja.md por tópico
                                ─► store/hours.py     aberto/fechado no fuso de Campo Grande
 history.py (sessões JSON)   tracing.py (JSONL)
```

As ferramentas expostas ao modelo:

| Ferramenta | Quando o modelo usa |
|---|---|
| `buscar_produtos` | busca por termo, categoria e faixa de preço ("violões até R$ 1000") |
| `detalhar_produto` | preço, estoque, ficha técnica e alternativas de um item específico |
| `consultar_pedido` | status, itens e rastreio. Exige nº do pedido **e** e-mail ou telefone do titular |
| `consultar_politica` | trocas, garantia, pagamento, frete, horário, contato, privacidade, escopo |
| `status_loja` | data e hora atuais em Campo Grande; aberto ou fechado; próxima abertura |

O contrato entre os módulos está em [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Os modos de falha
foram mapeados antes do código e estão em [`docs/FAILURE_MODES.md`](docs/FAILURE_MODES.md).

## Decisões técnicas

**Abordagem: function calling, sem framework.** As perguntas da loja se dividem em dois tipos.
- Perguntas de **dados estruturados** (preço, estoque, pedido) pedem filtro exato, e não similaridade
  semântica: "violões até R$ 1000" é um `WHERE`.
- Perguntas de **política**, respondidas por um documento curto.

Por isso cada necessidade virou uma ferramenta tipada, e o modelo decide qual chamar. Usei o SDK oficial
da Anthropic com um loop manual curto, sem LangChain ou similares. Assim cada mensagem e cada chamada de
ferramenta ficam visíveis (trace JSONL) e não há camadas de abstração a depurar. Descartei um agente de SQL:
ele dá ao modelo liberdade demais sobre dados de clientes (LGPD) e torna os cálculos de preço não
determinísticos.

**A aritmética fica no código, não no LLM.** Preço com promoção, desconto PIX e parcelamento máximo sem
juros são calculados em `Decimal` e devolvidos já formatados ("R$ 2.089,05"). O manual diz que informação
de preço errada "pode configurar propaganda enganosa", então esses números não podem ficar a cargo do
modelo. As regras aplicadas pelo código:
- o desconto PIX de 5% não se soma à promoção (manual §6.2);
- só promoções com `is_active = 1` entram no preço;
- o parcelamento segue as faixas de parcela mínima da §3.1.

Pelo mesmo motivo, a consulta de pedido já devolve quantos dias se passaram desde a compra e desde a
previsão de entrega, para que os prazos de troca e arrependimento não dependam de contas de data feitas pelo
modelo.

**Retrieval das políticas: seções por tópico, sem embeddings.** O manual tem 8 páginas (≈3 mil tokens). A
extração automática do PDF embaralha as tabelas: a de horários fica ilegível. Por isso fiz uma versão curada
em markdown (`knowledge/politicas_da_loja.md`), com uma seção por tópico, e a ferramenta
`consultar_politica(topico)` devolve a seção pedida. Isso é determinístico, auditável e sem risco de o chunk
errado ser recuperado. Com centenas de documentos, eu trocaria por busca híbrida (BM25 + embeddings), mantendo
a mesma interface da ferramenta.

**Modelo: Claude Opus 5.5 com `effort: low`.** Atendimento é uma tarefa de conversa e roteamento de
ferramentas. O esforço baixo dá respostas curtas e rápidas, mantendo o modelo mais capaz para decidir quando
consultar dados e quando consultar políticas. O modelo e o esforço são configuráveis por variável de
ambiente. Também configurei:
- *prompt caching*: o system prompt e as ferramentas são estáticos, e o horário vem da ferramenta
  `status_loja`, não do prompt, para não invalidar o cache;
- *fallback* de recusa no servidor.

**Estratégia de prompt.** O system prompt define a persona e o tom pela §7.1 do manual. Ele traz as regras
de quando usar cada ferramenta, por exemplo "nunca informar preço, estoque ou prazo sem consultar o sistema
neste turno". Traz também o escopo: só instrumentos, com acessórios redirecionados e assuntos alheios
recusados. As descrições das ferramentas reforçam o *quando usar*, porque são elas que guiam o roteamento.

**Privacidade (LGPD).** `consultar_pedido` só devolve dados se o e-mail ou o telefone conferir com o cliente
**daquele** pedido. O telefone é comparado só pelos dígitos, com ou sem DDD. O erro é idêntico para "pedido
não existe" e "contato não confere", então não dá para descobrir quais números de pedido existem. Também não
há busca de cliente por nome: há homônimos e um e-mail duplicado na base.

**Interface: CLI.** O foco do desafio é o agente. A CLI lê stdin linha a linha, então funciona no terminal e
via *pipe*, o que permite testá-la ponta a ponta sem nenhum mock.

**Persistência: JSON por sessão.** Com `--session`, o histórico é salvo após cada turno, com escrita atômica.
O cliente pode voltar depois e continuar a conversa. O histórico é *append-only*, como a API exige para os
blocos de raciocínio do modelo. Se a API falhar no meio de um turno, o turno é desfeito e o histórico
continua válido.

**Testes: só E2E, em duas camadas.** Não há testes unitários. Vinte cenários conversam com a CLI real.
Eles cobrem catálogo, preços, pedidos, políticas, escopo, privacidade e injeção de prompt.

1. **Verificações objetivas** sobre **fatos** e **o trace de ferramentas**, e não sobre a redação. Por
   exemplo: a ferramenta certa foi chamada? O preço 2.199 aparece? A promoção inativa de 12% ficou de fora?
   Nenhum dado do cliente vazou na tentativa de injeção?
2. **LLM como juiz.** Um modelo diferente do agente (`claude-sonnet-5-5`, com saída estruturada) lê cada
   conversa, inclusive as saídas das ferramentas, e dá notas de 1 a 5 com justificativa. Os critérios são
   **tom** (manual §7.1), **cordialidade**, **clareza** e **fidelidade** às ferramentas. Os mínimos são 3
   nos três primeiros critérios e 4 em fidelidade.

O juiz pegou o que as verificações objetivas não pegam: alucinações sutis com os fatos certos. Por exemplo,
descrever um produto que a loja não tem, inventar um "e-mail de confirmação" que a política não menciona,
deduzir preços além dos resultados exibidos, ou prometer que a equipe "vai investigar". Cada achado virou
uma correção no prompt ou na ferramenta. A faixa de preço completa, por exemplo, passou a vir na busca.

Os limiares nunca foram baixados, mas a rubrica do juiz foi calibrada três vezes, depois de ler as
transcrições em que ele penalizava algo legítimo. Cada calibração esclareceu que não é invenção:
- citar tipos de instrumento como exemplo;
- encaminhar o cliente aos canais oficiais da equipe;
- descrever o que as próprias ferramentas da Lia sabem fazer.

Para separar a calibração de um afrouxamento, toda nota de fidelidade baixa foi checada contra a frase
exata citada pelo juiz.

O relógio da loja é congelado por cenário (`EMPORIO_NOW`), o que torna reproduzíveis os casos que dependem
de data, como o de arrependimento de compra.

### Tratamento dos dados

| Achado | Decisão |
|---|---|
| Produto ativo com estoque 0 (Giannini GF-3D) | disponibilidade derivada de status **e** estoque: aparece como `esgotado` e o agente sugere alternativas |
| Produtos `discontinued` (com estoque > 0) e `coming_soon` | o status prevalece sobre o estoque e o produto não é oferecido como disponível |
| Várias promoções para o mesmo produto, a maioria inativa | só `is_active = 1` vale; se houver mais de uma ativa, vale o maior desconto |
| Takamine GD20 com promoção de 12% **inativa** | ignorada, como manda a §7.3 ("nunca prometer desconto que não está vigente") |
| Total do pedido diferente da soma dos itens (pedidos 3 e 20) | o total do pedido é histórico e é o informado |
| Campos vazios em pedidos (rastreio, previsão de entrega) | viram ausentes, sem texto vazio |
| Nome de produto e de categoria com acento, caixa ou abreviação diferentes ("gd 20", "violao") | normalização (remoção de acentos e casamento por tokens) |
| "Cordas" pode ser a categoria Cordas Orquestrais ou o acessório | o prompt trata "cordas" sozinho como acessório, que a loja não vende |

### Suposições sobre o manual de políticas

O manual tem contradições. Cada resolução abaixo está anotada como "Nota de curadoria" no arquivo curado.

- **Horário:** a tabela do PDF está desalinhada. Adotei Seg–Sex 09h–18h, Sáb 09h–13h, Dom e feriados
  fechado, a única leitura consistente.
- **Telefone:** o cabeçalho e a tabela "Telefone / WhatsApp" dizem (67) 3341-4444. A §7 cita (67) 3321-4500.
  Adotei o primeiro, que aparece duas vezes e com rótulo explícito. Na vida real, isso seria confirmado com a
  gerência.
- **E-mail:** a grafia "empóriodamusica" é um erro de digitação. Adotei `contato@emporiodamusica.com.br`.
- **Parcelamento:** a tabela fala em parcela mínima de R$ 100, mas a §3.1 detalha faixas (até 3x sem mínimo;
  4–6x com parcela ≥ R$ 80; 7–12x com parcela ≥ R$ 100). Prevalece a regra mais específica. Compras abaixo
  de R$ 50 não são parceladas.
- **Data de recebimento:** a base não tem data de entrega efetiva. Para o prazo de arrependimento (7 dias
  após o recebimento), o agente usa a previsão de entrega como referência e avisa o cliente disso.

## Limitações conhecidas e próximos passos

- **Feriados** não são modelados no horário da loja. O próximo passo seria um calendário de feriados de
  Campo Grande/MS.
- **Frete:** o agente explica as regras, mas não calcula o valor por CEP, porque não há tabela de frete nos
  dados.
- **Reclamações** são acolhidas e encaminhadas para o telefone ou e-mail, mas não são registradas. Com mais
  tempo, eu criaria uma ferramenta `registrar_reclamacao` com protocolo e SLA de 24h úteis.
- **Avaliação:** a suíte cobre 20 cenários escritos à mão. Com respostas não determinísticas, um cenário
  raramente oscila entre execuções. O próximo passo seria rodar cada cenário N vezes e reportar a taxa de
  aprovação, além de ampliar o conjunto com perguntas reais de clientes vindas do WhatsApp.
- **Canal:** o manual cita o WhatsApp como canal principal. O `Agent` não depende da CLI, então plugar um
  webhook (FastAPI + WhatsApp Business API) seria uma nova camada de interface.
- **Escala do catálogo:** para milhares de produtos, a busca em memória passaria a SQLite/Postgres com
  índice de texto, mantendo a mesma ferramenta.

## Uso de assistentes de código

O projeto foi construído com o **Claude Code** (Claude Opus 5.5), num fluxo de **orquestração de
agentes**. Eu defini as regras de trabalho e acompanhei as entregas: os testes são só E2E, com um artefato
verificável; os modos de falha vêm antes do código; os agentes trabalham em paralelo; o código é limpo. A
execução foi do Claude Code, como agente orquestrador e subagentes:

1. **Reconhecimento e contrato.** O orquestrador leu o enunciado, os CSVs e o PDF, mapeou as
   inconsistências dos dados e escreveu o contrato entre os módulos (`docs/ARCHITECTURE.md`). Os modos de
   falha (`docs/FAILURE_MODES.md`) foram escritos **antes** de qualquer código.
2. **Implementação em paralelo.** Três subagentes trabalharam ao mesmo tempo, em arquivos disjuntos e
   presos ao contrato:
   - (a) camada de dados, precificação, políticas curadas e ferramentas;
   - (b) loop do agente, persona, persistência e CLI;
   - (c) suíte E2E com relatório.

   Cada um recebeu os valores esperados para conferir (por exemplo, "Takamine GD20 → R$ 2.199,00; PIX
   R$ 2.089,05; 12x de R$ 183,25").
3. **Integração e revisão.** As partes foram integradas, o prompt e o loop foram revisados, e um quarto
   agente fez uma revisão de correção e de código limpo.
4. **Validação.** A suíte E2E roda a CLI real contra o modelo real e gera os exemplos de conversa deste
   repositório.
5. **Ampliação da suíte.** A pedido meu, a suíte cresceu de 9 para 20 cenários e ganhou o juiz LLM. Os
   novos modos de falha (E1–E11, J1–J3) foram escritos primeiro. Em seguida, dois subagentes em paralelo
   escreveram os cenários e o juiz. Cada falha foi diagnosticada pela transcrição antes de qualquer ajuste.
   Quando o agente errava, o prompt ou a ferramenta foi corrigido. Quando a checagem testava redação em vez
   de fato, a checagem foi corrigida.

As decisões técnicas estão documentadas acima com a justificativa de cada uma, para poderem ser
auditadas: o roteamento por ferramentas, a verificação de pedido para LGPD, a curadoria das contradições
do manual e a aritmética no código. O histórico de commits reflete essas etapas.
