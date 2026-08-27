# Solução de problemas

Erros reais encontrados durante a implantação, com causa e correção.

## Método de diagnóstico

Verifique na ordem do fluxo — cada etapa depende da anterior:

```bash
# 1. O servidor está de pé?
docker ps | grep mediamtx

# 2. A API responde?
curl -s localhost:9997/v3/paths/list

# 3. Chegou vídeo?
curl -s localhost:9997/v3/paths/list | python3 -m json.tool

# 4. O que o servidor viu?
docker logs --tail 50 mtx
```

E no terminal do túnel: houve `new connection`?

| Onde parou | Causa provável |
|---|---|
| Nenhuma conexão no túnel | Endereço errado no canal, ou dispositivo offline |
| Conexão no túnel, nada no MediaMTX | Container caído ou porta divergente |
| `opened` seguido de `closed` no MediaMTX | Autenticação ou path recusado |
| `is publishing` mas `items: []` | Consultando path errado |

---

## Rede e túnel

### `new connection` e `connection exited` em segundos

Ninguém escutando na porta local. Confirme `docker ps` e que o túnel aponta para a mesma porta publicada pelo container.

### `connection exited with error err=Broken pipe (os error 32)`

Dois publishers competindo. Nos logs do MediaMTX aparece `closing existing publisher`. Apague os canais duplicados no FlightHub.

### ngrok: `ERR_NGROK_8013`

```
You must add a credit or debit card before you can use TCP endpoints
```

Contas gratuitas do ngrok exigem cartão para endpoints TCP. Use IP público com port forward — ver [rede](rede.md).

---

## MediaMTX

### `curl` retorna vazio

A API vem desabilitada por padrão. Adicione `api: yes` ou `-e MTX_API=yes`.

### `{"status":"error","error":"authentication error"}`

Versões recentes exigem permissões explícitas. Use o bloco `authInternalUsers` da [instalação](../rodar/index.md), incluindo `action: api`.

### `part duration changed ... error in iOS clients`

Aviso benigno. O encoder da DJI tem taxa variável; afeta apenas players iOS nativos.

### `closing existing publisher`

Publisher duplicado. Ver acima.

---

## OpenCV

### `ImportError: libGL.so.1`

Duas variantes do OpenCV instaladas. Ambas fornecem `cv2` e uma sobrescreve a outra.

```bash
python3 -m pip uninstall -y opencv-python opencv-python-headless opencv-contrib-python
python3 -m pip install opencv-python-headless
python3 -c "import cv2; print(cv2.__version__)"
```

Em último caso, instale a biblioteca de sistema:

```bash
sudo apt-get update && sudo apt-get install -y libgl1 libglib2.0-0
```

### `method DESCRIBE failed: 404 (Not Found)`

Não há publisher ativo no path. Ou o stream caiu momentaneamente (normal durante reconexão), ou o path do script difere do configurado no canal.

Confira o nome exato:

```bash
curl -s localhost:9997/v3/paths/list | python3 -c "import sys,json;[print(i['name']) for i in json.load(sys.stdin)['items']]"
```

### `backend is generally available but can't be used to capture by name`

Aviso que acompanha o 404 acima. Mesma causa.

### `reconectando...` em ciclo

Se alterna entre quadros e reconexões, é o publisher duplicado. Se nunca conecta, o stream não existe.

---

## FlightHub

### Status do dispositivo: Offline

Equipamento desligado. Nada será encaminhado até ligar — independente de qualquer configuração.

### Canal habilitado mas "Não está transmitindo"

1. O endereço ainda é o exemplo `rtmp://a.rtmp.youtube.com/live2/password`
2. Dispositivo offline
3. Servidor inalcançável — nenhuma conexão registrada no túnel
4. Túnel gerou porta nova após reinício

### Canal duplicado sem querer

O ícone de copiar abre um diálogo intitulado "Canal de encaminhamento de **cópia**" e cria um canal novo. Para editar, use o ícone de lápis.

### Configurei mas o dispositivo não aparece no dropdown

Organização errada. Dispositivos e canais são isolados por organização.

---

## Terminal

### Heredoc sai embaralhado

Colar blocos com `cat > arquivo << 'EOF'` em terminal web frequentemente corrompe o conteúdo. Sintoma: linhas sobrepostas, código truncado.

Crie o arquivo pelo editor (clique direito na árvore → New File) e cole no editor, não no terminal.

### `bash: pip: Permission denied`

Antivírus corporativo bloqueando o executável. Use o módulo:

```bash
python -m pip install -r requirements.txt
```

---

## Reinício limpo

Quando nada faz sentido, recomece do zero:

```bash
docker rm -f mtx
pkill bore
docker run -d --name mtx --restart unless-stopped \
  -v $PWD/mediamtx.yml:/mediamtx.yml \
  -p 1935:1935 -p 8554:8554 -p 8888:8888 -p 9997:9997 \
  bluenviron/mediamtx:latest
bore local 1935 --to bore.pub
```

Atualize o endereço no FlightHub com a porta nova e religue o toggle do canal.
