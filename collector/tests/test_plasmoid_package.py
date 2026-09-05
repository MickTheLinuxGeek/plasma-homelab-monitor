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
    assert metadata["KPlugin"]["Version"] == "0.4.0"


def test_required_plasmoid_files_exist() -> None:
    required = [
        "contents/ui/main.qml",
        "contents/ui/CompactRepresentation.qml",
        "contents/ui/FullRepresentation.qml",
        "contents/ui/ConfigGeneral.qml",
        "contents/ui/DashboardHeader.qml",
        "contents/ui/DiagnosticsSection.qml",
        "contents/ui/DockerProjectGroup.qml",
        "contents/ui/DockerSection.qml",
        "contents/ui/EmptyState.qml",
        "contents/ui/HostMeasurements.qml",
        "contents/ui/HostsSection.qml",
        "contents/ui/IncidentTimeline.qml",
        "contents/ui/JellyfinSection.qml",
        "contents/ui/ProviderError.qml",
        "contents/ui/ResourceRow.qml",
        "contents/ui/SectionHeader.qml",
        "contents/ui/StatusIndicator.qml",
        "contents/ui/TrendSparkline.qml",
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
    assert 'root.endpoint("/api/v3/dashboard")' in main_qml
    assert "validProviderState" in main_qml
    assert "hasExactProperties" in main_qml
    assert "validDashboardPayload" in main_qml
    assert 'payload.schema_version !== "3"' in main_qml
    assert "validTimelineEvent" in main_qml
    assert "validTrendSeries" in main_qml
    assert "validFeatures" in main_qml
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


def test_phase_three_views_are_bounded_actionable_and_accessible() -> None:
    timeline_qml = (PACKAGE / "contents/ui/IncidentTimeline.qml").read_text(encoding="utf-8")
    trend_qml = (PACKAGE / "contents/ui/TrendSparkline.qml").read_text(encoding="utf-8")
    measurements_qml = (PACKAGE / "contents/ui/HostMeasurements.qml").read_text(encoding="utf-8")
    project_qml = (PACKAGE / "contents/ui/DockerProjectGroup.qml").read_text(encoding="utf-8")
    full_qml = (PACKAGE / "contents/ui/FullRepresentation.qml").read_text(encoding="utf-8")
    hosts_qml = (PACKAGE / "contents/ui/HostsSection.qml").read_text(encoding="utf-8")
    docker_qml = (PACKAGE / "contents/ui/DockerSection.qml").read_text(encoding="utf-8")

    assert "readonly property int maximumEvents: 6" in timeline_qml
    assert "Number(root.isActive(right))" in timeline_qml
    assert "modelData.parent_event_id === null" in timeline_qml
    assert "Accessible.role: Accessible.ListItem" in timeline_qml
    assert "readonly property int maximumPoints: 24" in trend_qml
    assert "StatusIndicator" in trend_qml
    assert "Accessible.description:" in trend_qml
    assert "readonly property int maximumMeasurements: 6" in measurements_qml
    assert "thresholdText" in measurements_qml
    assert "freshnessText" in measurements_qml
    assert "readonly property int maximumContainers: 8" in project_qml
    assert "health_failing_streak" in project_qml
    assert "oom_killed" in project_qml
    assert "readonly property int maximumHosts: 8" in hosts_qml
    assert "readonly property int maximumEnvironments: 6" in docker_qml
    assert "readonly property int maximumProjectsPerEnvironment: 6" in docker_qml
    assert "IncidentTimeline" in full_qml
    assert full_qml.index("IncidentTimeline") < full_qml.index("HostsSection")
    assert all(
        "XMLHttpRequest" not in component
        for component in (timeline_qml, trend_qml, measurements_qml, project_qml)
    )


def test_widget_explains_collector_owned_notification_and_history_state() -> None:
    config_qml = (PACKAGE / "contents/ui/ConfigGeneral.qml").read_text(encoding="utf-8")
    diagnostics_qml = (PACKAGE / "contents/ui/DiagnosticsSection.qml").read_text(
        encoding="utf-8"
    )

    assert "Notification policy and incident history are owned by the collector" in config_qml
    assert "features.history_enabled" in diagnostics_qml
    assert "features.history_available" in diagnostics_qml
    assert "features.history_retention_days" in diagnostics_qml
    assert "features.notifications_enabled" in diagnostics_qml
