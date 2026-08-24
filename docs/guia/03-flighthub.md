# 3. Canal no FlightHub

Registra o endereço do seu servidor para que a nuvem da DJI publique nele.

**Onde:** navegador, em `fh.dji.com`. Requer papel de **Administrador da organização** ou **Super-Admin**.

## Navegação

1. Canto superior direito → seu e-mail → **Minha organização**
2. **Confirme em qual organização está o dispositivo que vai voar.** Organizações são isoladas: dispositivos, canais e cotas não são compartilhados. Clique no nome da organização correta para torná-la a atual
3. Clique no ícone de **engrenagem** da linha → abre "Configurações da organização"
4. Card **FlightHub Sync** → **Detalhes**
5. Card **Encaminhamento de transmissão ao vivo** → clique no card

Você chega na lista de canais.

!!! warning "Organização errada é o erro mais comum"
    Um canal criado na organização A nunca vai receber vídeo de um dispositivo da organização B. Confira em **Dispositivos** onde está o equipamento antes de configurar.

## Criar ou editar o canal

Na lista, os ícones de ação à direita são, na ordem: **editar** (folha com lápis), **copiar** (duas folhas), **excluir** (lixeira).

- Canal novo → botão **Adicionar**
- Canal existente → ícone de **editar**

!!! danger "Não use o botão copiar para editar"
    O botão de copiar abre um diálogo intitulado "Canal de encaminhamento de cópia" e **cria um canal novo** ao confirmar. Dois canais publicando no mesmo path se derrubam mutuamente, gerando reconexão a cada poucos segundos. Se isso já aconteceu, apague as cópias.

## Campos

| Campo | Valor | Por quê |
|---|---|---|
| Nome do canal | livre | Use algo identificável, não o timestamp padrão |
| Tipo | **RTMP** | Mais rodado. RTSP também funciona e poupa uma conversão |
| Endereço do servidor | `rtmp://bore.pub:34055/live/m4td` | Host e porta do seu túnel |
| Nome do dispositivo | o que vai voar | Aeronave ou dock |
| Fonte de transmissão | Carga-zoom / wide / IV | Wide para área ampla, zoom para detalhe |
| Qualidade do vídeo | **fixa**, não "Automático" | Ver nota abaixo |

Confirme e verifique se o toggle **Status do canal** está azul (ligado).

!!! tip "Evite 'Automático' na qualidade"
    No modo automático a resolução muda conforme a banda disponível. Quando isso acontece no meio da transmissão, o `cv2.VideoCapture` normalmente perde a conexão ou passa a devolver quadros corrompidos. Resolução estável vale mais que qualidade máxima para visão computacional.

## Colunas da lista

| Coluna | O que observar |
|---|---|
| Status de transmissão | "Transmissão ao vivo" = publicando; "Não está transmitindo" = parado |
| Status do dispositivo | Precisa estar **Online**. Offline significa equipamento desligado |
| Status do canal | Toggle azul = habilitado |

## Forçar reconexão

Depois de mudar o endereço, ou quando o túnel gerar porta nova:

1. Desligue o toggle **Status do canal**
2. Espere 5 segundos
3. Ligue novamente

A DJI refaz a conexão em poucos segundos.

→ [Próximo: captura no OpenCV](04-captura.md)
