# Git Credential Relay

`git-credential-relay` is a service that exposes the local Git `credential.helper` over a UNIX domain socket.

The socket can be forwarded over SSH, allowing `git` commands on the remote host to leverage credentials stored with a local credential helper.


> [!IMPORTANT]  
> Forwarded UNIX domain sockets are advantageous in that they are by default only accessible by the login user and root (per the SSH `StreamLocalBindMask` option), unlike a TCP socket which could be accessed by any user on the remote server.
>
> Unfortunately SSH's support for forwarded UNIX domain sockets is hampered by its inability to reuse the same socket file on the remote side ([bug 2601](https://bugzilla.mindrot.org/show_bug.cgi?id=2601)). You must `unlink /tmp/git-credential-relay.sock` between uses.


For example:

    uv run main.py
    ssh -R '/tmp/git-credential-relay.sock:$HOME/.cache/git-credential-relay/local.sock' \
        user@server

On the remote server, configure Git to pass credential requests over the socket:

    git config --global credential.helper \
    '!f(){ op=${1:-get}; { printf "op=%s\n" "$op"; cat; } | socat -t 60 - UNIX-CONNECT:/tmp/git-credential-relay.sock; }; f'

You can test this out by sending a request for GitHub's credential:

    git credential fill <<EOF
    protocol=https
    host=github.com

    EOF

The relay server asks for permission locally before returning credentials. For security, the remote is not allowed to erase credentials.
