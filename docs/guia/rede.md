# Por que precisa de túnel

## Direção da conexão

Quando você abre um site, **você** inicia a conexão. O firewall deixa sair e memoriza o caminho de volta. Isso funciona em qualquer rede corporativa.

No encaminhamento do FlightHub é o contrário: o servidor da DJI **liga para você**. Ele precisa de um endereço que exista na internet pública.

Uma máquina em rede corporativa tem IP privado (`10.x`, `172.16–31.x`, `192.168.x`) atrás de NAT. Do lado de fora, ela não existe.

## Diagnóstico rápido

Rode na máquina que pretende usar como servidor:

```bash
# IP local
python -c "import socket;s=socket.socket();s.connect(('8.8.8.8',80));print(s.getsockname()[0])"

# IP público visto pela internet
curl -s https://api.ipify.org; echo
```

| Resultado | Significado |
|---|---|
| Os dois iguais | IP público direto — port forward resolve |
| Diferentes | Atrás de NAT — precisa de túnel ou VM |
| Público começa com `100.64.` | CGNAT do provedor — nem port forward funciona |

## As três saídas

### 1. Túnel reverso (desenvolvimento)

Um cliente abre conexão **de saída** para um relay público, que passa a aceitar conexões de entrada em seu nome.

| Ferramenta | Cartão? | Observação |
|---|---|---|
| **bore** | Não | Um binário, sem conta. Relay público `bore.pub` |
| **playit.gg** | Não | Conta grátis, 4 túneis TCP, mais estável |
| **ngrok** | **Sim** | Exige cartão para endpoints TCP mesmo no plano free |

### 2. VM com IP público (produção)

Azure, AWS, Oracle. Endereço fixo, sem intermediário, sem relay de terceiros no caminho do dado.

### 3. FlightHub On-Premises

Se a organização tiver a versão on-premises, tudo fica dentro da rede e o problema desaparece.

## Considerações de segurança

Um relay público como o `bore.pub` transporta o tráfego **sem criptografia** e por infraestrutura de terceiros. Para validação técnica é aceitável. Para operação contínua com imagem de área industrial, use VM própria.

O path RTMP funciona como credencial de fato: sem conhecer `/live/<sufixo-aleatório>`, ninguém publica nem lê. Gere um sufixo aleatório real:

```bash
echo "live/m4td-$(openssl rand -hex 6)"
```

!!! note "Codespaces e RTMP"
    O encaminhamento de portas nativo do GitHub Codespaces é um proxy HTTPS — passa apenas HTTP. RTMP e RTSP são TCP puro e não atravessam. Por isso o túnel roda **dentro** do Codespace, não no lugar dele.

    A porta 8888 (HLS) é exceção: sendo HTTP, funciona com o forwarding nativo.
