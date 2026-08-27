# Modo voo

Captura do drone real, via FlightHub 2.

## Pré-requisitos

- [x] Port forward da porta 1935 configurado no roteador
- [x] `PUBLIC_HOST` no `.env` com o IP público
- [x] Acesso de Administrador da organização no FlightHub 2
- [x] Dispositivo capaz de ficar online

## 1. Subir a aplicação

Dois terminais, ambos com o venv ativo:

```bash
cd ~/Desktop/git_repositories/flyhub_connecting
source .venv/bin/activate
```

**Terminal 1**

```bash
./start.sh
```

Saída esperada:

```
==> MediaMTX
    API respondendo
==> Túnel: pulado (PUBLIC_HOST=177.184.48.79)
┌──────────────────────────────────────────────────────────┐
  Cole no FlightHub → Endereço do servidor:

      rtmp://177.184.48.79:1935/live/m4td

└──────────────────────────────────────────────────────────┘
  Endereço fixo (PUBLIC_HOST) — não muda entre reinícios.
```

**Terminal 2**

```bash
./run.sh
```

## 2. Configurar o canal no FlightHub

Só precisa fazer uma vez. Com `PUBLIC_HOST`, o endereço não muda entre reinícios.

📍 **Navegador**, em `fh.dji.com`:

1. Seu e-mail → **Minha organização**
2. **Confirme a organização** — dispositivos e canais são isolados por organização
3. Ícone de **engrenagem** → Configurações
4. Card **FlightHub Sync** → **Detalhes**
5. Card **Encaminhamento de transmissão ao vivo**
6. Ícone de **lápis** no canal

| Campo | Valor |
|---|---|
| Tipo | RTMP |
| Endereço do servidor | `rtmp://SEU_IP:1935/live/m4td` |
| Nome do dispositivo | o que vai voar |
| Fonte de transmissão | Carga-zoom / wide / IV |
| Qualidade do vídeo | **fixa**, nunca "Automático" |

Confirme, depois **desligue o toggle, espere 5 s e ligue novamente**.

!!! danger "Nunca use o ícone de copiar para editar"
    Ele abre um diálogo chamado "Canal de encaminhamento **de cópia**" e cria um canal novo. Dois canais publicando no mesmo path se derrubam mutuamente — o MediaMTX registra `closing existing publisher` e a conexão cai a cada poucos segundos.

    Se já existirem duplicados, apague todos menos um.

!!! warning "Qualidade 'Automático' quebra a captura"
    A resolução muda em tempo de execução e derruba o `VideoCapture`. Já observado indo de 960×720 para 1280×720 no meio do voo, produzindo:

    ```
    reconectando...
    [rtsp] method DESCRIBE failed: 404 (Not Found)
    [h264] error while decoding MB 46 1, bytestream -11
    ```

## 3. Confirmar

O **Status do dispositivo** precisa estar `Online`. Offline significa equipamento desligado.

No painel, o semáforo deve ficar verde em segundos:

```
🟢 Recebendo — 1280×720 · 7.55 Mbps
```

| Cor | Significado | Ação |
|---|---|---|
| 🟢 | Vídeo chegando | Pode coletar |
| 🟡 | Conectado, sem dados | Aguarde; se persistir, investigue |
| 🔴 `Sem stream` | Ninguém publicando | Confira endereço e toggle |
| 🔴 `MediaMTX não responde` | Servidor caiu | Parar e Iniciar |

Um piscar amarelo no início é esperado — a taxa é derivada e o primeiro ciclo marca zero.

## 4. Coletar

**Coletar imagens do voo** → confirme a versão → ajuste intervalo e limite.

| Parâmetro | Recomendado para voo real |
|---|---|
| Intervalo | 1–2 s |
| Limite | 500 ou ilimitado |
| Dedup | **ligada** |

Com vídeo real a dedup funciona bem: quando o drone paira, ela descarta as repetições sem perder informação.

Durante a gravação: **Pausar** congela sem fechar a sessão, **Continuar** retoma, **Salvar** encerra e dispara o split.

!!! tip "Colete bastante"
    O split reserva 15% para validação e 15% para teste, com margem de descarte nas fronteiras. Em dataset pequeno a margem pesa desproporcionalmente — com 87 quadros, `valid` ficou com 4% em vez de 15%.

    Voo de 10 minutos a 2 s dá ~300 quadros, e aí as proporções se aproximam do pedido.

## 5. Encerrar

```bash
./stop.sh
```

## Checklist pré-voo

- [ ] `./start.sh` mostra MediaMTX no ar
- [ ] `./run.sh` rodando
- [ ] Endereço no FlightHub igual ao do `PUBLIC_HOST`
- [ ] Toggle religado após qualquer edição
- [ ] Apenas um canal ativo
- [ ] Nenhum `ffmpeg` de teste rodando (`pkill ffmpeg`)
- [ ] Qualidade fixa, não "Automático"
- [ ] Dispositivo Online
- [ ] Semáforo verde
- [ ] Espaço em disco suficiente

## Se nada chegar

Verifique na ordem do fluxo:

```bash
# o servidor está de pé?
docker ps | grep mediamtx

# a API responde?
curl -s localhost:9997/v3/paths/list

# o que o servidor viu?
docker logs --tail 50 mtx
```

| Onde parou | Causa provável |
|---|---|
| Nenhuma conexão nos logs | Port forward, firewall, ou endereço errado no canal |
| `opened` seguido de `closed` | Autenticação ou path recusado |
| `closing existing publisher` | Canal duplicado |
| Tudo ok mas 🔴 | Dispositivo offline ou toggle desligado |

Teste se a porta está alcançável de fora — use o celular no 4G, não o Wi-Fi de casa:

```bash
# na máquina, deixe escutando
nc -l 1935
```

Depois, do celular, tente conectar em `SEU_IP:1935`. Se nada chegar, o port forward não está funcionando.

Mais em [solução de problemas](../operacao/troubleshooting.md).
