# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""HTTPS for the Beach: a certificate the keeper provides, or one made here, offline.

Nothing here contacts the network, and nothing beyond the standard library is needed: the RSA keys
and the X.509 certificates are written directly (DER), the way `openssl req -x509` would.

What gets made, in `$AI_BEACH_DATA/tls/`:

- `beach-ca.pem`: a small certificate authority for this Beach only. This is the one file a
  browser or phone is told to trust, once. It is limited by X.509 name constraints to this
  computer's names and to private network addresses (127.x, 10.x, 172.16-31.x, 192.168.x,
  100.64-127.x, and IPv6 ::1 and fd00::/8), so even if its key leaked it couldn't vouch for any
  public website.
- `beach-ca.key`: its private key (readable only by you).
- `beach.pem` / `beach.key`: the Beach's own certificate, signed by the CA, naming `localhost`,
  127.0.0.1, ::1, this computer's name, the host in the keeper's `link_base` setting, and any
  `https_names`. When those change (a new address), a new one is made at the next start, still
  signed by the same CA, so nothing needs trusting again unless a new name falls outside the CA's
  limits (a new DNS name, or a public address).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
import os
import secrets
import socket
from pathlib import Path
from urllib.parse import urlparse

PRIVATE_NETS = ["127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
                "::1/128", "fd00::/8"]
CA_DAYS = 3650
LEAF_DAYS = 820          # Apple platforms refuse server certificates valid for more than 825 days
RENEW_DAYS = 30

# -------------------------------------------------------------------------------- DER, minimal


def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag: int, body: bytes) -> bytes:
    return bytes([tag]) + _len(len(body)) + body


def _int(n: int) -> bytes:
    b = n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big")   # room for a leading 0: always positive
    return _tlv(0x02, b)


def _seq(*parts: bytes) -> bytes:
    return _tlv(0x30, b"".join(parts))


def _set(*parts: bytes) -> bytes:
    return _tlv(0x31, b"".join(parts))


def _oid(dotted: str) -> bytes:
    nums = [int(x) for x in dotted.split(".")]
    out = bytearray([40 * nums[0] + nums[1]])
    for n in nums[2:]:
        chunk = [n & 0x7F]
        n >>= 7
        while n:
            chunk.append(0x80 | (n & 0x7F))
            n >>= 7
        out += bytes(reversed(chunk))
    return _tlv(0x06, bytes(out))


def _bits(data: bytes, unused: int = 0) -> bytes:
    return _tlv(0x03, bytes([unused]) + data)


def _octets(data: bytes) -> bytes:
    return _tlv(0x04, data)


def _utf8(s: str) -> bytes:
    return _tlv(0x0C, s.encode())


def _time(t: dt.datetime) -> bytes:
    if t.year < 2050:
        return _tlv(0x17, t.strftime("%y%m%d%H%M%SZ").encode())
    return _tlv(0x18, t.strftime("%Y%m%d%H%M%SZ").encode())


NULL = b"\x05\x00"
TRUE = b"\x01\x01\xff"
RSA_ENCRYPTION = "1.2.840.113549.1.1.1"
SHA256_WITH_RSA = "1.2.840.113549.1.1.11"
SHA256 = "2.16.840.1.101.3.4.2.1"


def _pem(kind: str, der: bytes) -> str:
    import base64
    b = base64.b64encode(der).decode()
    return f"-----BEGIN {kind}-----\n" + "\n".join(b[i:i + 64] for i in range(0, len(b), 64)) + f"\n-----END {kind}-----\n"


# ------------------------------------------------------------------------------------- RSA

_SMALL_PRIMES = [p for p in range(3, 2000) if all(p % q for q in range(2, int(p ** 0.5) + 1))]


def _probably_prime(n: int, rounds: int = 40) -> bool:
    if n < 2:
        return False
    for p in _SMALL_PRIMES:
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        a = 2 + secrets.randbelow(n - 3)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits: int, e: int) -> int:
    while True:
        n = secrets.randbits(bits) | (3 << (bits - 2)) | 1      # top two bits set: n*m has 2*bits bits
        if (n - 1) % e and _probably_prime(n):
            return n


