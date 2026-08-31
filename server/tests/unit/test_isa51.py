from yantra_server.vision.pid.isa51 import (
    classify_tag,
    is_safety_instrument,
    loop_of,
    parse_equipment,
    parse_instrument,
    parse_line,
)


def test_parse_instrument_fic():
    tag = parse_instrument("FIC-3201A")
    assert tag is not None
    assert tag.measured_variable == "flow"
    assert "indicator" in tag.functions and "controller" in tag.functions
    assert tag.loop_number == "3201"
    assert tag.suffix == "A"


def test_parse_instrument_variants():
    assert parse_instrument("LT-3104").measured_variable == "level"
    assert parse_instrument("PSV-101").measured_variable == "pressure"
    assert parse_instrument("TIC-5205").functions == ["indicator", "controller"]
    assert parse_instrument("not-a-tag") is None


def test_parse_equipment():
    pump = parse_equipment("P-3101A")
    assert pump is not None and pump.equipment_type == "pump" and pump.number == "3101"
    assert parse_equipment("E-201").equipment_type == "heat exchanger"
    assert parse_equipment("V-301").equipment_type == "vessel/drum"
    assert parse_equipment("ZZ-99") is None  # unknown prefix


def test_parse_line():
    line = parse_line('6"-P-1201-A1A-IH')
    assert line is not None
    assert line.size_inch == 6.0
    assert line.service == "P"
    assert line.number == "1201"
    assert line.spec == "A1A"
    assert line.insulation == "IH"


def test_classify_tag_precedence():
    assert classify_tag('6"-P-1201-A1A').kind == "line"
    assert classify_tag("P-3101A").kind == "equipment"
    assert classify_tag("FIC-3201").kind == "instrument"


def test_loop_of():
    assert loop_of("FT-3201") == "3201"
    assert loop_of("FIC-3201") == "3201"
    assert loop_of("FCV-3201") == "3201"
    assert loop_of("P-3101A") is None  # equipment, not an instrument


def test_is_safety_instrument():
    assert is_safety_instrument("PSV-3105")
    assert is_safety_instrument("PRV-101")
    assert not is_safety_instrument("FIC-3201")
