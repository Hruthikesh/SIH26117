"""ISA-5.1 tag grammar (SPEC §11.2 step 3): instruments, equipment, lines.

A deterministic parser, not a model: given a tag string it returns its structured meaning,
which is what makes small-model P&ID analysis reliable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ISA-5.1 first-letter = measured/initiating variable.
FIRST_LETTER: dict[str, str] = {
    "A": "analysis",
    "B": "burner/combustion",
    "C": "conductivity",
    "D": "density",
    "E": "voltage",
    "F": "flow",
    "G": "gauging/position",
    "H": "hand",
    "I": "current",
    "J": "power",
    "K": "time/schedule",
    "L": "level",
    "M": "moisture",
    "N": "user",
    "O": "user",
    "P": "pressure",
    "Q": "quantity",
    "R": "radiation",
    "S": "speed/frequency",
    "T": "temperature",
    "U": "multivariable",
    "V": "vibration",
    "W": "weight/force",
    "X": "unclassified",
    "Y": "event/state",
    "Z": "position/dimension",
}
# Succeeding letters = function/modifier.
SUCCEEDING_LETTER: dict[str, str] = {
    "A": "alarm",
    "C": "controller",
    "E": "element/sensor",
    "G": "glass/gauge",
    "I": "indicator",
    "K": "control station",
    "L": "light/low",
    "H": "high",
    "M": "middle",
    "O": "orifice",
    "P": "test point",
    "R": "recorder",
    "S": "switch/safety",
    "T": "transmitter",
    "V": "valve/damper",
    "W": "well",
    "X": "unclassified",
    "Y": "relay/compute",
    "Z": "driver/actuator",
}

DEFAULT_EQUIPMENT_PREFIXES: dict[str, str] = {
    "P": "pump",
    "C": "compressor",
    "K": "compressor",
    "E": "heat exchanger",
    "V": "vessel/drum",
    "T": "tower/column",
    "D": "drum",
    "R": "reactor",
    "F": "furnace/fired heater",
    "TK": "tank",
    "MX": "mixer",
    "FL": "filter",
}

INSTRUMENT_RE = re.compile(r"^([A-Z])([A-Z]{0,3})-?(\d{2,5})([A-Z]?)$")
EQUIPMENT_RE = re.compile(r"^([A-Z]{1,2})-(\d{2,4})([A-Z])?(?:/([A-Z]))?$")
LINE_RE = re.compile(r'^(\d{1,2})"?-([A-Z]+)-(\d{3,5})-([A-Z0-9]+?)(?:-([A-Z]{1,3}))?$')


@dataclass
class InstrumentTag:
    raw: str
    measured_variable: str
    functions: list[str]
    loop_number: str
    suffix: str = ""
    location: str = "field"  # field|panel|dcs, inferred from bubble style elsewhere
    kind: str = "instrument"


@dataclass
class EquipmentTag:
    raw: str
    prefix: str
    equipment_type: str
    number: str
    suffix: str = ""
    kind: str = "equipment"


@dataclass
class LineTag:
    raw: str
    size_inch: float
    service: str
    number: str
    spec: str
    insulation: str = ""
    kind: str = "line"


@dataclass
class TagPrefixMap:
    equipment: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_EQUIPMENT_PREFIXES))

    @classmethod
    def load(cls, path: Path | None) -> TagPrefixMap:
        mapping = dict(DEFAULT_EQUIPMENT_PREFIXES)
        if path and path.is_file():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                for prefix, name in (data.get("equipment", {}) or {}).items():
                    mapping[str(prefix).upper()] = str(name)
            except yaml.YAMLError:
                pass
        return cls(equipment=mapping)


def parse_instrument(tag: str) -> InstrumentTag | None:
    match = INSTRUMENT_RE.match(tag.strip().upper())
    if not match:
        return None
    first, rest, loop, suffix = match.groups()
    if first not in FIRST_LETTER:
        return None
    functions = [SUCCEEDING_LETTER.get(ch, "unknown") for ch in (rest or "")]
    return InstrumentTag(
        raw=tag.strip(),
        measured_variable=FIRST_LETTER[first],
        functions=functions,
        loop_number=loop,
        suffix=suffix or "",
    )


def parse_equipment(tag: str, prefixes: TagPrefixMap | None = None) -> EquipmentTag | None:
    prefixes = prefixes or TagPrefixMap()
    match = EQUIPMENT_RE.match(tag.strip().upper())
    if not match:
        return None
    prefix, number, suffix, alt = match.groups()
    if prefix not in prefixes.equipment:
        return None
    return EquipmentTag(
        raw=tag.strip(),
        prefix=prefix,
        equipment_type=prefixes.equipment[prefix],
        number=number,
        suffix=suffix or alt or "",
    )


def parse_line(tag: str) -> LineTag | None:
    match = LINE_RE.match(tag.strip().upper())
    if not match:
        return None
    size, service, number, spec, insulation = match.groups()
    return LineTag(
        raw=tag.strip(),
        size_inch=float(size),
        service=service,
        number=number,
        spec=spec,
        insulation=insulation or "",
    )


def classify_tag(
    tag: str, prefixes: TagPrefixMap | None = None
) -> InstrumentTag | EquipmentTag | LineTag | None:
    """Try line → equipment → instrument (most specific first)."""
    if line := parse_line(tag):
        return line
    if equip := parse_equipment(tag, prefixes):
        return equip
    if inst := parse_instrument(tag):
        return inst
    return None


def loop_of(tag: str) -> str | None:
    """The loop number an instrument belongs to (FT-3201, FIC-3201 → 3201).

    Defers to equipment/line classification first, so an equipment tag like P-3101A
    (which also matches the instrument grammar as pressure) is not mistaken for a loop.
    """
    classified = classify_tag(tag)
    if isinstance(classified, InstrumentTag):
        return classified.loop_number
    return None


def is_safety_instrument(tag: str) -> bool:
    """PSV/PSHH/SIS-style safety tags (relief, safety switches)."""
    upper = tag.strip().upper()
    if upper.startswith("PSV") or upper.startswith("PZV") or upper.startswith("PRV"):
        return True
    inst = parse_instrument(tag)
    return bool(inst and "safety/switch" in inst.functions and inst.measured_variable == "pressure")
