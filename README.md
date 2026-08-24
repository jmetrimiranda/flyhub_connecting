# Documentação — FlightHub 2 → OpenCV

Site MkDocs documentando o pipeline de ingestão de vídeo ao vivo de drones DJI para visão computacional.

## Publicar no GitHub Pages

**1. Copie os arquivos para o repositório**

```
seu-repo/
├── mkdocs.yml
├── requirements-docs.txt
├── docs/
└── .github/workflows/docs.yml
```

**2. Ative o GitHub Pages**

No repositório: **Settings → Pages → Build and deployment → Source: GitHub Actions**

Esse passo é obrigatório. Sem ele o workflow falha na etapa de deploy.

**3. Faça o push**

```bash
git add mkdocs.yml requirements-docs.txt docs .github
git commit -m "docs: pipeline FlightHub 2 para OpenCV"
git push
```

A Action roda automaticamente. O site fica em:

```
https://<usuario>.github.io/<repositorio>/
```

Acompanhe em **Actions** no repositório.

## Rodar localmente

```bash
python -m pip install -r requirements-docs.txt
mkdocs serve
```

Abre em `http://127.0.0.1:8000` com recarga automática ao salvar.

## Estrutura

```
docs/
├── index.md                    visão geral e caminho rápido
├── guia/
│   ├── arquitetura.md          como as peças se encaixam
│   ├── rede.md                 por que precisa de túnel
│   ├── 01-mediamtx.md          servidor de mídia
│   ├── 02-tunel.md             endereço público
│   ├── 03-flighthub.md         canal de encaminhamento
│   ├── 04-captura.md           OpenCV
│   ├── 05-visualizacao.md      formas de ver o vídeo
│   ├── latencia.md             reduzir atraso
│   ├── troubleshooting.md      erros reais e correções
│   └── producao.md             migração para VM
└── referencia/
    ├── arquivos.md             configs prontas
    └── comandos.md             cheatsheet
```

## Repositório privado

O GitHub Pages em repositório privado exige plano Enterprise. Alternativas: tornar o repositório público (a documentação não contém credenciais), ou servir internamente com `mkdocs build` e hospedar a pasta `site/`.
