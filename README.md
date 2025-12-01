# 🧾 MailingCoreSQL

O **MailingCoreSQL** é o repositório que concentra as **consultas SQL principais e mais importantes** utilizadas para geração dos mailings de cobrança.

Ele funciona como o **"coração SQL"** do processo de cobrança, servindo de base para o sistema que monta e envia os mailings de forma automatizada.

---

## 🎯 Objetivo

Centralizar, padronizar e documentar as **consultas essenciais** que:

- Alimentam os mailings de cobrança
- Selecionam os clientes corretos em cada cenário
- Garantem consistência de regras de negócio entre diferentes rotinas
- Facilitam manutenção e auditoria das regras de cobrança

---

## 🗂 Estrutura do Repositório

> A organização pode variar conforme o crescimento do projeto, mas a ideia geral é:

```text
MailingCoreSQL/
│
├── consultas/
│   ├── mailing_principal.sql
│   ├── mailing_inadimplentes.sql
│   ├── mailing_negociacao.sql
│   ├── mailing_reforco_cobranca.sql
│   └── ...
│
├── exemplos/
│   ├── exemplo_parametros.sql
│   └── exemplo_filtros.sql
│
└── README.md
