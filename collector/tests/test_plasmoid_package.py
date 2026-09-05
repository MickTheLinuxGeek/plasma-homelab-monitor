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
        "contents/ui/DashboardHeader.qml",
        "contents/ui/DiagnosticsSection.qml",
        "contents/ui/DockerSection.qml",
        "contents/ui/EmptyState.qml",
        "contents/ui/HostsSection.qml",
        "contents/ui/JellyfinSection.qml",
        "contents/ui/ProviderError.qml",
        "contents/ui/ResourceRow.qml",
        "contents/ui/SectionHeader.qml",
        "contents/ui/StatusIndicator.qml",
        "contents/config/main.xml",
        "contents/config/config.qml",
    ]

    assert all((PACKAGE / path).is_file() for path in required)


def test_kconfig_xml_is_well_formed() -> None:
    root = ElementTree.parse(PACKAGE / "contents/config/main.xml").getroot()

    names = {entry.attrib["name"] for entry in root.findall(".//{*}entry")}
    assert names == {
        "collectorUrl",
        "refreshInterval",
        "showHosts",
        "showDocker",
        "showJellyfin",
        "hostsExpanded",
        "dockerExpanded",
        "jellyfinExpanded",
        "sortMode",
        "issuesOnlyByDefault",
    }


def test_qml_models_transport_freshness_and_bounded_retry_independently() -> None:
    main_qml = (PACKAGE / "contents/ui/main.qml").read_text(encoding="utf-8")

    assert "property bool requestInFlight: false" in main_qml
    assert 'property string transportState: "unknown"' in main_qml
    assert "readonly property string dataFreshness:" in main_qml
    assert "readonly property string dashboardHealth:" in main_qml
    assert "readonly property string compactStatus:" in main_qml
    assert "if (root.requestInFlight)" in main_qml
    assert "Math.min(root.maximumRetryDelay" in main_qml
    assert 'root.transportState = "unavailable"' in main_qml
    assert "root.dashboard = payload" in main_qml
    assert "root.retryAttempt = 0" in main_qml
    assert 'root.endpoint("/api/v2/dashboard")' in main_qml
    assert "validProviderState" in main_qml
    assert "validDashboardPayload" in main_qml
    assert "payload.last_successful_observation_at" in main_qml


def test_qml_exposes_accessible_non_color_status_and_controls() -> None:
    compact_qml = (PACKAGE / "contents/ui/CompactRepresentation.qml").read_text(encoding="utf-8")
    status_qml = (PACKAGE / "contents/ui/StatusIndicator.qml").read_text(encoding="utf-8")
    section_qml = (PACKAGE / "contents/ui/SectionHeader.qml").read_text(encoding="utf-8")
    resource_qml = (PACKAGE / "contents/ui/ResourceRow.qml").read_text(encoding="utf-8")

    assert "Accessible.role: Accessible.Button" in compact_qml
    assert "Keys.onSpacePressed" in compact_qml
    assert "readonly property string iconName:" in status_qml
    assert "readonly property string statusText:" in status_qml
    assert "Accessible.checked: root.expanded" in section_qml
    assert "Keys.onRightPressed" in section_qml
    assert "Accessible.role: Accessible.ListItem" in resource_qml
    assert "activeFocusOnTab: true" in resource_qml
