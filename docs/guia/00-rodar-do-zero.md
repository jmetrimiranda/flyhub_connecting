# Rodar do zero

Do ambiente vazio até ver quadros do drone no Python.

Se você só quer operar o sistema, esta é a única página necessária. As demais existem para quando algo der errado ou você quiser entender o porquê.

!!! tip "Dois modos"
    **Com drone** — precisa de dispositivo online e acesso ao FlightHub.

    **Sem drone** — um gerador de vídeo sintético alimenta o pipeline. Mesmo código, mesma latência, sem depender de voo. Use isso para desenvolver. Veja [testar sem drone](testar-sem-drone.md).

---

## Parte 1 — Subir o servidor

**Onde:** terminal do Codespace ou VM.

### 1.1 Conferir o ambiente

```bash
cd /workspaces/flyhub_connecting
docker --version && bore --version && python3 --version
```

Se `bore` não for encontrado, o container foi recriado sem o setup:

```bash
bash .devcontainer/setup.sh
```

### 1.2 Instalar dependências

```bash
python3 -m pip install -r requirements.txt
```

### 1.3 Subir o painel

```bash
./run.sh
```

Porta **8080**. No Codespaces aparece um aviso oferecendo abrir; se não, use a aba **PORTS**.

!!! danger "Mantenha a porta do painel como Private"
    A rota de status devolve o endereço RTMP completo, e o path do stream é a única credencial do endpoint de publicação. Quem alcançar a porta consegue publicar no seu servidor.

    A porta 8888 (HLS) pode ser pública para compartilhar visualização. A do painel, não.

### 1.4 Iniciar o pipeline

Na tela, clique em **Iniciar pipeline**. Em ~1,6 s os quatro passos ficam verdes:

```
✓ MediaMTX    container mtx no ar
✓ API         respondendo em :9997
✓ Túnel       bore local 1935 --to bore.pub
✓ Endereço    bore.pub:57577
```

Clique em **Copiar** ao lado do endereço RTMP.

??? note "Prefere terminal?"
    ```bash
    ./stop.sh && ./start.sh
    ```

    Faz o mesmo e imprime o endereço. Painel e scripts são intercambiáveis — mas **não use os dois ao mesmo tempo**: ambos removem o container `mtx` e matam qualquer processo `bore`.

---

## Parte 2 — Configurar o FlightHub

**Onde:** navegador, `fh.dji.com`. Requer **Administrador da organização**.

Este é o único passo que o painel não automatiza.

### 2.1 Chegar na tela certa

1. Seu e-mail (canto superior direito) → **Minha organização**
2. **Confirme a organização.** Dispositivos e canais são isolados por organização — um canal criado na organização errada nunca receberá vídeo
3. Ícone de **engrenagem** da linha → Configurações da organização
4. Card **FlightHub Sync** → **Detalhes**
5. Card **Encaminhamento de transmissão ao vivo**

### 2.2 Editar o canal

Os ícones de ação, da esquerda para a direita: **editar** (folha com lápis), **copiar** (duas folhas), **excluir** (lixeira).

Clique no **primeiro** — editar.

!!! danger "Nunca use o ícone de copiar para editar"
    Ele abre um diálogo intitulado "Canal de encaminhamento **de cópia**" e cria um canal novo ao confirmar. Dois canais publicando no mesmo path se derrubam mutuamente — o MediaMTX registra `closing existing publisher` e a conexão cai a cada poucos segundos.

    Se já existirem duplicados, apague todos menos um.

### 2.3 Os campos

| Campo | Valor | Por quê |
|---|---|---|
| **Nome do canal** | livre | Use algo identificável, não o timestamp padrão |
| **Tipo** | RTMP | Mais rodado. RTSP também funciona |
| **Endereço do servidor** | `rtmp://bore.pub:57577/live/m4td` | Cole o do painel |
| **Nome do dispositivo** | o que vai voar | Aeronave ou dock |
| **Fonte de transmissão** | Carga-zoom / wide / IV | Wide para área ampla, zoom para detalhe |
| **Qualidade do vídeo** | **fixa** | Ver abaixo |

!!! warning "Qualidade 'Automático' quebra a captura"
    No modo automático a resolução muda conforme a banda disponível. Quando isso acontece durante a transmissão, o `cv2.VideoCapture` perde a conexão e você vê:

    ```
    reconectando...
    [rtsp] method DESCRIBE failed: 404 (Not Found)
    [h264] error while decoding MB 46 1, bytestream -11
    ```

    Observado na prática: o stream saiu de 960×720 para 1280×720 no meio do voo e a captura caiu.

    Escolha um valor fixo. Resolução estável vale mais que qualidade máxima para visão computacional.

