# Alerta de orçamento, para um recurso esquecido ligado não aparecer só na
# fatura. O gasto esperado é de US$ 5 a 10 por mês, na moeda da assinatura.
resource "azurerm_consumption_budget_subscription" "cno" {
  name            = "orcamento-cno"
  subscription_id = "/subscriptions/${var.assinatura}"
  amount          = 100
  time_grain      = "Monthly"

  time_period {
    start_date = "2026-09-01T00:00:00Z"
  }

  # Metade do teto já gasta.
  notification {
    enabled        = true
    threshold      = 50
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = [var.email_alerta]
  }

  # Previsão de estourar o mês.
  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Forecasted"
    contact_emails = [var.email_alerta]
  }
}
