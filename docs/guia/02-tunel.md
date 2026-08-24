# 2. Túnel público

Dá à nuvem da DJI um endereço alcançável que aponta para o seu MediaMTX.

**Onde:** no mesmo servidor, terminal separado.

!!! tip "Pule esta etapa se tiver IP público"
    Em VM com IP público e porta 1935 liberada no firewall, use o IP direto e vá para a [etapa 3](03-flighthub.md).

## bore (recomendado para começar)

Sem conta, sem cartão, um binário.

```bash
cd ~
URL=$(curl -s https://api.github.com/repos/ekzhang/bore/releases/latest \
  | grep browser_download_url | grep x86_64-unknown-linux-musl | cut -d '"' -f 4)
curl -sL "$URL" | tar xz
sudo mv bore /usr/local/bin/
bore --version
```

Abra o túnel:

```bash
bore local 1935 --to bore.pub
```

Saída:

```
INFO bore_cli::client: connected to server remote_port=34055
INFO bore_cli::client: listening at bore.pub:34055
```

**Anote host e porta.** Deixe o terminal aberto — fechar derruba o túnel.

## playit.gg (alternativa mais estável)

Se o `bore.pub` estiver fora do ar ou instável:

```bash
curl -SsL https://playit-cloud.github.io/ppa/key.gpg | sudo apt-key add -
sudo curl -SsL -o /etc/apt/sources.list.d/playit-cloud.list \
  https://playit-cloud.github.io/ppa/playit-cloud.list
sudo apt update && sudo apt install -y playit
playit
```

O agente imprime uma URL de ativação. Abra no navegador, crie um túnel TCP para a porta 1935 e ele fornece um endereço persistente.

## Lendo os logs do túnel

Durante operação normal você verá:

```
INFO proxy{...}: new connection
```

Uma conexão que abre e fica é o correto.

| Padrão | Significado |
|---|---|
| `new connection` seguido de `connection exited` em segundos | Nada escutando na 1935, ou o MediaMTX rejeitou |
| `Broken pipe (os error 32)` | Publisher derrubado por outro — canais duplicados |
| `new connection` persistente | Funcionando |

## Limitações do túnel gratuito

- O endereço muda a cada reinício do processo
- Codespaces hiberna após ~30 min ocioso, derrubando o túnel
- Sem criptografia no relay público
- Sem SLA

Ao trocar o endereço, você precisa reeditar o canal no FlightHub.

→ [Próximo: canal no FlightHub](03-flighthub.md)
