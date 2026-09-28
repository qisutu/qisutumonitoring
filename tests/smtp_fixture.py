"""Local-only SMTP fixture. Never forwards messages or connects to remote hosts."""
import base64
import socketserver
import threading


class SMTPFixture(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, context=None, implicit_tls=False, auth=None):
        self.context, self.implicit_tls, self.auth = context, implicit_tls, auth
        self.messages, self.commands, self.reject = [], [], {}
        self.drop_after_data = False
        super().__init__(('127.0.0.1', 0), SMTPHandler)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def get_request(self):
        sock, peer = super().get_request()
        sock.settimeout(10)
        if self.implicit_tls:
            try:
                sock = self.context.wrap_socket(sock, server_side=True)
            except Exception:
                sock.close()
                raise OSError('Test TLS handshake failed')
        return sock, peer

    def close(self):
        self.shutdown(); self.server_close(); self.thread.join(2)


class SMTPHandler(socketserver.StreamRequestHandler):
    def finish(self):
        try:
            super().finish()
        finally:
            self.connection.close()

    def reply(self, line):
        self.wfile.write(line.encode('ascii')+b'\r\n'); self.wfile.flush()

    def handle(self):
        server = self.server
        recipient = ''
        secure = server.implicit_tls
        authenticated = server.auth is None
        self.reply('220 localhost SMTP test')
        try:
            while True:
                line = self.rfile.readline(8192)
                if not line:
                    return
                command, _, arg = line.decode('ascii', errors='replace').strip().partition(' ')
                command = command.upper(); server.commands.append(command)
                if command in ('EHLO', 'HELO'):
                    self.reply('250-localhost')
                    if server.context and not secure:
                        self.reply('250-STARTTLS')
                    if server.auth:
                        self.reply('250-AUTH PLAIN')
                    self.reply('250 SIZE 100000')
                elif command == 'STARTTLS' and server.context:
                    self.reply('220 Begin TLS')
                    self.connection = server.context.wrap_socket(self.connection, server_side=True)
                    self.rfile = self.connection.makefile('rb')
                    self.wfile = self.connection.makefile('wb')
                    secure = True
                elif command == 'AUTH':
                    mechanism, _, encoded = arg.partition(' ')
                    decoded = base64.b64decode(encoded).split(b'\0')
                    authenticated = mechanism=='PLAIN' and len(decoded)==3 and tuple(x.decode() for x in decoded[1:])==server.auth
                    self.reply('235 Authenticated' if authenticated else '535 Authentication failed')
                elif command == 'MAIL':
                    self.reply('250 Sender accepted' if authenticated else '530 Authenticate first')
                elif command == 'RCPT':
                    recipient = arg.split('<', 1)[1].split('>', 1)[0]
                    codes = server.reject.get(recipient, [])
                    code = codes.pop(0) if codes else 250
                    self.reply(str(code)+' Recipient result')
                elif command == 'DATA':
                    self.reply('354 Send data')
                    content = []
                    while True:
                        line = self.rfile.readline(100000)
                        if not line:
                            return
                        if line == b'.\r\n':
                            break
                        content.append(line[1:] if line.startswith(b'..') else line)
                    server.messages.append((recipient, b''.join(content)))
                    if server.drop_after_data:
                        return
                    self.reply('250 Message accepted')
                elif command == 'QUIT':
                    self.reply('221 Bye'); return
                elif command in ('RSET', 'NOOP'):
                    self.reply('250 OK')
                else:
                    self.reply('500 Unsupported')
        except (OSError, ValueError):
            return
