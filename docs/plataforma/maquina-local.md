# Rodar em máquina local

Setup completo numa máquina Linux com GPU NVIDIA. É o ambiente definitivo do projeto: a inferência roda em tempo real e o treino acontece na mesma máquina.

Referência usada nesta página: Alienware 16 Area-51, RTX 5070 Laptop (8 GB VRAM), 64 GB RAM, Ubuntu.

## Por que sair do Codespace

| | Codespace | Máquina local |
|---|---|---|
| Inferência | ~3 fps (CPU) | 30+ fps (GPU) |
| Treino | inviável | na mesma máquina |
| Custo | por hora | zero |
| Disco | 32 GB fixos | o que você tiver |
| Sessão | hiberna em 30 min | permanente |

---

## 1. Pré-requisitos

```bash
sudo apt update
sudo apt install -y git python3-venv ffmpeg unzip curl
```

**Docker**, para o MediaMTX:

```bash
docker --version || {
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker $USER
  newgrp docker
}
```

**Driver NVIDIA** — confirme que já está instalado:

```bash
nvidia-smi
```

Anote a linha `CUDA Version`. Ela indica o driver, não a versão que o PyTorch precisa — drivers recentes são compatíveis com builds mais antigos.

---

## 2. Clonar e criar o ambiente

```bash
cd ~/Desktop/git_repositories
git clone https://github.com/jmetrimiranda/flyhub_connecting.git
cd flyhub_connecting
```

!!! warning "Cuidado com a versão do Python"
    O PyTorch costuma demorar meses para publicar wheels de versões novas. Se o `python3` do sistema for muito recente (3.14 ou mais), o `pip install torch` falha.

    Confira antes:

    ```bash
    python3 --version
    ```

    Se for 3.13+, prefira criar o ambiente com 3.12:

    ```bash
    sudo apt install -y python3.12 python3.12-venv
    python3.12 -m venv .venv
    ```

    A aplicação em si roda em qualquer versão — o problema é só o torch.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Recrie o `.env` — ele não vem do Git:

```bash
cat > .env << 'ENVEOF'
ROBOFLOW_API_KEY=sua_chave_aqui
ENVEOF
```

Sem aspas em volta do valor, sem espaço em volta do `=`.

---

## 3. GPU e PyTorch

O sufixo do índice (`cu126`, `cu128`) refere-se ao build do CUDA, não ao driver. Escolha o mais alto disponível que seja igual ou inferior ao que o `nvidia-smi` reporta.

```bash
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
python -m pip install ultralytics
```

Verifique:

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Precisa imprimir `True` e o nome da placa. Se vier `False`, o build do CUDA não bate com o driver — tente outro sufixo.

!!! note "A aplicação funciona sem torch"
    Sem pesos, o `Detector` entra em passthrough e o vídeo passa cru. Você pode adiar essa etapa e voltar quando tiver um modelo treinado.

---

## 4. Rodar

Três terminais. Em todos: `cd` no projeto e `source .venv/bin/activate`.

=== "Modo teste"

    **Terminal 1 — servidor de mídia**
    ```bash
    ./start.sh
    ```

    **Terminal 2 — vídeo**
    ```bash
    ./tools/fake_stream.sh                      # padrão colorido
    ./tools/fake_stream.sh data/videos/voo.mp4  # seu vídeo, em loop
    ./tools/fake_stream.sh data/videos/voo.mp4 --copy   # sem reencode
    ```

    **Terminal 3 — aplicação**
    ```bash
    ./run.sh
    ```

=== "Modo real"

    **Terminal 1**
    ```bash
    ./start.sh
    ```
    Anote o endereço RTMP.

    **No FlightHub:** editar canal (lápis) → colar endereço → qualidade **fixa** → toggle off/on.

    **Terminal 2 — aplicação**
    ```bash
    ./run.sh
    ```

Abra `http://localhost:8080`.

