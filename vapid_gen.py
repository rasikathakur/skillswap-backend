import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

def b64url(b):
    return base64.urlsafe_b64encode(b).decode('utf-8').rstrip('=')

# Generate new key pair
private_key = ec.generate_private_key(ec.SECP256R1())
public_key = private_key.public_key()

# Get private key bytes
private_bytes = private_key.private_numbers().private_value.to_bytes(32, byteorder='big')

# Get public key bytes (uncompressed format)
public_bytes = public_key.public_bytes(
    encoding=serialization.Encoding.X962,
    format=serialization.PublicFormat.UncompressedPoint
)

with open("vapid_keys.txt", "w") as f:
    f.write(f"VAPID_PUBLIC_KEY={b64url(public_bytes)}\n")
    f.write(f"VAPID_PRIVATE_KEY={b64url(private_bytes)}\n")
