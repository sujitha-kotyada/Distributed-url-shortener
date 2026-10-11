import pytest

from url_shortener.utils.base62 import decode_base62, encode_base62


@pytest.mark.parametrize(
    ("value", "encoded"),
    [
        (0, "0"),
        (1, "1"),
        (9, "9"),
        (10, "A"),
        (35, "Z"),
        (36, "a"),
        (61, "z"),
        (62, "10"),
        (3843, "zz"),
        (3844, "100"),
        (238327, "zzz"),
    ],
)
def test_encode_base62(value: int, encoded: str) -> None:
    assert encode_base62(value) == encoded


@pytest.mark.parametrize("value", [0, 1, 61, 62, 12345, 987654321])
def test_base62_round_trip(value: int) -> None:
    assert decode_base62(encode_base62(value)) == value


def test_encode_base62_rejects_negative_integer() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        encode_base62(-1)


@pytest.mark.parametrize("value", ["", "abc!", "with space"])
def test_decode_base62_rejects_invalid_input(value: str) -> None:
    with pytest.raises(ValueError):
        decode_base62(value)
