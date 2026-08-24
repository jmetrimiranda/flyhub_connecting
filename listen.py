import socket
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("0.0.0.0", 1935))
s.listen(5)
print("escutando na 1935 — aguardando conexao externa...")
while True:
    conn, addr = s.accept()
    print(">>> CONEXAO RECEBIDA DE", addr)
    conn.close()