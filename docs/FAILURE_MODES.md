# Modos de falha (escritos antes do código)

Regra do projeto: o teste principal é E2E. Onde um componente precisa ser pensado isoladamente, primeiro
listamos como ele pode falhar; o código é escrito para tornar cada item impossível ou tratado. A coluna
**Verificação** indica qual cenário E2E (`tests/e2e/`) cobre o item.

## Dados (CSVs)

| # | Falha | Tratamento | Verificação |
|---|---|---|---|
| D1 | Produto com `stock_quantity = 0` mas `status = active` (ex.: Giannini GF-3D, id 96) oferecido como disponível | disponibilidade derivada: `active` **e** estoque > 0 → senão `esgotado` | catálogo violões ≤ R$1000 |
| D2 | Produto `discontinued` (ids 113, 136) ou `coming_soon` (130) vendido como normal | rótulos `descontinuado` / `em_breve`; `detalhar_produto` sugere alternativas | produto indisponível |
| D3 | Promoção inativa aplicada (ex.: Takamine GD20 tem "Oferta Especial 12%" com `is_active = 0`) | só `is_active = 1` entra no preço | preço Takamine GD20 |
| D4 | Mais de uma promoção para o mesmo produto (ids 93, 96, 99) | considera apenas ativas; havendo várias, a de maior desconto | revisão de código |
| D5 | Desconto PIX somado à promoção | PIX 5% só sem promoção ativa (manual §6.2) | promoção ativa |
| D6 | Erro aritmético do LLM em descontos/parcelas | todo cálculo em `Decimal` no código; tool devolve valores já formatados | preço Takamine GD20 / promoção ativa |
| D7 | Busca por nome falha por acento/caixa/abreviação ("takamine gd 20", "violao") | normalização (NFKD sem acento, minúsculas, tokens) e casamento por tokens | preço Takamine GD20 |
| D8 | Categoria pedida pelo cliente não bate com o nome da tabela ("violão" vs "Violões", "ukulele" vs "Ukuleles") | `category_by_name` tolerante (singular/plural, acentos) | catálogo violões |
| D9 | Busca ampla devolve o catálogo inteiro e estoura contexto | limite de 15 resultados, ordenados por preço, com total informado | catálogo violões |
| D10 | `total_brl` do pedido diverge da soma dos itens (ex.: pedido 20) | total do pedido é histórico e é o informado; não recalculado | revisão de código |
| D11 | CSV com campo vazio (tracking, entrega estimada, notes) quebra o parser | campos opcionais viram `None` | pedido confirmado sem rastreio |

## Pedidos e privacidade (LGPD — manual §9)

| # | Falha | Tratamento | Verificação |
|---|---|---|---|
| P1 | Qualquer pessoa consulta pedido alheio só com o número | exige nº do pedido **e** e-mail ou telefone do cliente daquele pedido | pedido com contato errado |
| P2 | Mensagem de erro revela se o pedido existe ou de quem é | erro único e genérico para "não existe" e "não confere" | pedido com contato errado |
| P3 | Clientes homônimos / e-mail duplicado (ids 11 e 43 compartilham `bruno.martins@jmail.com`) | verificação compara com o cliente vinculado ao pedido, nunca busca cliente por nome | revisão de código |
| P4 | Telefone em formato diferente ("67998123456" vs "(67) 99812-3456") | comparação só por dígitos; e-mail sem caixa/espaços | arrependimento de compra |

## Políticas (PDF)

| # | Falha | Tratamento | Verificação |
|---|---|---|---|
| K1 | Tabela de horários extraída embaralhada do PDF | versão curada em `knowledge/` reconstrói a tabela (Seg–Sex 9–18, Sáb 9–13, Dom fechado) | endereço/horário |
| K2 | Contradições no manual (telefone 3341-4444 vs WhatsApp 3321-4500; e-mail com "ó"; parcela mínima R$100 vs regras por faixa) | resolvidas na versão curada com nota explicando a decisão; documentado no README | endereço/horário |
| K3 | Agente responde política "de memória" e alucina | tool `consultar_politica` + instrução de sempre consultar | arrependimento de compra |
| K4 | Direito de arrependimento aplicado sem olhar datas | agente consulta pedido (data, status) e política; prazo de 7 dias após recebimento | arrependimento de compra |

## Agente / LLM

