# Sistema de Cotação de Frete com Groq

Este script implementa um sistema automatizado para monitorar, extrair e processar informações de e-mails de cotação de frete, calculando custos de transporte usando APIs externas.

**Linguagem**: Python

## Bibliotecas Principais
- imaplib: Para conexão e manipulação de e-mails via IMAP.
- email: Para parsing de mensagens de e-mail.
- dotenv: Para carregar variáveis de ambiente.
- logging: Para registro de logs.
- groq: Para processamento de linguagem natural.
- requests: Para fazer requisições HTTP à API de cálculo de frete.

## Funcionalidades Principais
1. Conexão IMAP segura para monitoramento de e-mails.
2. Extração e decodificação de conteúdo de e-mails.
3. Processamento de linguagem natural com a API Groq para extrair informações relevantes.
4. Cálculo de frete utilizando a API Qualp.
5. Formatação e apresentação dos resultados de cotação.

## Técnicas Aplicadas
- Programação assíncrona para monitoramento contínuo.
- Parsing e processamento de texto.
- Integração com APIs externas (Groq e Qualp).
- Manipulação de dados JSON.
- Tratamento de erros e logging extensivo.
