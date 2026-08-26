# Como rodar

Dois modos, mesmo código. A única diferença é quem publica o vídeo.

```
MODO REAL     drone → FlightHub → túnel ──┐
                                          ├─► MediaMTX → aplicação
MODO TESTE    ffmpeg com vídeo local ─────┘
```

No modo teste você exercita **tudo**: coleta, split, galeria, exclusão e envio ao Roboflow. Só a origem do vídeo muda.

---

## Modo teste

### 1. Subir o servidor de mídia

```bash
cd /workspaces/flyhub_connecting
./stop.sh && ./start.sh
```

O túnel sobe junto, mas no modo teste você pode ignorá-lo — o vídeo entra por `localhost`.

### 2. Publicar o vídeo

**Padrão colorido**, sem precisar de arquivo:

```bash
./tools/fake_stream.sh
```

**Seu próprio vídeo**, em loop infinito:

```bash
./tools/fake_stream.sh caminho/do/voo.mp4
```

Se o vídeo já for H.264, use `--copy` para não gastar CPU reencodando:

```bash
./tools/fake_stream.sh voo.mp4 --copy
```

Deixe rodando. `Ctrl+C` para parar.

### 3. Subir a aplicação

```bash
pkill -f "uvicorn app.main"
./run.sh
```

Abra a porta 8080. O vídeo deve aparecer na Home em segundos.

### Onde colocar seus vídeos

Qualquer lugar, mas o `.gitignore` já protege `data/`:

```bash
mkdir -p data/videos
# arraste os arquivos para essa pasta no VS Code
./tools/fake_stream.sh data/videos/voo_ubu.mp4
```

Vídeos gravados de voos reais são muito melhores que o padrão colorido para testar coleta e dedup — o padrão nunca muda, então a deduplicação descarta quase tudo.

### Gravar um trecho real para reutilizar

Durante um voo, num terminal separado:

```bash
ffmpeg -i rtsp://localhost:8554/live/m4td -t 120 -c copy data/videos/voo.mp4
```

Dois minutos bastam. A partir daí você desenvolve sem depender de drone.

### Testar em path separado

Para o teste não brigar com o drone:

```bash
STREAM_PATH=live/teste ./tools/fake_stream.sh voo.mp4
```

O MediaMTX aceita quantos paths quiser, e o painel lista todos na tabela.

---

## Modo real

### 1. Subir o pipeline

```bash
cd /workspaces/flyhub_connecting
./stop.sh && ./start.sh
```

Anote o endereço RTMP impresso.

### 2. Configurar o FlightHub

📍 **Navegador**, em `fh.dji.com`:

1. Minha organização → engrenagem → FlightHub Sync → Detalhes
2. Card **Encaminhamento de transmissão ao vivo**
3. Ícone de **lápis** no canal — nunca o de copiar
4. Cole o endereço em **Endereço do servidor**
5. **Qualidade do vídeo: um valor fixo**, nunca "Automático"
6. Confirmar
7. Desligue o toggle, espere 5 s, ligue

!!! danger "Apenas um canal ativo"
    Dois canais no mesmo path se derrubam mutuamente e a conexão cai a cada poucos segundos. Se houver duplicados, apague todos menos um.

!!! warning "Qualidade 'Automático' quebra a captura"
    A resolução muda em tempo de execução e derruba o `VideoCapture`. Já observado indo de 960×720 para 1280×720 no meio do voo.

### 3. Subir a aplicação

```bash
pkill -f "uvicorn app.main"
./run.sh
```

O semáforo deve ficar 🟢 quando o dispositivo estiver online.

---

## Fluxo completo de um teste

Roteiro para exercitar tudo de ponta a ponta:

1. **Suba** servidor, vídeo e aplicação
2. **Home** → confirme os quatro indicadores verdes
3. **Criar dataset** → confirme a versão → intervalo 1 s, limite 100
4. Deixe gravar ~2 minutos, observando o contador
5. **Pausar** → o contador congela → **Continuar** → volta a subir
6. **Salvar** → o split roda → veja o resumo com as contagens
7. **Datasets** → a versão aparece na lista com a distribuição
8. Clique nela → galeria com abas train/valid/test
9. Selecione 2-3 imagens → **Excluir selecionadas** → confirme
10. Veja o aviso de **manifesto desatualizado**
11. **Refazer o split** → a divergência zera
12. **Enviar ao Roboflow** → preencha e envie

O passo 12 exige um projeto no Roboflow. Crie um vazio, pegue a API key em Settings → API Keys, e use o workspace e projeto que aparecem na URL do projeto.

Para não digitar a chave toda vez:

```bash
echo "ROBOFLOW_API_KEY=sua_chave" >> .env
```

O `.env` está no `.gitignore` — a chave nunca sobe para o repositório.

---

## Parar tudo

```bash
pkill ffmpeg
pkill -f "uvicorn app.main"
./stop.sh
```

📍 **Navegador:** `github.com/codespaces` → `...` → **Stop codespace**

Codespace esquecido ligado consome cota mesmo sem você usar.
