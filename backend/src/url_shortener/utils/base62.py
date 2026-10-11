"""Base62 encoding utilities.

The alphabet is deterministic and ordered as digits, uppercase letters, then
lowercase letters: 0-9, A-Z, a-z. Encoding maps non-negative integers to the
shortest Base62 string for that value. The integer 0 is encoded as "0".
"""

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE = len(ALPHABET)
CHAR_TO_VALUE = {character: index for index, character in enumerate(ALPHABET)}


def encode_base62(value: int) -> str:
    if value < 0:
        raise ValueError("Base62 encoding requires a non-negative integer.")
    if value == 0:
        return ALPHABET[0]

    encoded = ""
    current = value
    while current > 0:
        current, remainder = divmod(current, BASE)
        encoded = ALPHABET[remainder] + encoded
    return encoded


def decode_base62(value: str) -> int:
    if value == "":
        raise ValueError("Base62 decoding requires a non-empty string.")

    decoded = 0
    for character in value:
        if character not in CHAR_TO_VALUE:
            raise ValueError(f"Invalid Base62 character: {character!r}.")
        decoded = decoded * BASE + CHAR_TO_VALUE[character]
    return decoded
