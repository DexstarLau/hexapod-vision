"""Tests for vision/range.py. Standard library plus pytest, no frames, no camera.

The point of testing this before collection starts is that every claim below has
an exact answer known in advance. `apparent_width_px` is the algebraic inverse of
`range_mm`, so a round trip through both must return the distance it started
with -- and it must do so to floating-point precision, not approximately.

WHAT THESE TESTS HAVE POWER OVER
  the geometry, the refusal thresholds, the error propagation, and the module's
  refusal to invent a focal length.

WHAT THEY HAVE NO POWER OVER
  whether a real detector measures `w_px` correctly on a real frame. Nothing
  here touches an image. Lens distortion, motion blur and marker non-planarity
  are systematic, they all move `w_px`, and a test built on synthetic widths
  cannot see any of them. That is what the held-out set is for, and it is said
  here rather than left to be discovered when the first session disagrees.
"""

import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vision.range import (  # noqa: E402
    DETECTION_FLOOR_PX,
    RELIABLE_WIDTH_PX,
    Intrinsics,
    RangeError,
    apparent_width_px,
    load_intrinsics,
    range_error_mm,
    range_mm,
)

# Values chosen to be UNROUND on purpose. A stand-in that is a neat number hides
# an arithmetic error that a ragged one exposes -- 1108.0 and 100.0 would agree
# under several wrong formulas that 1108.4210 and 99.6400 separate.
F_PX = 1108.4210
F_PX_SIGMA = 4.1200
MARKER_MM = 99.6400


@pytest.fixture
def intr():
    return Intrinsics(f_px=F_PX, f_px_sigma=F_PX_SIGMA, image_width_px=1280,
                      source="charuco_a4_landscape, 27 shots",
                      calibrated_on="2026-09-14")


# ---------------------------------------------------------------- the geometry

@pytest.mark.parametrize("distance_mm", [312.5, 500.0, 1000.0, 1873.25, 3000.0])
def test_round_trip_returns_the_distance_it_started_from(intr, distance_mm):
    """Exact inverse, so this is a test of the algebra and not of a tolerance."""
    w = apparent_width_px(intr, MARKER_MM, distance_mm)
    if w < DETECTION_FLOOR_PX:
        pytest.skip("below the floor by construction; covered by its own test")
    est = range_mm(intr, MARKER_MM, w)
    assert est.distance_mm == pytest.approx(distance_mm, rel=1e-12)


def test_range_is_linear_in_focal_length(intr):
    """Doubling f_px doubles Z. This is why a spec-sheet f_px is not usable."""
    a = range_mm(intr, MARKER_MM, 60.0).distance_mm
    twice = Intrinsics(F_PX * 2.0, F_PX_SIGMA, 1280, "x", "2026-09-14")
    b = range_mm(twice, MARKER_MM, 60.0).distance_mm
    assert b == pytest.approx(2.0 * a, rel=1e-12)


def test_range_is_inverse_in_observed_width(intr):
    a = range_mm(intr, MARKER_MM, 40.0).distance_mm
    b = range_mm(intr, MARKER_MM, 80.0).distance_mm
    assert a == pytest.approx(2.0 * b, rel=1e-12)


# ------------------------------------------------------------ the refusals

def test_below_the_detection_floor_it_raises_rather_than_returning_a_number(intr):
    with pytest.raises(RangeError) as exc:
        range_mm(intr, MARKER_MM, DETECTION_FLOOR_PX - 0.001)
    assert "floor" in str(exc.value)


def test_between_the_floor_and_reliable_it_returns_but_labels_it(intr):
    est = range_mm(intr, MARKER_MM, (DETECTION_FLOOR_PX + RELIABLE_WIDTH_PX) / 2.0)
    assert est.status == "marginal"
    assert est.distance_mm > 0.0


def test_at_and_above_the_reliable_width_the_status_is_ok(intr):
    assert range_mm(intr, MARKER_MM, RELIABLE_WIDTH_PX).status == "ok"
    assert range_mm(intr, MARKER_MM, 200.0).status == "ok"


def test_the_boundary_is_inclusive_at_reliable_and_at_the_floor(intr):
    """Stated explicitly because an off-by-one on a threshold is invisible."""
    assert range_mm(intr, MARKER_MM, RELIABLE_WIDTH_PX).status == "ok"
    assert range_mm(intr, MARKER_MM, DETECTION_FLOOR_PX).status == "marginal"


