"""Guards the OpenCV pin: 5.0 on Apple silicon crashed in KleidiCV's resize on a long OCR run."""

import cv2


def test_opencv_is_below_4_13():
    major, minor = (int(part) for part in cv2.__version__.split(".")[:2])
    assert (major, minor) < (4, 13), cv2.__version__


def test_opencv_has_no_kleidicv_hal():
    hal_lines = [line for line in cv2.getBuildInformation().splitlines() if "Custom HAL" in line]
    assert hal_lines
    assert not any("kleidicv" in line.lower() for line in hal_lines), hal_lines
