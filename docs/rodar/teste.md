# Modo teste

Exercita a plataforma inteira sem drone: coleta, split, galeria, exclusão, Roboflow e inferência. Mesmo código, mesma latência — só a origem do vídeo muda.

Use isto para desenvolver, treinar operadores e validar mudanças.

## Subir

Três terminais. Em todos:

```bash
cd ~/Desktop/git_repositories/flyhub_connecting
source .venv/bin/activate
```

**Terminal 1 — servidor de mídia**

```bash
./start.sh
```

**Terminal 2 — vídeo**

```bash
./tools/fake_stream.sh                      # padrão colorido 960×720
./tools/fake_stream.sh data/videos/voo.mp4  # seu vídeo, em loop
./tools/fake_stream.sh data/videos/voo.mp4 --copy   # sem reencode
```

**Terminal 3 — aplicação**

```bash
./run.sh
```

Abra `http://localhost:8080`.

## Conferir

```bash
curl -s localhost:9997/v3/paths/list | python3 -m json.tool
```

Precisa vir `"ready": true`.

Na tela: **Disponibilidade** e **Stream** verdes, **Túnel** cinza com "não usado (IP direto)".

## Vídeos de teste

```bash
mkdir -p data/videos
```

Copie os arquivos para lá. O `.gitignore` já protege `data/`.

Vídeo real de voo é muito melhor que o padrão colorido para testar a deduplicação — o padrão quase não muda entre quadros, então quase tudo seria descartado.

Para gravar um trecho durante um voo real:

```bash
ffmpeg -i rtsp://localhost:8554/live/m4td -t 120 -c copy data/videos/voo.mp4
```

Dois minutos bastam. A partir daí você desenvolve sem depender de drone.

## Roteiro completo

Exercita todas as funcionalidades, na ordem:

1. **Home** — confirme os indicadores verdes e o vídeo aparecendo
2. **Coletar imagens do voo** → confirme → intervalo **1 s**, limite **200**
3. Com o padrão colorido, **desligue a dedup** — a imagem muda pouco e quase tudo seria descartado
4. Deixe gravar ~3 minutos, observando o contador
5. **Pausar** → o contador congela → **Continuar** → volta a subir
6. **Salvar** → veja o resumo com contagens e avisos
7. **Datasets** → a versão aparece com a distribuição
8. Clique nela → galeria com abas train/valid/test
9. Selecione 2-3 imagens → **Excluir selecionadas** → confirme
10. Observe o aviso de **manifesto desatualizado**
11. **Refazer o split** → a divergência zera
12. **Enviar ao Roboflow** → preencha e envie

## Testar a inferência

Sem modelo próprio, use um COCO só para medir velocidade:

```bash
mkdir -p data/models
cd data/models && curl -LO https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11n.pt
mv yolo11n.pt best.pt
```

A aplicação detecta pelo mtime e recarrega sozinha, sem reiniciar. Ou clique em **Recarregar pesos**.

O badge muda de "SEM MODELO" para o nome do arquivo, e o campo **FPS de inferência** mostra o número real.

Como é um modelo COCO, ele vai procurar pessoas e carros — não vai detectar nada útil no padrão colorido. Serve só para medir.

## Simular problemas

Para testar o comportamento da aplicação sob falha:

**Queda de conexão**

```bash
timeout 30 ./tools/fake_stream.sh
```

Publica por 30 s e corta. O semáforo deve passar a 🟡 e depois 🔴.

**Mudança de resolução** — reproduz o problema da qualidade "Automático" no FlightHub:

```bash
ffmpeg -re -f lavfi -i testsrc=size=1280x720:rate=30 \
  -c:v libx264 -preset ultrafast -f flv rtmp://localhost:1935/live/m4td
```

Deve aparecer um banner de aviso na tela.

**Path separado** — para o teste não brigar com um voo real:

```bash
STREAM_PATH=live/teste ./tools/fake_stream.sh voo.mp4
```

## Parar

```bash
pkill ffmpeg
pkill -f "uvicorn app.main"
./stop.sh
```
