import pytest

from capsule.errors import CapsuleError
from capsule.units import size, to_mib


def test_bare_numbers_are_gib_and_units_are_normalised():
    assert size("8", "ram") == "8GiB"
    assert size("512MB", "ram") == "512MiB"
    assert size("4G", "ram") == "4GiB"


def test_to_mib():
    assert to_mib("8GiB") == 8192
    assert to_mib("512MiB") == 512
    assert to_mib("garbage") == 0


def test_invalid_size_is_a_friendly_error():
    with pytest.raises(CapsuleError) as error:
        size("lots", "ram")
    assert "8GiB" in (error.value.hint or "")