@pytest.mark.parametrize("bad", [0.0, -1.0, None])
def test_a_missing_or_impossible_focal_length_raises(bad):
    with pytest.raises(RangeError):
        Intrinsics(bad, F_PX_SIGMA, 1280, "x", "2026-09-14")


def test_a_missing_focal_length_uncertainty_raises():
    with pytest.raises(RangeError):
        Intrinsics(F_PX, None, 1280, "x", "2026-09-14")


@pytest.mark.parametrize("bad", [0.0, -5.0, None])
def test_a_missing_marker_width_raises(intr, bad):
    with pytest.raises(RangeError):
        range_mm(intr, bad, 60.0)


# --------------------------------------------------------- the error estimate

def test_relative_error_adds_in_quadrature(intr):
    w, sigma_w = 50.0, 0.5
    est = range_mm(intr, MARKER_MM, w, sigma_w)
    expected_rel = math.sqrt((F_PX_SIGMA / F_PX) ** 2 + (sigma_w / w) ** 2)
    assert est.sigma_mm / est.distance_mm == pytest.approx(expected_rel, rel=1e-12)


def test_the_width_term_dominates_at_range(intr):
    """The reason the detection floor exists, asserted rather than asserted-about."""
    near = range_mm(intr, MARKER_MM, 200.0)
    far = range_mm(intr, MARKER_MM, 25.0)
    assert far.sigma_mm / far.distance_mm > 4.0 * (near.sigma_mm / near.distance_mm)


def test_error_scales_with_distance_not_with_pixel_count_alone(intr):
    """sigma is a fixed FRACTION of Z at fixed w, so it grows as Z does."""
    a = range_mm(intr, MARKER_MM, 40.0)
    b = range_mm(intr, 2.0 * MARKER_MM, 40.0)   # twice as wide, twice as far
    assert b.distance_mm == pytest.approx(2.0 * a.distance_mm, rel=1e-12)
    assert b.sigma_mm == pytest.approx(2.0 * a.sigma_mm, rel=1e-12)


def test_a_perfect_calibration_leaves_only_the_width_term(intr):
    exact = Intrinsics(F_PX, 0.0, 1280, "hypothetical", "2026-09-14")
    est = range_mm(exact, MARKER_MM, 50.0, 0.5)
    assert est.sigma_mm / est.distance_mm == pytest.approx(0.5 / 50.0, rel=1e-12)


# ------------------------------------------------------- the calibration file

def test_a_missing_calibration_file_raises_and_says_why(tmp_path):
    with pytest.raises(RangeError) as exc:
        load_intrinsics(tmp_path / "nope.json")
    assert "calibration" in str(exc.value)


def test_an_incomplete_calibration_file_names_what_is_missing(tmp_path):
    p = tmp_path / "cal.json"
    p.write_text(json.dumps({"f_px": F_PX, "image_width_px": 1280}), encoding="utf-8")
    with pytest.raises(RangeError) as exc:
        load_intrinsics(p)
    message = str(exc.value)
    assert "f_px_sigma" in message and "source" in message


def test_a_complete_calibration_file_round_trips(tmp_path):
    p = tmp_path / "cal.json"
    p.write_text(json.dumps({
        "f_px": F_PX, "f_px_sigma": F_PX_SIGMA, "image_width_px": 1280,
        "source": "charuco_a4_landscape, 27 shots",
        "calibrated_on": "2026-09-14",
    }), encoding="utf-8")
    k = load_intrinsics(p)
    assert k.f_px == F_PX and k.f_px_sigma == F_PX_SIGMA


# ------------------------------------------------------------------ planning

def test_the_protocol_planning_table_reproduces_within_its_own_rounding():
    """docs/MP2_collection_protocol.md section 2: 1280x720, f_px ~1108, ~3.7 m at 30 px.

    The protocol's figures are labelled planning-only and are quoted to two
    significant figures, so this asserts agreement AT THAT PRECISION and no
    further. A tighter tolerance would be asserting against a rounding.
    """
    k = Intrinsics(1108.0, 1.0, 1280, "planning table", "n/a")
    reliable = range_mm(k, 100.0, RELIABLE_WIDTH_PX).distance_mm
    assert reliable / 1000.0 == pytest.approx(3.7, abs=0.05)

    floor = 1108.0 * 100.0 / DETECTION_FLOOR_PX
    assert floor / 1000.0 == pytest.approx(5.5, abs=0.05)


def test_apparent_width_refuses_a_nonpositive_distance(intr):
    with pytest.raises(RangeError):
        apparent_width_px(intr, MARKER_MM, 0.0)
