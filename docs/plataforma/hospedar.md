# Hospedar na internet

O problema que impediu rodar na rede da Samarco era **conexão de entrada**: a nuvem da DJI precisa alcançar seu servidor, e uma máquina corporativa atrás de NAT não é alcançável.

Um servidor fora da rede resolve isso sem envolver a TI. Você não está pedindo para abrir porta na Samarco — está usando uma máquina que já nasce na internet.

## O que precisa ser hospedado

```
VPS pública
├── MediaMTX      porta 1935 aberta — a DJI conecta aqui
├── Aplicação     FastAPI + inferência
├── Caddy         HTTPS automático + autenticação
└── data/         datasets e pesos
```

Com IP fixo, o endereço no FlightHub **para de mudar** a cada reinício. Some sua maior fricção diária.

## Opções

| Provedor | Configuração | Custo/mês | Observação |
|---|---|---|---|
| **Oracle Always Free** | 4 vCPU ARM, 24 GB | **R$ 0** | Exige cartão para verificar; disponibilidade oscila |
| **Hetzner** CX22 | 2 vCPU, 4 GB | ~R$ 25 | Melhor custo-benefício; datacenter na Europa |
| **Contabo** VPS S | 4 vCPU, 8 GB | ~R$ 35 | Mais RAM pelo preço |
| **DigitalOcean** | 2 vCPU, 4 GB | ~R$ 130 | Mais caro, interface mais simples |
| **AWS Lightsail** | 2 vCPU, 4 GB | ~R$ 120 | Se preferir ficar em nuvem grande |

O Oracle Always Free é genuinamente gratuito e a máquina ARM de 4 núcleos com 24 GB é generosa. O ponto fraco é disponibilidade — as instâncias gratuitas frequentemente aparecem como esgotadas na região.

Para latência menor, prefira São Paulo quando disponível. Hetzner não tem região no Brasil; some uns 200 ms.

### Sobre GPU

Não vale no começo. Uma T4 na Azure custa ~R$ 2.000/mês.

A saída mais barata é **inferir a cada N quadros** em vez de todos. Detectar 1×/segundo e reaproveitar as caixas nos quadros intermediários devolve o vídeo a 30 fps e mantém a detecção útil — pluma não muda em 300 ms.

Medição feita: YOLO nano em CPU sobre 960×720 dá **3 fps de inferência**, com captura estável em 30 fps.

## Instalar

Numa VPS Ubuntu recém-criada:

```bash
# Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker

# projeto
git clone https://github.com/jmetrimiranda/flyhub_connecting.git
cd flyhub_connecting
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# mídia
docker run -d --name mtx --restart unless-stopped \
  -v $PWD/config/mediamtx.yml:/mediamtx.yml \
  -p 1935:1935 -p 8554:8554 -p 8888:8888 -p 9997:9997 \
  bluenviron/mediamtx:latest
```

**Firewall:**

| Porta | Origem | Motivo |
|---|---|---|
| 1935/TCP | Internet | A DJI não publica faixas de IP fixas |
| 443/TCP | Internet | Painel via HTTPS |
| 22/TCP | Seu IP | Administração |
| 8554, 8888, 9997 | apenas local | Nunca exponha |

## Autenticação — obrigatória antes de expor

!!! danger "A aplicação não tem autenticação"
    `GET /api/pipeline/status` devolve o endereço RTMP completo. O path do stream é a **única credencial** do endpoint de publicação — quem lê essa rota consegue publicar no seu servidor.

    Não exponha o painel sem colocar autenticação na frente.

O Caddy resolve com HTTPS automático:

```bash
sudo apt install -y caddy
caddy hash-password    # anote o hash
```

`/etc/caddy/Caddyfile`:

```
seu-dominio.com {
    basic_auth {
        operador COLE_O_HASH_AQUI
    }
    reverse_proxy localhost:8080
}
```

```bash
sudo systemctl restart caddy
```

Sem domínio, use um gratuito do DuckDNS ou nip.io.

## Serviço permanente

`/etc/systemd/system/painel.service`:

```ini
[Unit]
Description=Painel do pipeline de drone
After=docker.service
Requires=docker.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/flyhub_connecting
Environment="PANEL_PORT=8080"
ExecStart=/home/ubuntu/flyhub_connecting/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now painel
journalctl -u painel -f
```

Note o `--host 127.0.0.1`: a aplicação só escuta local, e quem fala com a internet é o Caddy.

## O que muda no FlightHub

Uma coisa só: o endereço, que passa a ser fixo.

```
rtmp://SEU_IP:1935/live/m4td-a1b2c3
```

Gere um sufixo aleatório — é a credencial do endpoint:

```bash
echo "live/m4td-$(openssl rand -hex 6)"
```

## Considerações antes de decidir

**Onde o dado fica.** Imagem aérea de área industrial numa conta pessoal de VPS estrangeira é uma decisão de governança, não só técnica. Vale alinhar com seu gestor antes de operar continuamente — a validação técnica é uma coisa, operação com dado real é outra.

**A alternativa interna.** Se a Samarco tem Azure (tem — o Databricks roda lá), uma VM na subscription corporativa resolve o mesmo problema com o dado dentro de casa. Custo vai para a empresa e a governança fica resolvida. Exige chamado, mas o pedido é pequeno: uma VM com uma porta liberada.

**Custo comparado.** O Codespace na 4-core em uso intenso passa fácil de R$ 100/mês. Uma VPS de R$ 25 rodando 24/7 sai mais barato e ainda elimina a troca de endereço. Migrar cedo pode economizar.
