"""Loopback SSH fixture. Optional Paramiko is for tests only."""
import logging
import socketserver
import subprocess
import threading
import paramiko
logging.getLogger('paramiko').setLevel(logging.CRITICAL)

class SSHFixture(socketserver.ThreadingTCPServer):
 allow_reuse_address=True
 daemon_threads=True
 def __init__(self,output=None,password='Resource test password',client_key=None):
  self.key=paramiko.RSAKey.generate(2048);self.password=password;self.client_key=client_key
  self.output=output;self.auth_attempts=0;self.executions=0
  super().__init__(('127.0.0.1',0),Handler)
  threading.Thread(target=self.serve_forever,daemon=True).start()
 def close(self):self.shutdown();self.server_close()

class Authentication(paramiko.ServerInterface):
 def __init__(self,fixture):self.fixture=fixture;self.event=threading.Event();self.command=None
 def get_allowed_auths(self,username):return 'publickey,password'
 def check_auth_password(self,username,password):
  self.fixture.auth_attempts+=1
  return paramiko.AUTH_SUCCESSFUL if username=='monitor' and password==self.fixture.password else paramiko.AUTH_FAILED
 def check_auth_publickey(self,username,key):
  self.fixture.auth_attempts+=1
  return paramiko.AUTH_SUCCESSFUL if username=='monitor' and self.fixture.client_key and key==self.fixture.client_key else paramiko.AUTH_FAILED
 def check_channel_request(self,kind,chanid):return paramiko.OPEN_SUCCEEDED if kind=='session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
 def check_channel_exec_request(self,channel,command):self.command=command;self.event.set();return True

class Handler(socketserver.BaseRequestHandler):
 def handle(self):
  transport=paramiko.Transport(self.request);transport.add_server_key(self.server.key)
  auth=Authentication(self.server)
  try:
   transport.start_server(server=auth);channel=transport.accept(6)
   if not channel or not auth.event.wait(5):return
   if auth.command!=b'sh -s':channel.send_exit_status(1);return
   script=bytearray();channel.settimeout(8)
   while True:
    chunk=channel.recv(16384)
    if not chunk:break
    script.extend(chunk)
    if len(script)>8192:return
   if b'NETZMONITOR_RESOURCES_1' not in script:return
   self.server.executions+=1
   if self.server.output is None:
    proc=subprocess.run(['sh'],input=bytes(script),capture_output=True,timeout=8)
    content,code=proc.stdout+proc.stderr,proc.returncode
   else:
    content=self.server.output() if callable(self.server.output) else self.server.output
    content=content.encode();code=0
   channel.sendall(content);channel.send_exit_status(code);channel.shutdown_write()
   # Let the client drain output before closing the transport.
   threading.Event().wait(.1)
  except (EOFError,OSError,paramiko.SSHException):pass
  finally:transport.close()
