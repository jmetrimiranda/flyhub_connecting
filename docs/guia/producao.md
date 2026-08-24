# Ir para produção

O que muda entre a validação em Codespace e uma operação contínua.

## O que não serve em produção

| Item | Problema |
|---|---|
| Codespaces | Hiberna após ~30 min ocioso |
| bore.pub | Endereço muda a cada reinício, relay de terceiros, sem SLA |
| Túnel gratuito | Sem criptografia, sem garantia |

## Infraestrutura mínima

Uma VM Linux com IP público, na mesma região e rede virtual do restante do stack de dados.

| Perfil | Uso |
|---|---|
| 2 vCPU / 8 GB | Apenas ingestão e repasse |
| GPU (T4 ou superior) | Ingestão + inferência na mesma máquina |

**Firewall:**

| Porta | Origem | Motivo |
|---|---|---|
| 1935/TCP | Internet | A DJI não publica faixas de IP fixas |
| 8554/TCP | Rede interna | Consumo RTSP |
| 9997/TCP | Rede interna | API de status |
| 22/TCP | Rede corporativa | Administração |

Expor a 1935 para a internet é inevitável. A proteção é o path: sem conhecer `/live/<sufixo>`, ninguém publica nem lê.

```bash
echo "live/m4td-$(openssl rand -hex 6)"
```

## Onde a inferência roda

Vídeo ao vivo não se encaixa bem em Spark. Clusters são orientados a batch e micro-batch — não mantêm conexão RTSP contínua e desligam por inatividade.

O padrão que funciona:

```
VM: MediaMTX + inferência
      │
      ├─→ detecções (linha por evento) ──> Delta
      ├─→ quadros com evento ───────────> ADLS/S3 ──> Auto Loader
      └─→ MJPEG ────────────────────────> dashboard interno
```

O lakehouse recebe o que ele faz bem: histórico, consulta, dashboard, treino. A VM cuida do tempo real.

Se o modelo já está registrado em MLflow, sirva-o como endpoint e faça a VM consumir por HTTP — assim o versionamento continua centralizado e você não duplica código de inferência.

## Serviço permanente

O MediaMTX com `--restart unless-stopped` sobrevive a reinício do Docker. Para o script de captura, use systemd:

```ini
# /etc/systemd/system/captura.service
[Unit]
Description=Captura e inferencia do stream do drone
After=docker.service
Requires=docker.service

[Service]
Type=simple
User=app
WorkingDirectory=/opt/captura
Environment="STREAM_URL=rtsp://localhost:8554/live/m4td-a1b2c3"
ExecStart=/opt/captura/.venv/bin/python capture.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now captura
journalctl -u captura -f
```

## Monitoramento

A API do MediaMTX serve como health check:

```bash
curl -s localhost:9997/v3/paths/list \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if any(i['ready'] for i in d['items']) else 'SEM STREAM')"
```

Métricas que valem alerta:

- `bytesReceived` parado por mais de 30 s com dispositivo online
- `inboundFramesInError` crescendo
- Ausência de path quando deveria haver voo em andamento

## Cota e custo

Segundo a documentação da DJI, o encaminhamento via FlightHub Sync consome minutos de transmissão. Em plano Enterprise com minutos ilimitados, irrelevante. Em plano por minuto, desligue o canal fora de operação — via toggle na interface ou pela OpenAPI.

Atenção também ao **limite de dispositivos online simultâneos** do plano. Um limite de 1 impede manter dock e aeronave online ao mesmo tempo.

## Automatizar o start/stop

A OpenAPI do FlightHub 2 permite habilitar e desabilitar encaminhamento por código. O token (`X-User-Token`) é a **Organization Key**, encontrada no card **OpenAPI** das configurações da organização.

```python
import os, requests

H = {
    "X-User-Token": os.environ["FH2_ORG_KEY"],
    "X-Project-Uuid": os.environ["FH2_PROJECT_UUID"],
    "Content-Type": "application/json",
}
```

A referência da API é publicada pela DJI no Apifox. A base URL não consta na documentação — confirme com o suporte ou inspecione as chamadas da própria interface.

Com isso é possível ligar o encaminhamento quando uma missão inicia e desligar ao terminar, sem intervenção manual.
