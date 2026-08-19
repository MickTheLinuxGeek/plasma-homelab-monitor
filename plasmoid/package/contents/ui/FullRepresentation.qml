pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.extras as PlasmaExtras

PlasmaExtras.Representation {
    id: root

    required property var dashboard
    required property bool loading
    required property string errorMessage
    required property string lastUpdated
    signal refreshRequested

    property bool hostsExpanded: true
    property bool dockerExpanded: true
    property bool jellyfinExpanded: true

    Layout.minimumWidth: Kirigami.Units.gridUnit * 20
    Layout.minimumHeight: Kirigami.Units.gridUnit * 18
    Layout.preferredWidth: Kirigami.Units.gridUnit * 25
    Layout.preferredHeight: Kirigami.Units.gridUnit * 30
    collapseMarginsHint: true

    function statusLabel(status) {
        switch (status) {
        case "healthy":
            return i18n("Healthy");
        case "degraded":
            return i18n("Needs attention");
        case "unavailable":
            return i18n("Unavailable");
        default:
            return i18n("Unknown");
        }
    }

    header: PlasmaExtras.PlasmoidHeading {
        contentItem: RowLayout {
            spacing: Kirigami.Units.smallSpacing

            StatusDot {
                status: root.dashboard ? root.dashboard.overall_status : "unknown"
            }

            ColumnLayout {
                spacing: 0
                Layout.fillWidth: true

                PlasmaComponents3.Label {
                    text: i18n("Home-lab Monitor")
                    font.bold: true
                }

                PlasmaComponents3.Label {
                    text: root.dashboard
                        ? root.statusLabel(root.dashboard.overall_status)
                        : i18n("Waiting for collector")
                    opacity: 0.7
                    font: Kirigami.Theme.smallFont
                }
            }

            PlasmaComponents3.BusyIndicator {
                visible: root.loading
                running: root.loading
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: implicitWidth
            }

            PlasmaComponents3.ToolButton {
                icon.name: "view-refresh"
                text: i18n("Refresh")
                display: QQC2.AbstractButton.IconOnly
                enabled: !root.loading
                onClicked: root.refreshRequested()
                PlasmaComponents3.ToolTip.text: text
                PlasmaComponents3.ToolTip.visible: hovered
            }
        }
    }

    contentItem: Flickable {
        id: flickable

        clip: true
        contentWidth: width
        contentHeight: contentColumn.implicitHeight

        ColumnLayout {
            id: contentColumn

            width: flickable.width
            spacing: Kirigami.Units.smallSpacing

            PlasmaExtras.PlaceholderMessage {
                Layout.fillWidth: true
                Layout.margins: Kirigami.Units.largeSpacing
                visible: !root.dashboard && !root.loading
                iconName: root.errorMessage ? "network-disconnect" : "server-database"
                text: root.errorMessage || i18n("No dashboard data")
                explanation: i18n("Start the collector, then refresh this widget.")
            }

            PlasmaComponents3.ToolButton {
                Layout.fillWidth: true
                visible: !!root.dashboard
                text: (root.hostsExpanded ? "▾ " : "▸ ") + i18n("Hosts")
                icon.name: "computer"
                display: QQC2.AbstractButton.TextBesideIcon
                onClicked: root.hostsExpanded = !root.hostsExpanded
            }

            Repeater {
                model: root.dashboard && root.hostsExpanded ? root.dashboard.hosts : []

                delegate: Item {
                    id: hostRow

                    required property var modelData
                    Layout.fillWidth: true
                    Layout.leftMargin: Kirigami.Units.largeSpacing
                    Layout.rightMargin: Kirigami.Units.largeSpacing
                    implicitHeight: hostLayout.implicitHeight + Kirigami.Units.smallSpacing

                    RowLayout {
                        id: hostLayout
                        anchors.fill: parent
                        spacing: Kirigami.Units.smallSpacing

                        StatusDot {
                            status: hostRow.modelData.status
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0

                            PlasmaComponents3.Label {
                                Layout.fillWidth: true
                                text: hostRow.modelData.name
                                elide: Text.ElideRight
                            }

                            PlasmaComponents3.Label {
                                Layout.fillWidth: true
                                text: hostRow.modelData.detail
                                    + (hostRow.modelData.latency_ms
                                        ? " · " + hostRow.modelData.latency_ms + " ms"
                                        : "")
                                opacity: 0.7
                                font: Kirigami.Theme.smallFont
                                elide: Text.ElideRight
                            }
                        }

                        PlasmaComponents3.ToolButton {
                            visible: !!hostRow.modelData.dashboard_url
                            icon.name: "internet-web-browser"
                            text: i18n("Open dashboard")
                            display: QQC2.AbstractButton.IconOnly
                            onClicked: Qt.openUrlExternally(hostRow.modelData.dashboard_url)
                            PlasmaComponents3.ToolTip.text: text
                            PlasmaComponents3.ToolTip.visible: hovered
                        }
                    }
                }
            }

            PlasmaComponents3.ToolButton {
                Layout.fillWidth: true
                visible: !!root.dashboard && root.dashboard.docker.status !== "unknown"
                text: (root.dockerExpanded ? "▾ " : "▸ ") + i18n("Docker")
                icon.name: "docker"
                display: QQC2.AbstractButton.TextBesideIcon
                onClicked: root.dockerExpanded = !root.dockerExpanded
            }

            Repeater {
                model: root.dashboard && root.dockerExpanded
                    ? root.dashboard.docker.environments
                    : []

                delegate: ColumnLayout {
                    id: environment

                    required property var modelData
                    Layout.fillWidth: true
                    Layout.leftMargin: Kirigami.Units.largeSpacing
                    Layout.rightMargin: Kirigami.Units.largeSpacing
                    spacing: Kirigami.Units.smallSpacing / 2

                    RowLayout {
                        Layout.fillWidth: true

                        StatusDot {
                            status: environment.modelData.status
                        }

                        PlasmaComponents3.Label {
                            Layout.fillWidth: true
                            text: environment.modelData.name
                            font.bold: true
                            elide: Text.ElideRight
                        }

                        PlasmaComponents3.Label {
                            text: i18n("%1/%2 running",
                                environment.modelData.running,
                                environment.modelData.total)
                            opacity: 0.7
                            font: Kirigami.Theme.smallFont
                        }
                    }

                    Repeater {
                        model: environment.modelData.containers

                        delegate: RowLayout {
                            id: containerRow

                            required property var modelData
                            Layout.fillWidth: true
                            Layout.leftMargin: Kirigami.Units.largeSpacing

                            StatusDot {
                                status: containerRow.modelData.status
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0

                                PlasmaComponents3.Label {
                                    Layout.fillWidth: true
                                    text: containerRow.modelData.name
                                    elide: Text.ElideRight
                                }

                                PlasmaComponents3.Label {
                                    Layout.fillWidth: true
                                    text: containerRow.modelData.detail
                                    opacity: 0.7
                                    font: Kirigami.Theme.smallFont
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }
            }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.largeSpacing
                visible: !!root.dashboard && !!root.dashboard.docker.error
                text: root.dashboard ? root.dashboard.docker.error || "" : ""
                color: Kirigami.Theme.negativeTextColor
                wrapMode: Text.WordWrap
                font: Kirigami.Theme.smallFont
            }

            PlasmaComponents3.ToolButton {
                Layout.fillWidth: true
                visible: !!root.dashboard && root.dashboard.jellyfin.status !== "unknown"
                text: (root.jellyfinExpanded ? "▾ " : "▸ ") + i18n("Jellyfin")
                icon.name: "jellyfin"
                display: QQC2.AbstractButton.TextBesideIcon
                onClicked: root.jellyfinExpanded = !root.jellyfinExpanded
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.largeSpacing
                visible: !!root.dashboard && root.jellyfinExpanded

                RowLayout {
                    Layout.fillWidth: true

                    StatusDot {
                        status: root.dashboard ? root.dashboard.jellyfin.status : "unknown"
                    }

                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        text: root.dashboard
                            ? root.dashboard.jellyfin.server_name || i18n("Jellyfin")
                            : i18n("Jellyfin")
                    }

                    PlasmaComponents3.Label {
                        text: root.dashboard ? root.dashboard.jellyfin.version : ""
                        opacity: 0.7
                        font: Kirigami.Theme.smallFont
                    }

                    PlasmaComponents3.ToolButton {
                        visible: !!root.dashboard && !!root.dashboard.jellyfin.dashboard_url
                        icon.name: "internet-web-browser"
                        text: i18n("Open Jellyfin")
                        display: QQC2.AbstractButton.IconOnly
                        onClicked: Qt.openUrlExternally(root.dashboard.jellyfin.dashboard_url)
                        PlasmaComponents3.ToolTip.text: text
                        PlasmaComponents3.ToolTip.visible: hovered
                    }
                }

                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    visible: !!root.dashboard
                        && root.dashboard.jellyfin.active_sessions.length === 0
                        && !root.dashboard.jellyfin.error
                    text: i18n("Nothing is playing")
                    opacity: 0.7
                    font: Kirigami.Theme.smallFont
                }

                Repeater {
                    model: root.dashboard
                        ? root.dashboard.jellyfin.active_sessions
                        : []

                    delegate: ColumnLayout {
                        id: sessionRow

                        required property var modelData
                        Layout.fillWidth: true
                        Layout.leftMargin: Kirigami.Units.largeSpacing
                        spacing: 0

                        PlasmaComponents3.Label {
                            Layout.fillWidth: true
                            text: sessionRow.modelData.item_name
                            elide: Text.ElideRight
                        }

                        PlasmaComponents3.Label {
                            Layout.fillWidth: true
                            text: i18n("%1 · %2 on %3",
                                sessionRow.modelData.user_name,
                                sessionRow.modelData.client,
                                sessionRow.modelData.device_name)
                            opacity: 0.7
                            font: Kirigami.Theme.smallFont
                            elide: Text.ElideRight
                        }
                    }
                }

                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    visible: !!root.dashboard && !!root.dashboard.jellyfin.error
                    text: root.dashboard ? root.dashboard.jellyfin.error || "" : ""
                    color: Kirigami.Theme.negativeTextColor
                    wrapMode: Text.WordWrap
                    font: Kirigami.Theme.smallFont
                }
            }
        }

        PlasmaComponents3.ScrollBar.vertical: PlasmaComponents3.ScrollBar {}
    }

    footer: PlasmaExtras.PlasmoidHeading {
        visible: !!root.errorMessage || !!root.lastUpdated
        contentItem: PlasmaComponents3.Label {
            text: root.errorMessage
                ? root.errorMessage
                : i18n("Updated %1", root.lastUpdated)
            color: root.errorMessage
                ? Kirigami.Theme.negativeTextColor
                : Kirigami.Theme.textColor
            opacity: root.errorMessage ? 1 : 0.7
            font: Kirigami.Theme.smallFont
            elide: Text.ElideRight
        }
    }
}
