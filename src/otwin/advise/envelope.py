"""The twin can say no.

A model that always returns a number is not being careful, it is being polite.
Every forecast this library produces carries a validity envelope: the operating
range the model was actually identified over, the horizon it was actually
validated to, and whether its intervals have actually been checked against
held-out data. Ask outside that envelope and you get a refusal with a reason,
not a plausible number.

This is the ISO 13374 Advisory Generation block (AG), and it is the difference
between a twin and a plotting library. A confident wrong answer about when a
40 MWh bank reaches end of life costs more than no answer at all.

The envelope is read from the :class:`~otwin.interfaces.TwinManifest` -- the
same record that says what was estimated, under which split protocol, and at
what measured coverage. Nothing here is inferred. If the manifest does not
record that something was checked, the answer is that it was not checked, and
``not yet checked`` is not the same as ``fine``.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt


class OutsideEnvelope(RuntimeError):
    """The question falls outside what this twin has been shown to answer."""

    def __init__(self, verdict: "Verdict"):
        self.verdict = verdict
        super().__init__(verdict.explain())


@dataclass(frozen=True)
class Breach:
    """One reason a request falls outside the envelope."""

    kind: str
    detail: str
    observed: float | None = None
    limit: float | None = None

    def __str__(self) -> str:
        if self.observed is None or self.limit is None:
            return f"{self.kind}: {self.detail}"
        return (
            f"{self.kind}: {self.detail} "
            f"(asked for {self.observed:g}, validated to {self.limit:g})"
        )


@dataclass
class Verdict:
    """What the twin is willing to say, and why.

    Attributes:
        answerable: Whether the question is inside the validated envelope.
        breaches: Every reason it is not. Empty when ``answerable``.
        checked: Every check that ran and passed -- so a clean verdict is
            evidence rather than silence.
    """

    answerable: bool
    breaches: list[Breach] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.answerable

    def explain(self) -> str:
        if self.answerable:
            passed = "; ".join(self.checked) or "no checks configured"
            return f"inside the validated envelope ({passed})"
        lines = ["outside the validated envelope:"]
        lines += [f"  - {b}" for b in self.breaches]
        lines.append("")
        lines.append(
            "This is a refusal, not a failure. The twin has not been shown to "
            "answer this question, and returning a number anyway would hide that."
        )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "answerable": self.answerable,
            "breaches": [
                {
                    "kind": b.kind,
                    "detail": b.detail,
                    "observed": b.observed,
                    "limit": b.limit,
                }
                for b in self.breaches
            ],
            "checked": list(self.checked),
        }


@dataclass
class Envelope:
    """The range over which a twin has been shown to work.

    Args:
        state_bounds: Per-state ``(low, high)`` the model was identified over.
            ``None`` for a state leaves it unconstrained.
        max_horizon: Longest forecast horizon that was actually validated, in
            steps. ``None`` means no horizon was validated -- which is a
            refusal for every horizon, not a licence for all of them.
        requires_validated: Refuse if the manifest does not record a
            leakage-free validation. Default True.
        requires_calibrated: Refuse if interval coverage was never measured.
            Only applies to requests that ask for an interval.
        max_extrapolation: How far outside ``state_bounds`` to tolerate, as a
            fraction of each range. 0.0 means none at all.

    Example:
        >>> env = Envelope(state_bounds=[(0.0, 1.0)], max_horizon=500)
        >>> v = env.check(state=[0.4], horizon=100)
        >>> bool(v)
        True
        >>> v = env.check(state=[0.4], horizon=900)
        >>> bool(v)
        False
        >>> print(v.breaches[0])
        horizon: beyond the validated forecast horizon (asked for 900, validated to 500)
    """

    state_bounds: list[tuple[float, float] | None] | None = None
    max_horizon: int | None = None
    requires_validated: bool = True
    requires_calibrated: bool = True
    max_extrapolation: float = 0.0

    # ------------------------------------------------------------------
    @classmethod
    def from_manifest(cls, manifest: Any, **overrides: Any) -> "Envelope":
        """Build an envelope from what a fitted twin actually recorded.

        Reads ``validation`` and ``calibration`` off a
        :class:`~otwin.interfaces.TwinManifest`. Fields the manifest does not
        carry stay ``None``, which is a refusal rather than a default.
        """
        validation = getattr(manifest, "validation", None) or {}
        kwargs: dict[str, Any] = {
            "max_horizon": validation.get("horizon"),
            "state_bounds": validation.get("state_bounds"),
        }
        kwargs.update(overrides)
        return cls(**kwargs)

    # ------------------------------------------------------------------
    def check(
        self,
        state: npt.ArrayLike | None = None,
        horizon: int | None = None,
        manifest: Any = None,
        wants_interval: bool = False,
    ) -> Verdict:
        """Decide whether this question is inside the envelope.

        Args:
            state: The operating point the forecast starts from.
            horizon: Steps ahead being requested.
            manifest: The fitted twin's record, for the validation and
                calibration checks.
            wants_interval: Whether the caller is asking for an uncertainty
                band. Calibration is only required if they are.

        Returns:
            A :class:`Verdict`. Truthy when the question can be answered.
        """
        breaches: list[Breach] = []
        checked: list[str] = []

        if horizon is not None:
            if self.max_horizon is None:
                breaches.append(
                    Breach(
                        "horizon",
                        "no forecast horizon has been validated for this twin",
                    )
                )
            elif horizon > self.max_horizon:
                breaches.append(
                    Breach(
                        "horizon",
                        "beyond the validated forecast horizon",
                        float(horizon),
                        float(self.max_horizon),
                    )
                )
            else:
                checked.append(f"horizon {horizon} <= {self.max_horizon}")

        if state is not None and self.state_bounds is None:
            # Symmetric with the horizon check above. An operating range that
            # was never recorded is a refusal, not a licence.
            #
            # The previous version skipped this branch entirely when
            # `state_bounds` was None, so a twin with no recorded range
            # returned a clean verdict for any operating point at all -- a
            # state of charge of 1e12 came back answerable with zero breaches.
            # `from_manifest` already states the intended rule: fields the
            # manifest does not carry stay None, "which is a refusal rather
            # than a default". That held for `max_horizon` and not for this.
            breaches.append(
                Breach(
                    "state",
                    "no operating range has been recorded for this twin, so no "
                    "operating point can be shown to be inside it",
                )
            )
        elif state is not None and self.state_bounds is not None:
            x = np.atleast_1d(np.asarray(state, dtype=float))
            if len(x) != len(self.state_bounds):
                breaches.append(
                    Breach(
                        "state",
                        f"envelope describes {len(self.state_bounds)} states, "
                        f"got {len(x)}",
                    )
                )
            else:
                for i, (value, bound) in enumerate(
                    zip(x, self.state_bounds, strict=True)
                ):
                    if bound is None:
                        continue
                    lo, hi = float(bound[0]), float(bound[1])
                    slack = self.max_extrapolation * (hi - lo)
                    if value < lo - slack:
                        breaches.append(
                            Breach(
                                "state",
                                f"state {i} below the identified range",
                                float(value),
                                lo - slack,
                            )
                        )
                    elif value > hi + slack:
                        breaches.append(
                            Breach(
                                "state",
                                f"state {i} above the identified range",
                                float(value),
                                hi + slack,
                            )
                        )
                if not any(b.kind == "state" for b in breaches):
                    checked.append("operating point inside the identified range")

        if manifest is not None:
            if self.requires_validated:
                if not getattr(manifest, "is_validated", False):
                    # A manifest that carries validation under some other key is
                    # the interesting case: the twin probably *was* validated and
                    # the record simply does not assert it. Saying "never been
                    # validated" there is true of the record and false of the
                    # work, and sends the reader looking in the wrong place.
                    recorded = getattr(manifest, "validation", None) or {}
                    # Narrow on purpose. A record that carries `leakage_free`
                    # and sets it to False -- or to a `1` that survived a trip
                    # through MATLAB -- has answered the question, and the
                    # answer is no. The reworded message is only for the record
                    # that never mentions the key, which is the one whose author
                    # has no way to find out what is wrong.
                    if recorded and "leakage_free" not in recorded:
                        detail = (
                            "validation is recorded "
                            f"({', '.join(sorted(str(k) for k in recorded))}) but does "
                            "not assert leakage_free=True; that key, as the boolean, is "
                            "what certifies the protocol. Build it with "
                            "TwinManifest.validated_by(...)"
                        )
                    else:
                        detail = (
                            "this twin has never been validated under a "
                            "leakage-free protocol"
                        )
                    breaches.append(Breach("validation", detail))
                else:
                    checked.append("validated, leakage-free")

            if wants_interval and self.requires_calibrated:
                calibration = getattr(manifest, "calibration", None) or {}
                if calibration.get("empirical_coverage") is None:
                    if calibration and "empirical_coverage" not in calibration:
                        detail = (
                            "calibration is recorded "
                            f"({', '.join(sorted(str(k) for k in calibration))}) but "
                            "carries no empirical_coverage; a nominal level is a "
                            "promise, and this check reads the measurement. Build it "
                            "with TwinManifest.calibrated_by(...)"
                        )
                    else:
                        detail = (
                            "interval coverage has never been measured, so the "
                            "band has no demonstrated meaning"
                        )
                    breaches.append(Breach("calibration", detail))
                else:
                    checked.append(
                        f"coverage measured at {calibration['empirical_coverage']:.2f}"
                    )

        return Verdict(answerable=not breaches, breaches=breaches, checked=checked)

    # ------------------------------------------------------------------
    def require(self, **kwargs: Any) -> Verdict:
        """Like :meth:`check`, but raises :class:`OutsideEnvelope` on refusal.

        Use this at the boundary of anything automated. A dispatch decision
        should stop, not proceed with a caveat nobody reads.
        """
        verdict = self.check(**kwargs)
        if not verdict:
            raise OutsideEnvelope(verdict)
        return verdict
