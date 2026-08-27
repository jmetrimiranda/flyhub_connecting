# Reduzir latência

## De onde vem o atraso

A latência total é a soma de seis parcelas. Vale saber quais você controla.

| Etapa | Típico | Controlável? |
|---|---|---|
| Captura e encode na aeronave | 100–300 ms | Parcialmente (qualidade) |
| Enlace de rádio / 4G até o dock | 200–800 ms | Não |
| Processamento na nuvem DJI | 500–1500 ms | Não |
| Rede até sua casa | 20–80 ms | Já otimizado (IP direto) |
| MediaMTX | 10–50 ms | Sim (configuração) |
| Buffer do OpenCV | **0 a ∞** | **Sim — maior ganho** |

As três primeiras somam de 1 a 2,5 segundos e são intocáveis. O trabalho útil está nas três últimas.

## Ganho 1: buffer do OpenCV

Este é o maior de todos e o mais ignorado.

Se sua inferência é mais lenta que a taxa de quadros, `cap.read()` sequencial forma uma fila que **cresce sem limite**. Após um minuto de operação você pode estar analisando imagem de 30 segundos atrás — e o pior é que não parece um bug, porque o vídeo continua fluido.

A correção é o leitor em thread da a arquitetura de slot único: a thread lê no ritmo da rede e sobrescreve; o laço principal sempre pega o mais recente.

```python
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp"
    "|fflags;nobuffer"        # não acumula pacotes antes de decodificar
    "|flags;low_delay"        # decodifica sem esperar reordenação
    "|reorder_queue_size;0"   # zero buffer de reordenação
    "|max_delay;0"
)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
```

**Impacto: de segundos acumulados para latência constante.**

## Ganho 2: um publisher só

Dois canais publicando no mesmo path se derrubam mutuamente. Sintomas:

```
INF [path live/m4td] closing existing publisher
WAR bore_cli::client: connection exited with error err=Broken pipe
```

Do lado do Python, isso aparece como `reconectando...` e `DESCRIBE failed: 404` a cada poucos segundos. Cada reconexão custa 1–3 s de vídeo perdido e reinicia o buffer.

**Correção:** apague os canais duplicados no FlightHub. **Impacto: elimina cortes periódicos.**

## Ganho 3: qualidade fixa e adequada

No FlightHub, campo **Qualidade do vídeo**:

| Opção | Resolução aprox. | Quando usar |
|---|---|---|
| Suave | 960×720 | Detecção de objeto grande, banda limitada |
| Padrão | 1280×720 | Equilíbrio |
| Alta definição | 1920×1080 | Objeto pequeno, banda boa |
| Automático | variável | **Evite** |

O modo automático troca a resolução em tempo de execução, o que frequentemente derruba o `VideoCapture`.

Menor resolução reduz latência de encode, transmissão e decode ao mesmo tempo. Se sua rede neural trabalha em 640×640, mandar 1080p só desperdiça — você vai reduzir na entrada do modelo de qualquer jeito.

!!! tip "Teste antes de decidir"
    Rode a rede neural nas duas qualidades e compare o recall em objetos pequenos. Se não houver diferença mensurável, fique na menor.

## Ganho 4: IP direto em vez de relay

Já aplicado nesta arquitetura. Um túnel público adicionaria um salto pela internet, possivelmente em outro continente.

Com `PUBLIC_HOST` e port forward, a DJI conecta direto na sua máquina.

**Economia: 100–600 ms.**

## Ganho 5: descartar o áudio

O stream traz uma trilha AAC que o OpenCV ignora, mas que ocupa banda e é demuxada à toa. Para descartar no MediaMTX, configure um path dedicado que reencoda apenas vídeo — ou simplesmente aceite, já que o custo é pequeno.

## Ganho 6: escolher o protocolo certo

| Protocolo | Latência | Uso |
|---|---|---|
| RTSP | 0,1–0,5 s | **OpenCV** |
| MJPEG | ~0,1 s | Dashboard com inferência |
| HLS Low-Latency | 2–4 s | Compartilhamento |
| HLS padrão | 6–15 s | Evite |

Para o OpenCV, sempre RTSP. HLS existe para o navegador.

## Ordem de ataque

Aplique nesta ordem — a lista está em ordem decrescente de impacto por esforço:

1. [x] Apagar canais duplicados
2. [x] Usar o leitor em thread
3. [x] Fixar a qualidade no FlightHub
4. [x] IP público direto (já feito)
5. [ ] Ajustar `hlsPartDuration` se usar HLS

Com 1 a 3 aplicados, espere latência estável de 3 a 5 segundos, dominada pela nuvem da DJI. Chegar abaixo disso exige On-Premises, onde o vídeo não sai da rede local.

## Medindo

Aponte a câmera para um relógio com segundos e compare com o relógio da tela. Grosseiro, mas honesto — e mede o caminho inteiro, que é o que importa.
