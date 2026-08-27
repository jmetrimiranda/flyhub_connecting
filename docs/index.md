# Drone Vision — M4TD

Plataforma que traz o vídeo ao vivo de drones DJI para uma máquina local, roda inferência em tempo real e coleta imagens rotuláveis para retreinar o modelo.

Tudo roda numa máquina só. Sem nuvem, sem custo de GPU, sem túnel.

## O ciclo

```
    ┌──────────────────────────────────────────────────────┐
    │                                                      │
    ▼                                                      │
  VOA ──► COLETA ──► SPLIT ──► ROBOFLOW ──► ANOTA ──► TREINA
  drone     Home     temporal    Datasets    manual    train/
                     automático                            │
                                                           ▼
                                                      best.pt
                                                           │
                                             ┌─────────────┘
                                             ▼
                                      INFERÊNCIA AO VIVO
                                      Home + tela Modelo
```

Cada volta melhora o modelo. A plataforma cobre tudo menos a anotação, que é manual no Roboflow — e mesmo essa fica mais rápida a cada rodada, porque o modelo anterior pré-rotula.

## Máquina de referência

| Item | Valor |
|---|---|
| Máquina | Alienware 16 Area-51 |
| GPU | RTX 5070 Laptop, 8 GB VRAM |
| RAM | 64 GB |
| Sistema | Ubuntu |
| Python | 3.14 |
| CUDA | 12.8 (torch 2.11) |

Qualquer máquina Linux com GPU NVIDIA serve. Sem GPU também roda, mas a inferência cai para ~3 fps.

## Por onde começar

**Primeira vez** → [Instalação](rodar/index.md)

**Já instalado, quer testar sem drone** → [Modo teste](rodar/teste.md)

**Tem voo agendado** → [Modo voo](rodar/voo.md)

**Quer entender como funciona** → [Arquitetura](arquitetura/index.md)

**Vai treinar um modelo** → [Treinar o modelo](treino/index.md)

## Estado atual

| Componente | Situação |
|---|---|
| Ingestão de vídeo | Funcionando |
| Inferência ao vivo | Funcionando (passthrough sem pesos) |
| Coleta e split temporal | Funcionando |
| Envio ao Roboflow | Funcionando |
| Treino | Script pronto, sem modelo treinado ainda |
| Autenticação | **Não implementada** |

!!! danger "Sem autenticação"
    A rota `/api/pipeline/status` devolve o endereço RTMP completo, e o path do stream é a única credencial do endpoint de publicação.

    Em rede local, tudo bem. Não exponha a porta 8080 à internet sem colocar um proxy com autenticação na frente.
