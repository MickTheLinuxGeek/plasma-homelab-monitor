import json
from pathlib import Path
from xml.etree import ElementTree

PROJECT_ROOT = Path(__file__).parents[2]
PACKAGE = PROJECT_ROOT / "plasmoid" / "package"


def test_plasmoid_metadata_targets_plasma_6() -> None:
    metadata = json.loads((PACKAGE / "metadata.json").read_text(encoding="utf-8"))

    assert metadata["KPackageStructure"] == "Plasma/Applet"
    assert metadata["X-Plasma-API-Minimum-Version"] == "6.0"
    assert metadata["KPlugin"]["Id"] == "org.mickgeeklabs.homelabmonitor"


def test_required_plasmoid_files_exist() -> None:
    required = [
        "contents/ui/main.qml",
        "contents/ui/CompactRepresentation.qml",
        "contents/ui/FullRepresentation.qml",
        "contents/ui/ConfigGeneral.qml",
        "contents/config/main.xml",
        "contents/config/config.qml",
    ]

    assert all((PACKAGE / path).is_file() for path in required)


def test_kconfig_xml_is_well_formed() -> None:
    root = ElementTree.parse(PACKAGE / "contents/config/main.xml").getroot()

    names = {entry.attrib["name"] for entry in root.findall(".//{*}entry")}
    assert names == {"collectorUrl", "refreshInterval"}
