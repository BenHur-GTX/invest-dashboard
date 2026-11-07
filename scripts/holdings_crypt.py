#!/usr/bin/env python3
"""보유 내역 암호화 (RSA-OAEP-256 + AES-GCM). 공개키로 암호화 → 브라우저가 개인키로 복호화.
  keygen <dir>                       : private.pem / public.pem 생성 (개인키는 Ben 기기에만)
  encrypt <public.pem> <in.json> <out.enc.json>
"""
import base64, json, os, sys
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
b64 = lambda b: base64.b64encode(b).decode()
cmd = sys.argv[1]
if cmd == "keygen":
    d = sys.argv[2]; k = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    open(os.path.join(d, "private.pem"), "wb").write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    open(os.path.join(d, "public.pem"), "wb").write(k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
elif cmd == "encrypt":
    pub = serialization.load_pem_public_key(open(sys.argv[2], "rb").read())
    pt = open(sys.argv[3], "rb").read(); json.loads(pt)
    key = AESGCM.generate_key(256); iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, pt, None)
    ek = pub.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    json.dump({"alg": "RSA-OAEP-256+A256GCM", "ek": b64(ek), "iv": b64(iv), "ct": b64(ct)}, open(sys.argv[4], "w"))
