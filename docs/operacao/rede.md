# Rede e acesso remoto

Dois problemas distintos: **a DJI precisa alcançar sua máquina** (entrada) e **você precisa alcançar a máquina de outro lugar** (acesso remoto).

## Entrada: port forward

A nuvem da DJI inicia a conexão RTMP. Sua máquina precisa ser alcançável na porta 1935.

### Confirmar que é possível

```bash
curl -s https://api.ipify.org; echo        # IP público
hostname -I | awk '{print $1}'             # IP local
```

Compare o IP público com o WAN que aparece na administração do roteador.

| Resultado | Significa |
|---|---|
| Iguais | Port forward funciona |
| WAN começa com `100.64.` | **CGNAT** — port forward não resolve |
| Diferentes de outra forma | Há outro roteador no caminho |

Com CGNAT, ligue para o provedor e peça IP público. Costuma ser gratuito ou custar pouco.

### Configurar

📍 **Administração do roteador:**

1. **Reserve o IP local** da máquina no DHCP. Sem isso o IP muda e o encaminhamento quebra
2. Crie uma regra: porta externa **1935** → IP local da máquina, porta **1935**, protocolo TCP

### Testar de fora

Use o celular no **4G**, não no Wi-Fi de casa — de dentro da rede o teste dá falso positivo.

Na máquina:

```bash
nc -l 1935
```

No celular, abra `http://SEU_IP_PUBLICO:1935` no navegador. Se aparecer qualquer coisa no terminal, funcionou.

### IP dinâmico

A maioria dos provedores residenciais troca o IP periodicamente. Quando isso acontece, o FlightHub aponta para o lugar errado e o stream para de chegar.

Solução: DNS dinâmico. Registre um nome no DuckDNS e rode o cliente na máquina:

```bash
mkdir -p ~/duckdns && cd ~/duckdns
cat > duck.sh << 'EOF'
echo url="https://www.duckdns.org/update?domains=SEUNOME&token=SEUTOKEN&ip=" \
  | curl -k -o ~/duckdns/duck.log -K -
EOF
chmod +x duck.sh
(crontab -l 2>/dev/null; echo "*/5 * * * * ~/duckdns/duck.sh >/dev/null 2>&1") | crontab -
```

Depois use o nome em vez do número:

```bash
PUBLIC_HOST=seunome.duckdns.org ./start.sh
```

E no FlightHub: `rtmp://seunome.duckdns.org:1935/live/m4td`

### Firewall local

```bash
sudo ufw status
sudo ufw allow 1935/tcp
```

## Acesso remoto: Tailscale

Para mexer na aplicação de outra máquina — do PC da Samarco, por exemplo — sem abrir porta nenhuma.

O Tailscale cria uma rede privada entre seus dispositivos. Cada um ganha um IP fixo que só você enxerga. Funciona de qualquer lugar, atrás de qualquer NAT, sem configurar firewall.

### Na máquina servidor

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4
```

Anote o IP `100.x.x.x`.

### Na outra máquina

Instale o Tailscale (Linux, Windows ou macOS) e faça login na mesma conta.

A partir daí:

```bash
ssh jorgemetri@100.x.x.x
```

E o painel em `http://100.x.x.x:8080`.

Gratuito até 100 dispositivos.

!!! tip "VS Code Remote-SSH"
    Com o Tailscale ativo, instale a extensão **Remote - SSH** no VS Code da outra máquina e conecte em `jorgemetri@100.x.x.x`.

    Você edita o código do servidor como se fosse local, com terminal integrado. É a forma mais confortável de desenvolver de outro lugar.

### Alternativas

| Opção | Prós | Contras |
|---|---|---|
| **Tailscale** | Sem abrir porta, funciona em qualquer rede | Depende de serviço externo |
| **SSH via port forward** | Sem terceiros | Expõe SSH à internet; exige chave e fail2ban |
| **VPN da empresa** | Governança | Depende da TI |

Se optar por SSH exposto:

```bash
sudo nano /etc/ssh/sshd_config
# PasswordAuthentication no
# PermitRootLogin no
sudo systemctl restart ssh
sudo apt install -y fail2ban
```

E use uma porta alta em vez da 22 no port forward — reduz muito o ruído de varredura automática.

## Banda

O stream chega pela sua internet. Um dock em HD manda 5–8 Mbps.

```bash
speedtest-cli 2>/dev/null || sudo apt install -y speedtest-cli && speedtest-cli
```

O que importa aqui é o **download** — você recebe o vídeo. O upload só importa se alguém for assistir remotamente pelo HLS.

## Segurança

!!! danger "Só a porta 1935 vai para a internet"
    | Porta | Exposição |
    |---|---|
    | 1935 (RTMP) | Internet — a DJI precisa |
    | 8080 (painel) | **Nunca** — sem autenticação |
    | 8554, 8888, 9997 | Rede local apenas |

    `GET /api/pipeline/status` devolve o endereço RTMP completo, e o path do stream é a única credencial do endpoint de publicação.

O path funciona como senha. Gere um aleatório:

```bash
echo "live/m4td-$(openssl rand -hex 6)"
```

E use no `STREAM_PATH`. Sem conhecê-lo, ninguém publica no seu servidor mesmo com a porta aberta.
