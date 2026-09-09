"""Range from a marker of known size, and the error on it.

    Z = f_px * W_mm / w_px

`W_mm` is the MEASURED marker width, `w_px` its observed width in the image, and
`f_px` the focal length in pixels from calibration. `docs/MP2_collection_protocol.md`
section 2 derives it.

WHY THIS EXISTS BEFORE ANY FRAME DOES
-------------------------------------
Every input to this file is a number. None of it needs a photograph, a camera, or
a calibrated intrinsic to be written and tested -- the geometry can be exercised
against synthetic values whose exact answer is known in advance. Writing it after
collection would mean discovering its refusal thresholds on real data, when a
refused frame is one that has already cost a session.

WHAT IT REFUSES TO DO, AND WHY EACH REFUSAL IS DELIBERATE
----------------------------------------------------------
1.  **No intrinsic is ever hard-coded here.** `f_px` is read from a calibration
    file. The protocol's own table of `f_px` values is labelled *planning figures
    only*, and a field of view off a spec sheet is routinely 10-15 degrees wrong.
    Range is LINEAR in `f_px`, so a spec-sheet focal length is a range estimate
    with a silent 20% error.

    This also survives the camera changing. The laptop webcam is not the robot's
    camera; a pipeline that bakes in today's intrinsics is rewritten when the
    hardware arrives, and one that reads them from a file is not.

2.  **A missing value stops the calculation. It never gets a default.** A default
    focal length produces a plausible number from an uncalibrated camera, and a
    plausible number is worse than an exception because nothing downstream can
    tell it apart from a real one.

3.  **Below the detection floor the answer is refused, not returned small.** The
    protocol puts reliable detection at about 30 px of marker width and says it
    falls apart below 20. Between those, an estimate is returned CARRYING ITS
    STATUS; below 20 it is refused. A far-range reading that is quietly garbage
    is the failure mode this guards.

WHAT THE ERROR ESTIMATE HAS POWER OVER, AND WHAT IT DOES NOT
-------------------------------------------------------------
`range_error_mm` propagates two inputs: the uncertainty on the observed width in
pixels, and the uncertainty on `f_px` from calibration. Both enter as relative
errors and add in quadrature.

It has NO power over: lens distortion not removed before measuring `w_px`,
marker non-planarity, motion blur widening the apparent marker, or the marker
being measured across a different pair of corners than the one `W_mm` describes.
Those are systematic and this function cannot see them. They are what the
held-out set in `data/` is for.
"""

import json
import math
from pathlib import Path

__all__ = [
    "Intrinsics",
    "RangeEstimate",
    "load_intrinsics",
    "range_mm",
    "range_error_mm",
    "apparent_width_px",
    "DETECTION_FLOOR_PX",
    "RELIABLE_WIDTH_PX",
    "RangeError",
]

# From docs/MP2_collection_protocol.md section 2. Detection of a 4x4 marker needs
# roughly 30 px of width to be reliable and falls apart below about 20.
RELIABLE_WIDTH_PX = 30.0
DETECTION_FLOOR_PX = 20.0


class RangeError(Exception):
    """Raised rather than returning a number that cannot be trusted."""


class Intrinsics:
    """Camera intrinsics as calibration produced them. No defaults, ever."""

    __slots__ = ("f_px", "f_px_sigma", "image_width_px", "source", "calibrated_on")

    def __init__(self, f_px, f_px_sigma, image_width_px, source, calibrated_on):
        if f_px is None or f_px <= 0.0:
            raise RangeError(
                "f_px is %r. Calibration did not supply a focal length, and this "
                "module does not invent one: range is linear in f_px, so a "
                "stand-in produces a plausible distance from an uncalibrated "
                "camera." % (f_px,))
        if f_px_sigma is None or f_px_sigma < 0.0:
            raise RangeError(
                "f_px_sigma is %r. Calibration reports an uncertainty on the "
                "focal length; without it range_error_mm cannot be computed and "
                "a range without an error bar is not a measurement."
                % (f_px_sigma,))
        self.f_px = float(f_px)
        self.f_px_sigma = float(f_px_sigma)
        self.image_width_px = image_width_px
        self.source = source
        self.calibrated_on = calibrated_on

    def __repr__(self):
        return "Intrinsics(f_px=%.4f +/- %.4f, from %r, %s)" % (
            self.f_px, self.f_px_sigma, self.source, self.calibrated_on)


