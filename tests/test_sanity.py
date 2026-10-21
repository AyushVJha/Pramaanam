"""M0: package installs and imports cleanly. Real tests for extraction/resolver land in M1+."""

import pramaan


def test_package_importable():
    assert pramaan is not None
