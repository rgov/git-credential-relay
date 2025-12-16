#!/usr/bin/env python3
import os
import socket
import struct
import subprocess
import sys
import traceback

import psutil


SOCK = os.path.expanduser('~/.cache/git-credential-relay/local.sock')


# Constants required for getting the peer's PID
SOL_LOCAL = 0
LOCAL_PEERPID = 2
SO_PEERCRED = 17


def get_peer_pid(conn: socket.socket) -> int | None:
    try:
        if sys.platform == 'darwin':
            data = conn.getsockopt(SOL_LOCAL, LOCAL_PEERPID, 4)
            return struct.unpack('i', data)[0]
        elif sys.platform == 'linux':
            data = conn.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, 12)
            pid, _, _ = struct.unpack('iii', data)
            return pid
    except OSError:
        pass
    return None


def get_peer_info(conn: socket.socket) -> str:
    pid = get_peer_pid(conn)
    if pid is None:
        return '?'
    try:
        name = psutil.Process(pid).name()
    except psutil.NoSuchProcess:
        name = '?'
    return f'{name} (pid {pid})'


def read_kv(stream: socket.SocketIO) -> dict[str, str]:
    kv: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            break
        s = line.decode('utf-8', 'replace').rstrip('\n')
        if s == '':
            break
        k, _, v = s.partition('=')
        kv[k] = v
    return kv


def write_close_kv(stream: socket.SocketIO, kv: dict[str, str]) -> None:
    for k, v in kv.items():
        stream.write(f'{k}={v}\n'.encode())
    stream.write(b'\n')
    stream.flush()
    stream.close()


def git_credential_fill(req: dict[str, str]) -> dict[str, str]:
    p = subprocess.run(
        ['git', 'credential', 'fill'],
        input=('\n'.join(f'{k}={v}' for k, v in req.items()) + '\n\n').encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    resp: dict[str, str] = {}
    for line in p.stdout.splitlines():
        s = line.decode('utf-8', 'replace')
        k, _, v = s.partition('=')
        if k:
            resp[k] = v

    return resp


def git_credential_approve(req: dict[str, str]) -> None:
    subprocess.run(
        ['git', 'credential', 'approve'],
        input=('\n'.join(f'{k}={v}' for k, v in req.items()) + '\n\n').encode(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def confirm_get(req: dict[str, str], peer: str) -> bool:
    proto = req.get('protocol', '?')
    host = req.get('host', '?')
    path = req.get('path', '')
    username = req.get('username', '')

    target = f'{proto}://'
    if username:
        target += f'{username}@'
    target += f'{host}/{path}'.rstrip('/')

    print(f'\n[{peer}] requested Git credentials for: {target}')
    ans = input('Allow? [y/N] ')
    return ans.strip().lower() in {'y', 'yes'}


def main() -> None:
    os.makedirs(os.path.dirname(SOCK), exist_ok=True)
    try:
        os.unlink(SOCK)
    except FileNotFoundError:
        pass

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old_umask = os.umask(0o177)
    try:
        srv.bind(SOCK)
    finally:
        os.umask(old_umask)

    srv.listen(16)

    print('Listening for Git credential requests. Forward the socket with:')
    print(f'  ssh -R /tmp/git-credential-relay.sock:{SOCK} ...')
    print('Use ~C to forward the socket over an existing connection.')

    while True:
        conn, _ = srv.accept()
        with conn:
            f = conn.makefile('rwb', buffering=0)
            try:
                peer = get_peer_info(conn)
                req = read_kv(f)
                op = req.pop('op', 'get')

                if op == 'erase':
                    write_close_kv(f, {'error': 'erase disabled'})
                    continue

                if op == 'get':
                    if not confirm_get(req, peer):
                        write_close_kv(f, {'error': 'user denied'})
                        continue
                    write_close_kv(f, git_credential_fill(req))
                    continue

                if op == 'store':
                    git_credential_approve(req)
                    write_close_kv(f, {})
                    continue

                write_close_kv(f, {'error': f'unknown op: {op}'})
            except Exception:
                traceback.print_exc()
                write_close_kv(f, {'error': 'internal server error'})


if __name__ == '__main__':
    main()