class RangeEstimate:
    """A distance, its error bar, and whether it may be used.

    `status` is one of:
      "ok"        -- observed width at or above RELIABLE_WIDTH_PX
      "marginal"  -- between DETECTION_FLOOR_PX and RELIABLE_WIDTH_PX. The number
                     is returned and MUST be reported carrying this label.
    Below the floor nothing is returned; `range_mm` raises.
    """

    __slots__ = ("distance_mm", "sigma_mm", "status", "observed_width_px")

    def __init__(self, distance_mm, sigma_mm, status, observed_width_px):
        self.distance_mm = distance_mm
        self.sigma_mm = sigma_mm
        self.status = status
        self.observed_width_px = observed_width_px

    def __repr__(self):
        return "RangeEstimate(%.4f +/- %.4f mm, %s, w=%.4f px)" % (
            self.distance_mm, self.sigma_mm, self.status, self.observed_width_px)


def load_intrinsics(path):
    """Read calibration from JSON. Every required key must be present.

    Expected shape:

        {
          "f_px": 1108.4210,
          "f_px_sigma": 4.1200,
          "image_width_px": 1280,
          "source": "charuco_a4_landscape, 27 shots",
          "calibrated_on": "2026-09-14"
        }
    """
    path = Path(path)
    if not path.exists():
        raise RangeError(
            "no calibration file at %s. The protocol requires calibration before "
            "session 1; a field of view off a spec sheet is not a measurement."
            % path)
    data = json.loads(path.read_text(encoding="utf-8"))

    required = ("f_px", "f_px_sigma", "image_width_px", "source", "calibrated_on")
    missing = [k for k in required if k not in data]
    if missing:
        raise RangeError(
            "calibration file %s is missing %s. Nothing is defaulted."
            % (path, ", ".join(missing)))

    return Intrinsics(
        f_px=data["f_px"],
        f_px_sigma=data["f_px_sigma"],
        image_width_px=data["image_width_px"],
        source=data["source"],
        calibrated_on=data["calibrated_on"],
    )


def _check_width(observed_width_px):
    if observed_width_px is None or observed_width_px <= 0.0:
        raise RangeError("observed width is %r px" % (observed_width_px,))
    if observed_width_px < DETECTION_FLOOR_PX:
        raise RangeError(
            "observed width %.4f px is below the %.1f px detection floor. The "
            "protocol puts reliable detection at %.1f px and says it falls apart "
            "below %.1f. A number returned here would be geometry applied to a "
            "measurement that no longer means anything."
            % (observed_width_px, DETECTION_FLOOR_PX,
               RELIABLE_WIDTH_PX, DETECTION_FLOOR_PX))
    return "ok" if observed_width_px >= RELIABLE_WIDTH_PX else "marginal"


def range_mm(intrinsics, marker_width_mm, observed_width_px,
             observed_width_sigma_px=0.5):
    """Z = f_px * W_mm / w_px, with the error bar and the usability status.

    `observed_width_sigma_px` defaults to half a pixel, which is the corner
    localisation uncertainty a subpixel refiner typically reaches. It is a
    DEFAULT ON AN UNCERTAINTY, not on a measurement: passing it wrong widens or
    narrows an error bar and cannot fabricate a distance.
    """
    if marker_width_mm is None or marker_width_mm <= 0.0:
        raise RangeError(
            "marker width is %r mm. Use the MEASURED width from the manifest's "
            "marker_width_mm, not the nominal 100.0 -- print scaling is exactly "
            "what the 150 mm scale bar exists to catch." % (marker_width_mm,))

    status = _check_width(observed_width_px)

    distance = intrinsics.f_px * float(marker_width_mm) / float(observed_width_px)
    sigma = range_error_mm(intrinsics, distance, observed_width_px,
                           observed_width_sigma_px)
    return RangeEstimate(distance, sigma, status, float(observed_width_px))


def range_error_mm(intrinsics, distance_mm, observed_width_px,
                   observed_width_sigma_px=0.5):
    """Propagate f_px and w_px uncertainty. Relative errors, added in quadrature.

    Z is linear in f_px and inversely linear in w_px, so both enter as pure
    relative terms:

        sigma_Z / Z  =  sqrt( (sigma_f/f)^2 + (sigma_w/w)^2 )

    The w term dominates at range, which is the whole reason the detection floor
    exists: at 20 px a half-pixel error is already 2.5% of the distance, and it
    grows without bound as the marker shrinks.
    """
    rel_f = intrinsics.f_px_sigma / intrinsics.f_px
    rel_w = float(observed_width_sigma_px) / float(observed_width_px)
    return float(distance_mm) * math.sqrt(rel_f * rel_f + rel_w * rel_w)


def apparent_width_px(intrinsics, marker_width_mm, distance_mm):
    """The inverse, for planning and for tests: how wide will it look at Z?

    Used to answer "how far can this camera see this marker" without collecting
    anything, and to generate exact synthetic cases for the test suite.
    """
    if distance_mm is None or distance_mm <= 0.0:
        raise RangeError("distance is %r mm" % (distance_mm,))
    return intrinsics.f_px * float(marker_width_mm) / float(distance_mm)
