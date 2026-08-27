# Serviço permanente

Para a plataforma subir sozinha no boot e sobreviver a quedas, sem depender de terminal aberto.

## MediaMTX

Já resolvido. O container sobe com `--restart unless-stopped`, então o Docker o reinicia no boot e após falha.

```bash
docker ps --filter name=mtx --format "{{.Names}} {{.Status}}"
```

## Aplicação

Crie `/etc/systemd/system/painel.service`:

```ini
[Unit]
Description=Painel Drone Vision
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=simple
User=jorgemetri
WorkingDirectory=/home/jorgemetri/Desktop/git_repositories/flyhub_connecting
EnvironmentFile=/home/jorgemetri/Desktop/git_repositories/flyhub_connecting/.env
Environment="PANEL_PORT=8080"
ExecStart=/home/jorgemetri/Desktop/git_repositories/flyhub_connecting/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Ajuste `User` e os caminhos.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now painel
systemctl status painel
```

Acompanhar os logs:

```bash
journalctl -u painel -f
```

!!! note "EnvironmentFile e o .env"
    O systemd lê o `.env` diretamente, mas é mais restritivo que o shell: sem aspas, sem espaços em volta do `=`, sem comentários na mesma linha.

    Se o serviço não subir, `journalctl -u painel -n 50` mostra o motivo.

## Operação

```bash
sudo systemctl restart painel    # reiniciar
sudo systemctl stop painel       # parar
sudo systemctl disable painel    # não subir no boot
```

Para desenvolver, pare o serviço e rode manualmente — assim você vê a saída direto no terminal:

```bash
sudo systemctl stop painel
./run.sh
```

## Verificação de saúde

A API do MediaMTX serve como health check:

```bash
curl -s localhost:9997/v3/paths/list \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if any(i['ready'] for i in d['items']) else 'SEM STREAM')"
```

Para monitorar continuamente, um cron simples:

```bash
*/5 * * * * curl -sf localhost:9997/v3/paths/list >/dev/null || systemctl restart painel
```

## Espaço em disco

Datasets crescem. Um voo de 10 minutos a 2 s gera ~300 imagens, e cada versão mantém `raw/` **mais** as três partições — então o custo é aproximadamente o dobro.

```bash
du -sh data/datasets/*
df -h .
```

A aplicação para a coleta automaticamente quando o disco passa de 90%, mas vale limpar antes:

```bash
# depois de enviar ao Roboflow, o raw/ local é redundante
rm -rf data/datasets/v0.3/raw
```

⚠️ Sem `raw/` você perde a capacidade de refazer o split. Só apague depois de ter certeza da partição.

## Acesso de outra máquina

Com o serviço rodando em `0.0.0.0:8080`, qualquer máquina na mesma rede alcança por `http://IP_LOCAL:8080`.

Para acessar de fora da rede — do PC da Samarco, por exemplo — veja [rede e acesso remoto](../operacao/rede.md). A recomendação é Tailscale.

!!! danger "Não exponha a 8080 à internet"
    `GET /api/pipeline/status` devolve o endereço RTMP completo, e o path do stream é a única credencial do endpoint de publicação.

    Se precisar de acesso externo direto, coloque um proxy com autenticação na frente e mantenha o uvicorn em `127.0.0.1`.