### Vídeos de teste

```bash
mkdir -p data/videos
```

Copie os arquivos para lá. O `.gitignore` já protege `data/`.

Para gravar um trecho durante um voo real:

```bash
ffmpeg -i rtsp://localhost:8554/live/m4td -t 120 -c copy data/videos/voo.mp4
```

---

## 5. Rede

A nuvem da DJI precisa alcançar a porta 1935 da sua máquina. Depende de onde ela está.

=== "Em casa"

    A melhor situação. Port forward no roteador, endereço fixo, sem túnel.

    Confirme antes que não há CGNAT:

    ```bash
    curl -s https://api.ipify.org; echo     # IP público visto pela internet
    ```

    Compare com o WAN do roteador. Se forem iguais, funciona. Se o WAN for `100.64.x.x`, é CGNAT e o port forward não resolve — ligue para o provedor e peça IP público.

    No roteador: encaminhe a porta externa 1935 para o IP local da máquina, porta 1935.

    No FlightHub: `rtmp://SEU_IP_PUBLICO:1935/live/m4td`

    Fixe o IP local da máquina no DHCP do roteador, senão o encaminhamento quebra quando o IP mudar.

=== "Na rede corporativa"

    Mesmo problema de sempre: NAT bloqueia entrada. Use túnel reverso.

    ```bash
    cd ~
    URL=$(curl -s https://api.github.com/repos/ekzhang/bore/releases/latest \
      | grep browser_download_url | grep x86_64-unknown-linux-musl | cut -d '"' -f 4)
    curl -sL "$URL" | tar xz
    sudo mv bore /usr/local/bin/
    ```

    O `start.sh` já sobe o bore junto. O endereço muda a cada reinício.

=== "IP dinâmico"

    Se o provedor troca seu IP periodicamente, use DNS dinâmico (DuckDNS, No-IP) e configure o cliente na máquina. Aí o FlightHub aponta para um nome estável em vez de um número que muda.

---

## 6. Serviço permanente

Para a aplicação subir sozinha no boot:

```ini
# /etc/systemd/system/painel.service
[Unit]
Description=Painel do pipeline de drone
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=simple
User=jorgemetri
WorkingDirectory=/home/jorgemetri/Desktop/git_repositories/flyhub_connecting
Environment="PANEL_PORT=8080"
ExecStart=/home/jorgemetri/Desktop/git_repositories/flyhub_connecting/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
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

O MediaMTX já sobe sozinho pelo `--restart unless-stopped` do Docker.

!!! danger "Não exponha o painel sem autenticação"
    `GET /api/pipeline/status` devolve o endereço RTMP completo, e o path é a única credencial do endpoint. Em rede local tudo bem; para acesso externo, coloque um proxy com autenticação na frente (ver [hospedar](hospedar.md)).

---

## 7. Treinar

Depois de anotar as imagens no Roboflow:

```bash
source .venv/bin/activate
python -m pip install -r train/requirements.txt
python train/train.py --data caminho/data.yaml --epochs 100 --batch 16
```

Com 8 GB de VRAM, `--batch 16` em 640px costuma caber. Se der out of memory, reduza para 8.

Ao final, o script grava `data/models/best.pt` e `data/models/metrics.json`. A aplicação detecta o arquivo novo pelo mtime e recarrega sozinha — sem reiniciar o processo.

Detalhes completos em `train/README.md`.

---

## Diferenças em relação ao Codespace

| | Codespace | Local |
|---|---|---|
| Ativar venv | automático | `source .venv/bin/activate` |
| Portas | aba PORTS | `localhost` direto |
| Parar ao terminar | obrigatório (custo) | opcional |
| Endereço RTMP | sempre túnel | port forward, se em casa |
| GPU | não | sim |

Os scripts `start.sh`, `stop.sh`, `run.sh` e `tools/fake_stream.sh` funcionam igual — foram escritos para Linux desde o início.
