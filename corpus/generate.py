"""Deterministic synthetic refinery corpus (SPEC §20.1).

Generates a fictional plant ("Unit 3 — LPG Recovery", "Unit 5 — Diesel Hydrotreater") with
internally consistent SOPs, maintenance logs, inspection reports, datasheets, a DCS tag
list, incident reports, emails and a small legacy script — plus corpus/truth.json recording
every planted fact so the eval suite has known answers. P&ID SVG generation lives in
corpus/pid_gen.py (M7). No model calls: templates + a fixed RNG keep it reproducible.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

PUMPS = [
    ("P-3101A", "LPG product pump A", "mechanical seal", "plan 11 flush"),
    ("P-3101B", "LPG product pump B", "mechanical seal", "plan 11 flush"),
    ("P-3102A", "reflux pump A", "mechanical seal", "plan 52 flush"),
    ("P-5201A", "diesel feed pump A", "mechanical seal", "plan 32 flush"),
]
VESSELS = [("V-3104", "LPG accumulator"), ("V-3110", "reflux drum"), ("V-5210", "feed surge drum")]
EXCHANGERS = [("E-3102", "LPG condenser"), ("E-5205", "feed/effluent exchanger")]
INSTRUMENTS = [
    ("FIC-3201", "LPG flow controller"),
    ("LT-3104", "accumulator level transmitter"),
    ("PSV-3105", "accumulator relief valve"),
    ("TIC-5205", "reactor temperature controller"),
]


@dataclass
class TruthFact:
    doc: str
    kind: str
    statement: str
    answer: str
    tags: list[str] = field(default_factory=list)


class CorpusGenerator:
    SIZES: ClassVar[dict[str, int]] = {"small": 40, "medium": 200, "large": 2000}

    def __init__(self, out_dir: Path, size: str = "small", seed: int = 26117) -> None:
        self.out_dir = out_dir
        self.size = size
        self.target = self.SIZES.get(size, 40)
        self.rng = random.Random(seed)
        self.truth: list[TruthFact] = []

    def generate(self) -> dict[str, Any]:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "docs").mkdir(exist_ok=True)
        count = 0
        count += self._maintenance_logs()
        count += self._sops()
        count += self._inspection_reports()
        count += self._datasheets()
        count += self._dcs_tag_list()
        count += self._incident_reports()
        count += self._emails()
        count += self._legacy_script()
        # pad to the target size with additional dated maintenance entries
        while count < self.target:
            count += self._extra_log(count)
        truth = {
            "plant": "Unit 3 — LPG Recovery / Unit 5 — Diesel Hydrotreater (synthetic)",
            "facts": [fact.__dict__ for fact in self.truth],
            "document_count": count,
        }
        (self.out_dir / "truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
        return truth

    def _write(self, name: str, text: str) -> None:
        (self.out_dir / "docs" / name).write_text(text, encoding="utf-8")

    def _maintenance_logs(self) -> int:
        # Plant the "recurring seal failure on P-3101A" fact the demo hinges on.
        rows = ["date | equipment | event | action | downtime_h"]
        seal_failures = {"P-3101A": 5, "P-3101B": 1, "P-3102A": 0, "P-5201A": 1}
        for month in range(1, 25):
            for tag, base in seal_failures.items():
                if self.rng.random() < base / 12:
                    rows.append(
                        f"2024-{month:02d}-15 | {tag} | seal weepage then failure | "
                        f"replaced mechanical seal | {self.rng.randint(4, 24)}"
                    )
        self._write("MaintLog_Unit3_2024_2025.csv", "\n".join(rows))
        self.truth.append(
            TruthFact(
                "MaintLog_Unit3_2024_2025.csv",
                "reliability",
                "Which pump has the most recurring seal failures in Unit 3?",
                "P-3101A",
                ["P-3101A"],
            )
        )
        return 1

    def _sops(self) -> int:
        n = 0
        for tag, desc, seal, flush in PUMPS:
            body = (
                f"Standard Operating Procedure SOP-PMP-014\n"
                f"Title: Mechanical seal replacement for {tag} ({desc})\n"
                f"Rev C\n\n"
                f"1. Isolate {tag} and de-pressurise; confirm the standby pump is running.\n"
                f"2. The pump uses a {seal} with API {flush}. Verify the flush plan piping.\n"
                f"3. Torque the gland to 45 Nm. Set the seal face per the datasheet.\n"
                f"4. Restore the {flush} and check for weepage before returning to service.\n"
                f"Safety: PSV isolation valves must remain car-sealed open (CSO) throughout.\n"
            )
            self._write(f"SOP-PMP-014_{tag}.txt", body)
            n += 1
        self.truth.append(
            TruthFact(
                "SOP-PMP-014_P-3101A.txt",
                "procedure",
                "What flush plan does pump P-3101A use for its mechanical seal?",
                "plan 11 flush",
                ["P-3101A", "SOP-PMP-014"],
            )
        )
        self.truth.append(
            TruthFact(
                "SOP-PMP-014_P-3101A.txt",
                "safety",
                "What must remain car-sealed open during PSV maintenance per SOP-PMP-014?",
                "PSV isolation valves",
                ["SOP-PMP-014"],
            )
        )
        return n

    def _inspection_reports(self) -> int:
        n = 0
        for tag, desc in VESSELS:
            thickness = round(self.rng.uniform(9.5, 12.5), 1)
            body = (
                f"Inspection Report IR-{tag}-2025\n"
                f"Equipment: {tag} ({desc})\n"
                f"Inspection type: ultrasonic thickness survey\n"
                f"Measured minimum wall thickness: {thickness} mm (nominal 12.0 mm)\n"
                f"Corrosion rate: {round(self.rng.uniform(0.05, 0.2), 2)} mm/year\n"
                f"Next inspection due: 2027\n"
                f"Finding: {'acceptable' if thickness > 10 else 'below minimum — review required'}\n"
            )
            self._write(f"IR-{tag}-2025.txt", body)
            self.truth.append(
                TruthFact(
                    f"IR-{tag}-2025.txt",
                    "inspection",
                    f"What is the measured minimum wall thickness of {tag}?",
                    f"{thickness} mm",
                    [tag],
                )
            )
            n += 1
        return n

    def _datasheets(self) -> int:
        n = 0
        for tag, desc in EXCHANGERS:
            duty = self.rng.randint(2, 8)
            body = (
                f"Equipment Datasheet DS-{tag}\n"
                f"Service: {desc}\n"
                f"Type: shell and tube heat exchanger\n"
                f"Design duty: {duty}.0 MW\n"
                f"Design pressure: 19 barg shell / 25 barg tube\n"
                f"Material: shell CS, tubes SS316L\n"
                f"Applicable standard: ASME Section VIII Div 1; TEMA R\n"
            )
            self._write(f"DS-{tag}.txt", body)
            self.truth.append(
                TruthFact(
                    f"DS-{tag}.txt",
                    "datasheet",
                    f"What is the design duty of exchanger {tag}?",
                    f"{duty}.0 MW",
                    [tag],
                )
            )
            n += 1
        return n

    def _dcs_tag_list(self) -> int:
        rows = ["tag | description | range | units | alarm"]
        for tag, desc in INSTRUMENTS:
            rows.append(f"{tag} | {desc} | 0-100 | % | HH 95 / LL 5")
        self._write("DCS_TagList_Unit3.csv", "\n".join(rows))
        self.truth.append(
            TruthFact(
                "DCS_TagList_Unit3.csv",
                "instrumentation",
                "What is the high-high alarm setpoint for FIC-3201?",
                "95",
                ["FIC-3201"],
            )
        )
        return 1

    def _incident_reports(self) -> int:
        body = (
            "Incident Report INC-2025-07\n"
            "Unit: Unit 3 LPG Recovery\n"
            "Summary: LPG accumulator V-3104 high level trip during a P-3101A seal failure.\n"
            "Root cause: repeated seal failures on P-3101A caused loss of forwarding capacity.\n"
            "Recommendation: investigate P-3101A seal reliability; review flush plan 11 condition.\n"
        )
        self._write("INC-2025-07.txt", body)
        self.truth.append(
            TruthFact(
                "INC-2025-07.txt",
                "incident",
                "What was the root cause of incident INC-2025-07?",
                "repeated seal failures on P-3101A",
                ["P-3101A", "V-3104"],
            )
        )
        return 1

    def _emails(self) -> int:
        body = (
            "From: reliability@mrpl.example\n"
            "To: maintenance@mrpl.example\n"
            "Subject: P-3101A recurring seal failures\n\n"
            "Team, P-3101A has failed on the mechanical seal five times in the last two years. "
            "Please prioritise a root-cause review and check the plan 11 flush against SOP-PMP-014.\n"
        )
        self._write("email_P-3101A_review.eml", body)
        return 1

    def _legacy_script(self) -> int:
        body = (
            '"""Legacy tank gauging (has a unit bug: reports level in cm, not m)."""\n\n'
            "def tank_level(raw_ma):\n"
            "    # 4-20 mA maps to 0-10 m; BUG: returns centimetres without converting\n"
            "    span_m = 10.0\n"
            "    level = (raw_ma - 4) / 16 * span_m * 100  # <-- unit bug\n"
            "    return level\n\n\n"
            "if __name__ == '__main__':\n"
            "    print(tank_level(12))\n"
        )
        (self.out_dir / "docs").mkdir(exist_ok=True)
        self._write("tank_gauging.py", body)
        self.truth.append(
            TruthFact(
                "tank_gauging.py",
                "code",
                "What unit bug exists in tank_gauging.py?",
                "returns centimetres instead of metres (multiplies by 100)",
                [],
            )
        )
        return 1

    def _extra_log(self, index: int) -> int:
        tag, desc, _, _ = self.rng.choice(PUMPS)
        body = (
            f"Maintenance note MN-{index:04d}\n"
            f"Equipment: {tag} ({desc})\n"
            f"Routine lubrication and vibration check completed. Vibration "
            f"{round(self.rng.uniform(1.5, 4.5), 1)} mm/s RMS, within limits.\n"
        )
        self._write(f"MN-{index:04d}.txt", body)
        return 1


def generate_corpus(out_dir: Path, size: str = "small", seed: int = 26117) -> dict[str, Any]:
    return CorpusGenerator(out_dir, size, seed).generate()
