"""The Twin Manifest — what makes a fitted twin a shareable artifact.

A trained model saved as a pickle is not an artifact. It cannot be read from
another language, cannot be diffed, does not record what data it was fitted on
or how it was validated, and rots silently when the library version changes.

A Twin Manifest is a JSON document that records everything needed to
understand, audit, reproduce and cite a fitted twin. It is language-neutral by
construction: the Julia and MATLAB bindings read and write the same file.

Interoperability rules enforced here
------------------------------------

* **No non-finite numbers.** ``NaN`` and ``Infinity`` are not valid JSON
  (RFC 8259). Python's ``json`` emits them anyway as bare tokens, which
  ``JSON.parse``, Julia's ``JSON3`` and MATLAB's ``jsondecode`` all reject.
  :meth:`TwinManifest.to_json` refuses to write them, so a diverged fit fails
  at the boundary rather than three months later in another language.
* **Timestamps are second-resolution UTC with a ``Z`` suffix.** Julia's
  ``Dates.DateTime`` cannot parse a ``+00:00`` offset without an extra package,
  and MATLAB's ``datetime`` needs an explicit format string for microseconds.
* **Unknown fields survive a round-trip.** A manifest written by a newer Otwin
  can still be read by an older one; the extra keys are preserved rather than
  raising or being silently dropped.

The normative schema lives in ``otwin-spec``; this module is one implementation
of it.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = ["TwinManifest", "Provenance", "MANIFEST_VERSION", "TIMESTAMP_FORMAT"]

MANIFEST_VERSION = "1.0"

#: Normative timestamp format. Second resolution, UTC, ``Z`` suffix.
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class Provenance:
    """Where a number came from.

    Every quantitative claim in an Otwin artifact should be traceable to a
    script, a commit and a seed. If it is not reproducible, it is an anecdote.

    Attributes:
        created: UTC timestamp in :data:`TIMESTAMP_FORMAT`.
        otwin_version: Version of the implementation that wrote this.
        implementation: ``"python"``, ``"julia"`` or ``"matlab"``.
        script: Path or URL of the script that produced the twin.
        commit: VCS commit hash of that script, if known.
        seed: Random seed, if randomness was involved.
        data_source: Identifier of the dataset — a DOI, URL or checksum.
        notes: Anything a future reader would want and cannot infer.
    """

    created: str
    otwin_version: str
    implementation: str = "python"
    script: str | None = None
    commit: str | None = None
    seed: int | None = None
    data_source: str | None = None
    notes: str | None = None

    @classmethod
    def now(
        cls, otwin_version: str, implementation: str = "python", **kwargs: Any
    ) -> Provenance:
        """Build a Provenance stamped with the current UTC time."""
        return cls(
            created=datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT),
            otwin_version=otwin_version,
            implementation=implementation,
            **kwargs,
        )


@dataclass(frozen=True)
class TwinManifest:
    """A complete, portable description of a fitted twin.

    Attributes:
        name: Human-readable identifier for this twin.
        model_class: Which structure — ``"port_hamiltonian"``,
            ``"irreversible_phs"``, ``"empirical_law"``, ``"learned_phs"`` or
            ``"composite"``.
        model_kind: The specific model, e.g. ``"water_tank"``, ``"dc_motor"``.
        n_states: State dimension.
        n_inputs: Input dimension.
        parameters: Fitted or specified parameter values.
        estimated: Names of parameters estimated from data, as opposed to
            supplied from first principles. The white-box/grey-box distinction
            is exactly this list: empty means white-box.
        validation: How the twin was validated. Use
            :meth:`otwin.interfaces.Report.to_dict` rather than hand-rolled keys.
        calibration: Uncertainty method and measured coverage. Use
            :meth:`otwin.interfaces.Interval.to_dict`.
        provenance: See :class:`Provenance`.
        extra: Fields from a newer manifest version, preserved so that a
            round-trip through an older reader is lossless.

    Example:
        >>> m = TwinManifest(
        ...     name="tank-A",
        ...     model_class="port_hamiltonian",
        ...     model_kind="water_tank",
        ...     n_states=1,
        ...     n_inputs=1,
        ...     parameters={"area": 1.0, "outlet": 0.1},
        ...     provenance=Provenance.now("0.1.0"),
        ... )
        >>> m.is_white_box
        True
    """

    name: str
    model_class: str
    model_kind: str
    n_states: int
    n_inputs: int
    provenance: Provenance
    parameters: dict[str, Any] = field(default_factory=dict)
    estimated: tuple[str, ...] = ()
    validation: dict[str, Any] | None = None
    calibration: dict[str, Any] | None = None
    manifest_version: str = MANIFEST_VERSION
    extra: dict[str, Any] = field(default_factory=dict)

    VALID_CLASSES = (
        "port_hamiltonian",
        "irreversible_phs",
        "empirical_law",
        "learned_phs",
        "composite",
    )

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise TypeError(f"name must be a non-empty string, got {self.name!r}")
        if self.model_class not in self.VALID_CLASSES:
            raise ValueError(
                f"model_class must be one of {self.VALID_CLASSES}, "
                f"got {self.model_class!r}"
            )
        if isinstance(self.estimated, str):
            raise TypeError(
                f"estimated must be a sequence of names, not a single string "
                f"({self.estimated!r}). Did you mean ({self.estimated!r},)?"
            )
        object.__setattr__(self, "estimated", tuple(self.estimated))
        if len(set(self.estimated)) != len(self.estimated):
            raise ValueError(f"estimated contains duplicates: {self.estimated}")
        if not isinstance(self.n_states, int) or self.n_states < 1:
            raise ValueError(f"n_states must be an integer >= 1, got {self.n_states!r}")
        if not isinstance(self.n_inputs, int) or self.n_inputs < 0:
            raise ValueError(f"n_inputs must be an integer >= 0, got {self.n_inputs!r}")
        unknown = set(self.estimated) - set(self.parameters)
        if unknown:
            raise ValueError(
                f"estimated names not present in parameters: {sorted(unknown)}"
            )

    @property
    def is_white_box(self) -> bool:
        """True when no parameter was estimated from data.

        A white-box twin can be validated against a closed-form answer. A
        grey-box twin cannot, and must be validated against held-out data with
        a baseline instead.
        """
        return len(self.estimated) == 0

    @property
    def is_validated(self) -> bool:
        """True only when a leakage-free validation was actually recorded.

        Deliberately strict: ``leakage_free`` must be the boolean ``True``, not
        merely truthy. Manifests arrive from MATLAB and Julia, where a boolean
        can round-trip as ``1`` or as the string ``"false"`` — and the one
        property that certifies honest validation must not accept those.
        """
        if not self.validation:
            return False
        return self.validation.get("leakage_free") is True

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dict, dropping unset optional sections."""
        d = asdict(self)
        d["estimated"] = list(self.estimated)
        extra = d.pop("extra", None) or {}
        d = {k: v for k, v in d.items() if v is not None}
        d["provenance"] = {k: v for k, v in d["provenance"].items() if v is not None}
        d.update(extra)
        return d

    def to_json(self, indent: int = 2) -> str:
        """Serialise to a JSON string.

        Raises:
            ValueError: If any value is ``NaN`` or infinite. Those are not
                valid JSON and would be unreadable from Julia and MATLAB. A
                diverged fit should fail here, loudly, not travel.
        """
        try:
            return json.dumps(
                self.to_dict(), indent=indent, sort_keys=False, allow_nan=False
            )
        except ValueError as exc:
            raise ValueError(
                f"Manifest contains a value that is not representable in JSON "
                f"({exc}). NaN and Infinity are not valid JSON and cannot be "
                f"read from Julia or MATLAB. If a fit diverged, record that "
                f"fact in `notes` rather than writing a non-finite parameter."
            ) from exc

    def save(self, path: str | Path) -> Path:
        """Write the manifest to ``path``. Returns the path written."""
        text = self.to_json()  # validate before creating anything
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TwinManifest:
        """Reconstruct from a plain dict.

        Unknown keys are preserved in :attr:`extra` rather than raising, so a
        manifest written by a newer Otwin round-trips losslessly through an
        older reader.
        """
        data = dict(d)
        raw_version = data.get("manifest_version", MANIFEST_VERSION)
        if not isinstance(raw_version, str):
            # A non-string version used to be coerced with str(), which meant
            # `{"manifest_version": null}` loaded, warned about version "None",
            # and then vanished from to_dict() entirely -- so reading the file
            # back produced a manifest silently claiming to be this reader's
            # own version. The one job of this field is to let an old reader
            # notice it is reading a new file; quietly relabelling it defeats
            # that completely.
            raise ValueError(
                f"manifest_version must be a string, got {type(raw_version).__name__}"
            )
        version = raw_version
        if version.split(".")[0] != MANIFEST_VERSION.split(".")[0]:
            warnings.warn(
                f"Manifest declares version {version}; this reader implements "
                f"{MANIFEST_VERSION}. Fields may be missing or misinterpreted.",
                stacklevel=2,
            )
        prov = data.pop("provenance", None)
        if prov is None:
            raise ValueError("manifest is missing the required 'provenance' section")
        if not isinstance(prov, dict):
            # Fail at the boundary, naming the field. The previous version let
            # a non-mapping through untouched: `{"provenance": true}` loaded
            # without complaint and then raised
            # `AttributeError: 'bool' object has no attribute 'items'` from
            # `to_dict()`, at a call site with no idea which file was at fault.
            # SECURITY.md names manifest deserialisation as this project's
            # threat surface; a permissive parser that defers its failure is
            # exactly the shape that hides in.
            raise ValueError(
                f"manifest 'provenance' must be a mapping of fields, got "
                f"{type(prov).__name__}"
            )
        prov_known = {f for f in Provenance.__dataclass_fields__}
        prov = Provenance(**{k: v for k, v in prov.items() if k in prov_known})
        known = {f for f in cls.__dataclass_fields__} - {"provenance", "extra"}
        kwargs = {k: v for k, v in data.items() if k in known}
        extra = {k: v for k, v in data.items() if k not in known}
        if "estimated" in kwargs:
            kwargs["estimated"] = tuple(kwargs["estimated"])
        return cls(provenance=prov, extra=extra, **kwargs)

    @classmethod
    def load(cls, path: str | Path) -> TwinManifest:
        """Read a manifest from ``path``."""
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
