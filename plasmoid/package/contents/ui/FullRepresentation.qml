pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.extras as PlasmaExtras

PlasmaExtras.Representation {
    id: root

    required property var dashboard
    required property string viewState
    required property string requestActivity
    required property string transportState
    required property string failureCategory
    required property string failureMessage
    required property string lastUpdatedAge
    required property string lastSuccessfulConnectionAt
    required property bool issuesOnly
    required property bool showHosts
    required property bool showDocker
    required property bool showJellyfin
    required property bool hostsExpanded
    required property bool dockerExpanded
    required property bool jellyfinExpanded
    required property string sortMode

    signal refreshRequested
    signal issuesOnlyChangedByUser(bool value)
    signal hostsExpandedChangedByUser(bool value)
    signal dockerExpandedChangedByUser(bool value)
    signal jellyfinExpandedChangedByUser(bool value)

    property bool hostsAutoExpanded: false
    property bool dockerAutoExpanded: false
    property bool jellyfinAutoExpanded: false
    property int previousHostsIssues: -1
    property int previousDockerIssues: -1
    property int previousJellyfinIssues: -1

    readonly property bool effectiveHostsExpanded: root.hostsExpanded
        || root.hostsAutoExpanded
    readonly property bool effectiveDockerExpanded: root.dockerExpanded
        || root.dockerAutoExpanded
    readonly property bool effectiveJellyfinExpanded: root.jellyfinExpanded
        || root.jellyfinAutoExpanded
    readonly property int totalVisibleIssues: (root.showHosts ? hostsSection.issueCount : 0)
        + (root.showDocker ? dockerSection.issueCount : 0)
        + (root.showJellyfin ? jellyfinSection.issueCount : 0)
    readonly property bool hasConfiguredSections: root.dashboard
        && ((root.showHosts && root.dashboard.hosts.length > 0)
            || (root.showDocker && root.dashboard.docker.status !== "unknown")
            || (root.showJellyfin && root.dashboard.jellyfin.status !== "unknown"))

    Layout.minimumWidth: Kirigami.Units.gridUnit * 18
    Layout.minimumHeight: Kirigami.Units.gridUnit * 16
    Layout.preferredWidth: Kirigami.Units.gridUnit * 27
    Layout.preferredHeight: Kirigami.Units.gridUnit * 32
    collapseMarginsHint: true
    LayoutMirroring.enabled: root.mirrored
    LayoutMirroring.childrenInherit: true

    function updateAutomaticExpansion() {
        const hostIssues = hostsSection.issueCount;
        const dockerIssues = dockerSection.issueCount;
        const jellyfinIssues = jellyfinSection.issueCount;

        if (hostIssues > 0 && root.previousHostsIssues <= 0) {
            root.hostsAutoExpanded = true;
        } else if (hostIssues === 0) {
            root.hostsAutoExpanded = false;
        }
        if (dockerIssues > 0 && root.previousDockerIssues <= 0) {
            root.dockerAutoExpanded = true;
        } else if (dockerIssues === 0) {
            root.dockerAutoExpanded = false;
        }
        if (jellyfinIssues > 0 && root.previousJellyfinIssues <= 0) {
            root.jellyfinAutoExpanded = true;
        } else if (jellyfinIssues === 0) {
            root.jellyfinAutoExpanded = false;
        }

        root.previousHostsIssues = hostIssues;
        root.previousDockerIssues = dockerIssues;
        root.previousJellyfinIssues = jellyfinIssues;
    }

    function changeHostsExpansion(value) {
        root.hostsAutoExpanded = false;
        root.hostsExpandedChangedByUser(value);
    }

    function changeDockerExpansion(value) {
        root.dockerAutoExpanded = false;
        root.dockerExpandedChangedByUser(value);
    }

    function changeJellyfinExpansion(value) {
        root.jellyfinAutoExpanded = false;
        root.jellyfinExpandedChangedByUser(value);
    }

    onDashboardChanged: Qt.callLater(root.updateAutomaticExpansion)

    header: PlasmaExtras.PlasmoidHeading {
        contentItem: DashboardHeader {
            dashboard: root.dashboard
            viewState: root.viewState
            requestActivity: root.requestActivity
            transportState: root.transportState
            failureMessage: root.failureMessage
            lastUpdatedAge: root.lastUpdatedAge
            issuesOnly: root.issuesOnly
            onRefreshRequested: root.refreshRequested()
            onIssuesOnlyChangedByUser: value => root.issuesOnlyChangedByUser(value)
        }
    }

    contentItem: Flickable {
        id: flickable

        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentWidth: width
        contentHeight: contentColumn.implicitHeight
        activeFocusOnTab: true
        Accessible.role: Accessible.Pane
        Accessible.name: i18n("Home-lab dashboard")

        ColumnLayout {
            id: contentColumn

            width: flickable.width
            spacing: Kirigami.Units.smallSpacing

            EmptyState {
                visible: (!root.dashboard && root.requestActivity !== "loading")
                    || (root.dashboard && !root.hasConfiguredSections)
                    || (root.dashboard && root.issuesOnly && root.totalVisibleIssues === 0)
                viewState: root.viewState
                failureMessage: root.failureMessage
                filtered: !!root.dashboard
                    && root.issuesOnly
                    && root.totalVisibleIssues === 0
            }

            HostsSection {
                id: hostsSection
                visible: !!root.dashboard
                    && root.showHosts
                    && root.dashboard.hosts.length > 0
                    && (!root.issuesOnly || issueCount > 0)
                hosts: root.dashboard ? root.dashboard.hosts : []
                expanded: root.effectiveHostsExpanded
                issuesOnly: root.issuesOnly
                sortMode: root.sortMode
                onExpansionRequested: value => root.changeHostsExpansion(value)
            }

            DockerSection {
                id: dockerSection
                visible: !!root.dashboard
                    && root.showDocker
                    && root.dashboard.docker.status !== "unknown"
                    && (!root.issuesOnly || issueCount > 0)
                docker: root.dashboard
                    ? root.dashboard.docker
                    : ({
                        "status": "unknown",
                        "environments": [],
                        "error": ""
                    })
                expanded: root.effectiveDockerExpanded
                issuesOnly: root.issuesOnly
                sortMode: root.sortMode
                onExpansionRequested: value => root.changeDockerExpansion(value)
            }

            JellyfinSection {
                id: jellyfinSection
                visible: !!root.dashboard
                    && root.showJellyfin
                    && root.dashboard.jellyfin.status !== "unknown"
                    && (!root.issuesOnly || issueCount > 0)
                jellyfin: root.dashboard
                    ? root.dashboard.jellyfin
                    : ({
                        "status": "unknown",
                        "server_name": "",
                        "version": "",
                        "active_sessions": [],
                        "dashboard_url": "",
                        "error": ""
                    })
                expanded: root.effectiveJellyfinExpanded
                issuesOnly: root.issuesOnly
                onExpansionRequested: value => root.changeJellyfinExpansion(value)
            }

            Kirigami.Separator {
                Layout.fillWidth: true
                visible: !!root.dashboard || root.failureCategory.length > 0
            }

            DiagnosticsSection {
                visible: !!root.dashboard || root.failureCategory.length > 0
                dashboard: root.dashboard
                transportState: root.transportState
                lastSuccessfulConnectionAt: root.lastSuccessfulConnectionAt
                dataAge: root.lastUpdatedAge
                failureCategory: root.failureCategory
            }
        }

        PlasmaComponents3.ScrollBar.vertical: PlasmaComponents3.ScrollBar {
            policy: PlasmaComponents3.ScrollBar.AsNeeded
        }
    }
}
