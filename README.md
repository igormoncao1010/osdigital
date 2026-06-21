# OS Digital

Sistema local de ordens de serviço com numeração sequencial permanente, cadastro de cliente e aparelho, acompanhamento de status e impressão.

## Como executar

Dê dois cliques em `iniciar.bat`. Ele inicia o servidor e abre o endereço correto automaticamente. Se preferir o terminal, execute:

```powershell
.\iniciar.bat
```

Depois acesse `http://127.0.0.1:8000` no navegador.

Os dados ficam no arquivo `ordens.db`, criado automaticamente. Faça backup desse arquivo regularmente. A numeração usa a sequência interna `AUTOINCREMENT` do SQLite e não é reaproveitada.

Cada OS também gera automaticamente dois arquivos na pasta `pdfs`: o documento completo em duas vias e uma ficha interna para o técnico.

Na versão publicada na Vercel, as ordens são armazenadas no navegador do dispositivo e os PDFs são gerados para download. Para compartilhar os mesmos dados entre vários computadores será necessário conectar um banco de dados online.
