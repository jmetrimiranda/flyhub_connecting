# Instalação

Do sistema limpo até a aplicação rodando. Uma vez só.

## 1. Pacotes do sistema

```bash
sudo apt update
sudo apt install -y git python3-venv ffmpeg unzip curl
```

Se o `apt update` reclamar de mudança de prioridade num repositório:

```bash
sudo apt update --allow-releaseinfo-change
```

## 2. Docker

```bash
docker --version || {
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker $USER
  newgrp docker
}
```

!!! note
    O `newgrp` abre um subshell novo. Se você estava com um venv ativo, ele sai — reative depois.

## 3. Driver NVIDIA

```bash
nvidia-smi
```

Deve listar a GPU. Anote a linha `CUDA Version` — ela indica o driver, que é compatível com builds iguais ou anteriores.

Se o comando não existir, instale o driver pela ferramenta da distribuição antes de continuar.

## 4. Clonar

```bash
cd ~/Desktop/git_repositories
git clone https://github.com/jmetrimiranda/flyhub_connecting.git
cd flyhub_connecting
```

## 5. Ambiente Python

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Valide:

```bash
python -c "import cv2, numpy; print('cv2', cv2.__version__, '| numpy', numpy.__version__)"
python -c "import app.main; print('app ok')"
```

## 6. PyTorch e Ultralytics

Só necessário quando houver um modelo para rodar. A aplicação funciona sem.

O sufixo do índice (`cu126`, `cu128`) é o build do CUDA. Escolha o mais alto disponível que seja igual ou menor que o reportado pelo `nvidia-smi`.

```bash
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
python -m pip install ultralytics
```

Confirme que a GPU realmente computa — `is_available()` sozinho não prova:

```bash
python -c "
import torch
print('device:', torch.cuda.get_device_name(0))
print('capability:', torch.cuda.get_device_capability(0))
x = torch.randn(4000, 4000, device='cuda')
print('matmul ok:', (x @ x).sum().item())
print('vram livre:', torch.cuda.mem_get_info()[0] // 1024**2, 'MiB')
"
```

E que o YOLO usa a GPU:

```bash
python -c "
from ultralytics import YOLO
r = YOLO('yolo11n.pt').predict('https://ultralytics.com/images/bus.jpg', device=0, verbose=False)
print('device:', r[0].boxes.data.device)
"
```

Precisa imprimir `cuda:0`.

!!! warning "O ultralytics reinstala o OpenCV com GUI"
    Depois de instalar o ultralytics, confira e limpe:

    ```bash
    python -m pip uninstall -y opencv-python
    python -m pip install "numpy<2.4"
    python -c "import cv2; print(cv2.__version__)"
    ```

## 7. Variáveis de ambiente

```bash
cat > .env << 'ENVEOF'
PUBLIC_HOST=SEU_IP_PUBLICO
ROBOFLOW_API_KEY=sua_chave
ENVEOF
```

Sem aspas em volta dos valores, sem espaço em volta do `=`. O `.env` está no `.gitignore`.

Descubra seu IP público:

```bash
curl -s https://api.ipify.org; echo
```

## 8. Port forward no roteador

Necessário só para o modo voo. O [modo teste](teste.md) funciona sem.

Descubra o IP local da máquina:

```bash
hostname -I | awk '{print $1}'
```

📍 **No roteador:**

1. Reserve esse IP no DHCP, para não mudar
2. Encaminhe a porta externa **1935** → esse IP, porta **1935**

Detalhes e alternativas em [rede e acesso remoto](../operacao/rede.md).

## 9. Primeiro teste

```bash
./start.sh
```

Deve mostrar MediaMTX no ar e o endereço RTMP. Em outro terminal:

```bash
source .venv/bin/activate
./tools/fake_stream.sh
```

E num terceiro:

```bash
source .venv/bin/activate
./run.sh
```

Abra `http://localhost:8080`. O vídeo deve aparecer.

→ [Modo teste](teste.md) para o roteiro completo