### 2.4 Ativar

1. **Confirmar**
2. Toggle **Status do canal** azul (ligado)
3. Desligue o toggle, espere 5 s, ligue de novo

O passo 3 força a DJI a reconectar no endereço novo. Sem ele, ela continua tentando o antigo.

O **Status do dispositivo** precisa estar `Online`. Offline significa equipamento desligado — nada será encaminhado.

---

## Parte 3 — Confirmar e capturar

### 3.1 O semáforo

Volte ao painel. Em segundos:

```
🟢 Recebendo — 1280×720 · 7.55 Mbps
```

| Cor | Significado | Ação |
|---|---|---|
| 🟢 | Vídeo chegando | Siga para 3.2 |
| 🟡 | Conectado, sem dados | Aguarde; se persistir, veja abaixo |
| 🔴 `Sem stream` | Ninguém publicando | Confira endereço e toggle |
| 🔴 `MediaMTX não responde` | Servidor caiu | Parar e Iniciar |

Um piscar amarelo no início é esperado — a taxa é derivada e o primeiro ciclo marca zero.

### 3.2 Ver o vídeo

Confirmação visual rápida, no navegador:

```
http://localhost:8888/live/m4td
```

Em Codespaces: encaminhe a porta 8888 e acrescente o path à URL gerada.

### 3.3 Capturar

Terminal novo — o painel precisa continuar rodando:

```bash
python3 capture.py
```

```
conectado
30 quadros | 14.8 fps | (720, 1280, 3)
60 quadros | 15.1 fps | (720, 1280, 3)
```

O `frame.jpg` é gravado a cada 30 quadros. Clique nele na árvore do VS Code.

A inferência entra no lugar marcado dentro do laço:

```python
# ---- inferência entra aqui ----
# results = model(frame)
```

---

## A sincronia de endereços

Esta é a fricção central do setup, e a causa mais comum de "não funciona".

O túnel gratuito gera **porta nova a cada reinício**. Se o FlightHub tiver o endereço antigo, o canal fica em "Não está transmitindo" mesmo com tudo online.

| Onde olhar | O que deve bater |
|---|---|
| Painel → Endereço para o FlightHub | `rtmp://bore.pub:57577/live/m4td` |
| FlightHub → Endereço do servidor | idêntico |

Sempre que reiniciar o pipeline, **recopie e reedite**. Só uma VM com IP fixo elimina isso.

---

## Um publisher por path

Dois publicadores no mesmo path se derrubam mutuamente. Isso acontece de duas formas:

**Canais duplicados no FlightHub** — apague as cópias.

**Gerador sintético ainda rodando** — se você testou sem drone, encerre o ffmpeg (`q` no terminal dele) antes de ligar o drone.

Sintoma nos logs:

```bash
docker logs mtx | grep "closing existing publisher"
```

---

## Encerrar

```bash
./stop.sh
```

Ou o botão **Parar pipeline**. Depois `Ctrl+C` no `capture.py` e no `run.sh`.

---

## Checklist pré-voo

- [ ] Painel rodando, porta Private
- [ ] Pipeline iniciado, quatro passos verdes
- [ ] Endereço do painel **idêntico** ao do FlightHub
- [ ] Toggle religado após editar
- [ ] Apenas um canal ativo
- [ ] Nenhum ffmpeg de teste rodando
- [ ] Qualidade fixa, não "Automático"
- [ ] Dispositivo Online
- [ ] Semáforo verde
- [ ] `capture.py` rodando

---

## Se algo falhar

| Sintoma | Onde olhar |
|---|---|
| Passo `API` falhou | `docker logs mtx` |
| Passo `Endereço` falhou | `tail /tmp/bore.log` |
| Semáforo vermelho com tudo verde | endereço ou toggle no FlightHub |
| Stream cai a cada 30 s | canal duplicado ou ffmpeg competindo |
| `reconectando` + `decoding MB` | qualidade em "Automático" |
| `ImportError: libGL` | duas variantes do OpenCV instaladas |

Lista completa em [solução de problemas](troubleshooting.md); quando reiniciar, em [reiniciar o pipeline](reiniciar.md).