class RSAKey:
    def __init__(self, n: int, e: int, d: int, p: int, q: int):
        self.n, self.e, self.d, self.p, self.q = n, e, d, p, q

    @classmethod
    def generate(cls, bits: int = 2048) -> "RSAKey":
        e = 65537
        while True:
            p, q = _prime(bits // 2, e), _prime(bits // 2, e)
            if p != q and (p * q).bit_length() == bits:
                break
        d = pow(e, -1, (p - 1) * (q - 1))
        return cls(p * q, e, d, p, q)

    def private_der(self) -> bytes:      # PKCS#1 RSAPrivateKey
        p, q, d = self.p, self.q, self.d
        return _seq(_int(0), _int(self.n), _int(self.e), _int(d), _int(p), _int(q),
                    _int(d % (p - 1)), _int(d % (q - 1)), _int(pow(q, -1, p)))

    def public_info(self) -> bytes:      # SubjectPublicKeyInfo
        return _seq(_seq(_oid(RSA_ENCRYPTION), NULL), _bits(_seq(_int(self.n), _int(self.e))))

    def key_id(self) -> bytes:
        return hashlib.sha1(_seq(_int(self.n), _int(self.e))).digest()

    def sign(self, data: bytes) -> bytes:   # RSASSA-PKCS1-v1_5 with SHA-256
        k = (self.n.bit_length() + 7) // 8
        info = _seq(_seq(_oid(SHA256), NULL), _octets(hashlib.sha256(data).digest()))
        em = b"\x00\x01" + b"\xff" * (k - len(info) - 3) + b"\x00" + info
        m = int.from_bytes(em, "big")
        # Chinese remainder theorem: the same result as pow(m, d, n), several times faster.
        p, q = self.p, self.q
        m1, m2 = pow(m, self.d % (p - 1), p), pow(m, self.d % (q - 1), q)
        s = m2 + q * ((pow(q, -1, p) * (m1 - m2)) % p)
        assert pow(s, self.e, self.n) == m
        return s.to_bytes(k, "big")

    @classmethod
    def from_der(cls, der: bytes) -> "RSAKey":
        ints, i = [], 1 + _hdr_len(der, 1)            # inside the outer SEQUENCE
        while i < len(der):
            assert der[i] == 0x02
            i += 1
            n, used = _read_len(der, i)
            i += used
            ints.append(int.from_bytes(der[i:i + n], "big"))
            i += n
        _, n, e, d, p, q = ints[:6]
        return cls(n, e, d, p, q)


def _read_len(b: bytes, i: int) -> tuple[int, int]:
    if b[i] < 0x80:
        return b[i], 1
    k = b[i] & 0x7F
    return int.from_bytes(b[i + 1:i + 1 + k], "big"), 1 + k


def _hdr_len(b: bytes, i: int) -> int:
    return _read_len(b, i)[1]


def _unpem(text: str) -> bytes:
    import base64
    body = "".join(line for line in text.splitlines() if line and not line.startswith("-----"))
    return base64.b64decode(body)


# ----------------------------------------------------------------------------- certificates

def _name(cn: str) -> bytes:
    return _seq(_set(_seq(_oid("2.5.4.10"), _utf8("AI Beach"))), _set(_seq(_oid("2.5.4.3"), _utf8(cn))))


def _ext(oid: str, value: bytes, critical: bool = False) -> bytes:
    return _seq(_oid(oid), TRUE if critical else b"", _octets(value))


def _general_names(names: list[str]) -> bytes:
    out = b""
    for n in names:
        try:
            out += _tlv(0x87, ipaddress.ip_address(n).packed)       # [7] iPAddress
        except ValueError:
            out += _tlv(0x82, n.encode("ascii"))                     # [2] dNSName
    return out


def _subtrees(dns: list[str], nets: list[str]) -> bytes:
    trees = [_seq(_tlv(0x82, d.encode("ascii"))) for d in dns]
    for net in nets:
        nw = ipaddress.ip_network(net)
        trees.append(_seq(_tlv(0x87, nw.network_address.packed + nw.netmask.packed)))
    return _tlv(0xA0, b"".join(trees))                              # [0] permittedSubtrees


def _certificate(subject_cn: str, key: RSAKey, issuer_cn: str, issuer: RSAKey, days: int,
                 extensions: list[bytes]) -> bytes:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    tbs = _seq(
        _tlv(0xA0, _int(2)),                                         # v3
        _int(secrets.randbits(127) | 1),
        _seq(_oid(SHA256_WITH_RSA), NULL),
        _name(issuer_cn),
        _seq(_time(now - dt.timedelta(hours=1)), _time(now + dt.timedelta(days=days))),
        _name(subject_cn),
        key.public_info(),
        _tlv(0xA3, _seq(*extensions)),
    )
    return _seq(tbs, _seq(_oid(SHA256_WITH_RSA), NULL), _bits(issuer.sign(tbs)))


def ca_name() -> str:
    return f"AI Beach local CA ({socket.gethostname() or 'this computer'})"


def make_ca(dns: list[str], nets: list[str]) -> tuple[RSAKey, bytes]:
    key = RSAKey.generate()
    der = _certificate(ca_name(), key, ca_name(), key, CA_DAYS, [
        _ext("2.5.29.19", _seq(TRUE, _int(0)), critical=True),       # basicConstraints CA, pathLen 0
        _ext("2.5.29.15", _bits(b"\x06", 1), critical=True),         # keyUsage keyCertSign, cRLSign
        _ext("2.5.29.30", _seq(_subtrees(dns, nets)), critical=True),  # nameConstraints
        _ext("2.5.29.14", _octets(key.key_id())),                    # subjectKeyIdentifier
    ])
    return key, der


def make_leaf(names: list[str], ca_key: RSAKey, ca_cn: str) -> tuple[RSAKey, bytes]:
    key = RSAKey.generate()
    der = _certificate(names[0], key, ca_cn, ca_key, LEAF_DAYS, [
        _ext("2.5.29.19", _seq(), critical=True),                    # not a CA
        _ext("2.5.29.15", _bits(b"\xa0", 5), critical=True),         # digitalSignature, keyEncipherment
        _ext("2.5.29.37", _seq(_oid("1.3.6.1.5.5.7.3.1"))),          # extKeyUsage serverAuth
        _ext("2.5.29.17", _seq(_general_names(names))),              # subjectAltName
        _ext("2.5.29.14", _octets(key.key_id())),
        _ext("2.5.29.35", _seq(_tlv(0x80, ca_key.key_id()))),        # authorityKeyIdentifier
    ])
    return key, der


# --------------------------------------------------------------------------------- the Beach

def wanted_names(link_base: str | None, extra: list[str] | None) -> list[str]:
    """The names the Beach's certificate should carry. No lookups: only what's known locally."""
    names = ["localhost", "127.0.0.1", "::1"]
    host = socket.gethostname().strip().lower()
    if host and host != "localhost":
        names += [host] + ([host + ".local"] if "." not in host else [])
    if link_base:
        h = urlparse(link_base).hostname
        if h:
            names.append(h.lower())
    names += [n.strip().lower() for n in (extra or []) if n and n.strip()]
    out = []
    for n in names:
        if n not in out:
            out.append(n)
    return out


def check_name(n: str) -> str:
    n = (n or "").strip().lower()
    try:
        return str(ipaddress.ip_address(n))
    except ValueError:
        pass
    import re
    if not re.match(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$", n):
        raise ValueError(f"'{n}' isn't a host name or IP address")
    return n


def _covered(name: str, dns: list[str], nets: list[str]) -> bool:
    try:
        ip = ipaddress.ip_address(name)
        return any(ip in ipaddress.ip_network(n) for n in nets)
    except ValueError:
        return any(name == d or name.endswith("." + d) for d in dns)


def _write_private(path: Path, text: str) -> None:
    path.write_text(text)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def ensure(data_dir: Path, names: list[str], log=print) -> tuple[Path, Path, Path]:
    """Make (or reuse) the CA and the Beach's certificate. Returns (cert chain, key, CA cert)."""
    d = Path(data_dir) / "tls"
    d.mkdir(parents=True, exist_ok=True)
    meta_path = d / "names.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    ca_pem, ca_key_path = d / "beach-ca.pem", d / "beach-ca.key"
    dns = [n for n in names if not _is_ip(n)]
    if not (ca_pem.exists() and ca_key_path.exists()) or not all(
            _covered(n, meta.get("ca_dns", []), meta.get("ca_nets", [])) for n in names):
        nets = list(PRIVATE_NETS) + [f"{n}/{32 if ':' not in n else 128}" for n in names
                                     if _is_ip(n) and not _covered(n, [], PRIVATE_NETS)]
        log("Making this Beach's certificate authority (once; a few seconds)...")
        ca_key, ca_der = make_ca(dns, nets)
        ca_pem.write_text(_pem("CERTIFICATE", ca_der))
        _write_private(ca_key_path, _pem("RSA PRIVATE KEY", ca_key.private_der()))
        meta = {"ca_dns": dns, "ca_nets": nets, "ca_cn": ca_name(),
                "leaf_names": [], "leaf_until": 0}
        log(f"New: {ca_pem}. Browsers and phones need to trust it once (see the README, \"HTTPS\").")
    leaf_pem, leaf_key_path = d / "beach.pem", d / "beach.key"
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    if (not leaf_pem.exists() or not leaf_key_path.exists() or meta.get("leaf_names") != names
            or meta.get("leaf_until", 0) - now < RENEW_DAYS * 86400):
        ca_key = RSAKey.from_der(_unpem(ca_key_path.read_text()))
        key, der = make_leaf(names, ca_key, meta["ca_cn"])
        leaf_pem.write_text(_pem("CERTIFICATE", der) + ca_pem.read_text())
        _write_private(leaf_key_path, _pem("RSA PRIVATE KEY", key.private_der()))
        meta.update(leaf_names=names, leaf_until=now + LEAF_DAYS * 86400)
        log("Made the Beach's certificate for: " + ", ".join(names))
    meta_path.write_text(json.dumps(meta, indent=1))
    return leaf_pem, leaf_key_path, ca_pem


def _is_ip(n: str) -> bool:
    try:
        ipaddress.ip_address(n)
        return True
    except ValueError:
        return False
