# OS Digital

Sistema local de ordens de serviço com numeração sequencial permanente, cadastro de cliente e aparelho, acompanhamento de status e impressão.

## Como executar

Clique com o botão direito em `iniciar.ps1` e escolha **Executar com PowerShell**. Se preferir o terminal, execute:

```powershell
.\iniciar.ps1
```

Depois acesse `http://127.0.0.1:8000` no navegador.

Os dados ficam no arquivo `ordens.db`, criado automaticamente. Faça backup desse arquivo regularmente. A numeração usa a sequência interna `AUTOINCREMENT` do SQLite e não é reaproveitada.
