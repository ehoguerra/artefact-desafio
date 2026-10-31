# Direito de arrependimento

Pedido verificado com e-mail do cliente e política de devolução aplicada às datas reais do pedido (entregue há 3 dias, dentro do prazo de 7 dias).

*Modelo: `claude-opus-5-5` · Data/hora simulada da loja: 2026-02-20T15:00:00-04:00 · Avaliação do juiz: média 4.2/5*

**Cliente:** Me arrependi da minha compra, posso devolver meu pedido?

**Lia:** Pode sim, dependendo do prazo! 😊 Pelo direito de arrependimento (compras online), dá pra devolver assim:

- **Prazo:** até 7 dias corridos depois de receber o produto, sem precisar justificar
- **Estado do produto:** na embalagem original, sem sinais de uso, com todos os acessórios e manuais
- **Frete da devolução:** fica por conta da loja
- **Reembolso:** na mesma forma de pagamento que você usou, em até 10 dias úteis

Atenção: instrumentos personalizados ou com ajuste sob encomenda (setup, regulagem especial) e itens de liquidação com aviso de "venda final" não podem ser devolvidos.

Se você me passar o **número do pedido** e o **e-mail ou telefone do cadastro**, eu consulto o pedido e te digo se ele ainda está no prazo.

<details><summary>Ferramentas consultadas</summary>

- `consultar_politica` `{"topico": "trocas_e_devolucoes"}`

</details>

**Cliente:** É o pedido 7, meu email é leticia.rocha@jmail.com

**Lia:** Oi, Letícia! Achei seu pedido 😊

- **Pedido 7:** Shelby SU-21S Soprano Sunburst (ukulele), R$ 159,90 no cartão de crédito em 3x
- **Status:** entregue
- **Previsão de entrega:** 17/02/2026

**Seu pedido ainda está dentro do prazo de arrependimento.** Hoje é 20/02, então já se passaram 3 dias desde a previsão de entrega, e o limite é de 7 dias corridos depois do recebimento.

O sistema não registra o dia exato em que o ukulele chegou, então usei a previsão de entrega para calcular. Se ele chegou em outro dia, o prazo muda. De qualquer forma, é melhor fazer o pedido de devolução logo.

Para a devolução ser aceita, o ukulele precisa estar na embalagem original, sem sinais de uso e com todos os acessórios e manuais. O frete da devolução fica por conta da loja. O reembolso volta para o seu cartão em até 10 dias úteis.

Para fazer o pedido de devolução, fale com a nossa equipe:
📞 Telefone/WhatsApp: (67) 3341-4444
✉️ E-mail: contato@emporiodamusica.com.br

A loja está aberta agora, até as 18h. Posso ajudar em mais alguma coisa?

<details><summary>Ferramentas consultadas</summary>

- `consultar_pedido` `{"numero_pedido": 7, "email_ou_telefone": "leticia.rocha@jmail.com"}`
- `status_loja` `{}`

</details>

---

Gerado automaticamente por `pytest tests/e2e` em 2026-10-31T13:19:09-03:00.