| # | Falha | Tratamento | Verificação |
|---|---|---|---|
| A1 | Responde preço/estoque sem consultar o sistema | prompt + tools com descrição de "quando usar"; E2E exige a tool no trace | todos os cenários de dados |
| A2 | Pergunta fora do escopo (receita, capital da França) respondida | prompt: recusa gentil e volta ao tema | fora do escopo |
| A3 | Pedido de acessórios (cordas, amplificador) tratado como produto da loja | prompt + política `escopo_de_atendimento`: só instrumentos, redirecionar | fora do escopo |
| A4 | Loop infinito de tools | `max_tool_rounds`; ao estourar, resposta pedindo para reformular | revisão de código |
| A5 | Erro de API / rede / rate limit derruba a CLI com stacktrace | erros tipados do SDK viram mensagem amigável; sessão não é corrompida | revisão de código |
| A6 | `stop_reason = refusal` sem texto | resposta padrão educada | revisão de código |
| A7 | Histórico corrompido ao salvar no meio da escrita | escrita atômica (arquivo temporário + `replace`) | memória entre sessões |
| A8 | Tool lança exceção e mata o turno | `ToolExecutor.execute` nunca lança; devolve `is_error=True` | pedido com contato errado |
| A9 | Argumentos inválidos (pedido "abc", tópico inexistente) | `strict: true` nos schemas + validação no executor | revisão de código |
| A10 | "Estamos abertos agora?" respondido sem saber a hora | tool `status_loja` com fuso de Campo Grande; relógio congelável (`EMPORIO_NOW`) | endereço/horário |
| A11 | Não-determinismo do LLM torna o E2E frágil | asserções sobre o trace de tools (determinístico) e sobre fatos normalizados (números, nomes), não sobre redação | suíte inteira |
| A12 | Saída com acentos quebrada no console do Windows | `stdout/stdin` reconfigurados para UTF-8 | suíte inteira |

## Ampliação da suíte (segunda rodada)

Itens que a primeira suíte não exercitava. Cada um vira um cenário E2E com o mesmo nome.

| # | Falha | Tratamento | Verificação |
|---|---|---|---|
| E1 | Parcelamento prometido além do permitido (ex.: "12x" num item de R$ 599,90, cuja parcela ficaria < R$ 100) | `parcelamento` calculado no código e devolvido pela tool; prompt manda usar o valor da tool | parcelamento_por_faixa |
| E2 | Frete grátis prometido fora da região metropolitana de Campo Grande | política `frete_e_entrega` consultada; frete grátis só na região metropolitana | frete_para_outra_cidade |
| E3 | "Estão abertos?" respondido como aberto num domingo | `status_loja` com relógio congelado num domingo | loja_fechada_no_domingo |
| E4 | Defeito tratado como troca simples fora dos prazos de 30 dias e de 90 dias de garantia legal | pedido + política de garantia e de trocas; encaminhar à garantia do fabricante | defeito_fora_do_prazo_de_troca |
| E5 | Pedido enviado sem informar o código de rastreio; telefone em formato livre recusado | `consultar_pedido` aceita telefone por dígitos; resposta traz o código | rastreio_de_pedido_enviado |
| E6 | Pedido cancelado apresentado como em andamento | status e motivo do cancelamento informados | pedido_cancelado_com_motivo |
| E7 | Produto descontinuado vendido como disponível | rótulo `descontinuado` + alternativas | produto_descontinuado |
| E8 | Produto inexistente no catálogo recebe preço inventado | tool retorna "não encontrado"; agente não inventa preço | produto_inexistente_sem_alucinacao |
| E9 | Promoção expirada citada pelo cliente é honrada | só promoção ativa vale; informa preço atual sem desconto | promocao_expirada_nao_e_honrada |
| E10 | Prompt injection extrai dados de outro cliente | verificação obrigatória do contato; recusa sem vazar dados | injecao_de_prompt_dados_de_cliente |
| E11 | Pedido de exclusão de dados (LGPD) ignorado ou respondido sem base | política `privacidade` consultada; canais de solicitação informados | exclusao_de_dados_lgpd |
| J1 | Respostas corretas nos fatos, mas com tom robótico, frio ou formal demais (manual §7.1) | LLM como juiz avalia cada conversa com rubrica de tom, cordialidade, clareza e fidelidade às tools | todos os cenários (juiz) |
| J2 | Resposta afirma algo que as tools não devolveram (alucinação sutil) | juiz recebe as saídas das tools e pontua fidelidade | todos os cenários (juiz) |
| J3 | Juiz instável ou leniente demais torna a nota sem valor | juiz com modelo diferente do agente, saída estruturada, justificativa obrigatória por critério e limiar explícito | relatório E2E |
