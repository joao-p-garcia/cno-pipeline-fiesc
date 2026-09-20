# Alerta de orçamento.
#
# Não é pelo risco deste desenho — o job cabe na cota gratuita e o dashboard
# fica em zero réplicas. É porque descobrir um recurso esquecido pela fatura é
# uma lição cara de aprender duas vezes, e um ambiente de demonstração é
# exatamente o tipo de coisa que se esquece ligada.
#
# O `amount` está na moeda de cobrança da assinatura. O gasto esperado é de
# US$ 5–10/mês, quase todo em ACR Basic, então qualquer leitura de 100 já
# significa que alguma coisa não está como se pensa.
resource "azurerm_consumption_budget_subscription" "cno" {
  name            = "orcamento-cno"
  subscription_id = "/subscriptions/${var.assinatura}"
  amount          = 100
  time_grain      = "Monthly"

  time_period {
    start_date = "2026-09-01T00:00:00Z"
  }

  # Metade do teto, já gasto: alguma coisa mudou de patamar.
  notification {
    enabled        = true
    threshold      = 50
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = [var.email_alerta]
  }

  # E a previsão de estourar o mês, que avisa antes de acontecer em vez de
  # depois — que é o ponto de um alerta.
  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Forecasted"
    contact_emails = [var.email_alerta]
  }
}
