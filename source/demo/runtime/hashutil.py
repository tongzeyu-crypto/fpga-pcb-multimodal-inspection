"""SHA-256 for full Python installs and the board's minimal Python image."""
try:
    from _sha256 import sha256
except ImportError:
    try:
        from _hashlib import openssl_sha256 as sha256
    except ImportError:
        import subprocess

        class sha256:
            def __init__(self, data=b''):
                self.data = bytes(data)

            def update(self, data):
                self.data += bytes(data)

            def hexdigest(self):
                result = subprocess.run(['sha256sum'], input=self.data,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        check=True, timeout=5)
                digest = result.stdout.decode('ascii').split()[0]
                if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                    raise ValueError('invalid sha256sum result')
                return digest
