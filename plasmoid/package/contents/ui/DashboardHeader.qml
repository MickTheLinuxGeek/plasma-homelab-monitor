pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

ColumnLayout {
    id: root

    required property var dashboard
    required property string viewState
    required property string requestActivity
    required property string transportState
    required property string failureMessage
    required property string lastUpdatedAge
    required property bool issuesOnly
    signal refreshRequested
    signal issuesOnlyChangedByUser(bool value)

    readonly property string dashboardStatus: root.dashboard
        ? root.dashboard.overall_status
        : "unknown"
    readonly property string effectiveStatus: {
        if (root.transportState !== "unavailable") {
            return root.dashboardStatus;
        }
        return root.dashboard && root.dashboardStatus === "healthy"
            ? "degraded"
            : "unavailable";
    }
    readonly property string headline: {
        switch (root.viewState) {
        case "loading":
            return i18n("Connecting to collector");
        case "refreshing":
            return i18n("Refreshing dashboard");
        case "stale":
            return i18n("Collector unavailable — data is stale");
        case "collector-unavailable":
            return i18n("Collector unavailable");
        case "partial-failure":
            return i18n("Some providers need attention");
        case "empty":
            return i18n("No monitored resources");
        default:
            return status.statusText;
        }
    }

    spacing: Kirigami.Units.smallSpacing

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        StatusIndicator {
            id: status
            status: root.effectiveStatus
            showLabel: false
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                text: root.headline
                font.bold: true
                wrapMode: Text.Wrap
            }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                text: root.dashboard
                    ? i18n("Updated %1", root.lastUpdatedAge)
                    : i18n("No successful update yet")
                opacity: 0.75
                font: Kirigami.Theme.smallFont
                wrapMode: Text.Wrap
            }
        }

        PlasmaComponents3.BusyIndicator {
            visible: root.requestActivity !== "idle"
            running: visible
            implicitWidth: Kirigami.Units.iconSizes.small
            implicitHeight: implicitWidth
            Accessible.name: root.requestActivity === "loading"
                ? i18n("Loading")
                : i18n("Refreshing")
        }

        PlasmaComponents3.ToolButton {
            id: refreshButton
            icon.name: "view-refresh"
            text: i18n("Refresh dashboard")
            display: QQC2.AbstractButton.IconOnly
            enabled: root.requestActivity === "idle"
            activeFocusOnTab: true
            Accessible.name: text
            Accessible.description: enabled
                ? i18n("Request current status from the collector")
                : i18n("A request is already in progress")
            onClicked: root.refreshRequested()
            PlasmaComponents3.ToolTip.text: text
            PlasmaComponents3.ToolTip.visible: hovered
        }
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        visible: !!root.dashboard
        text: {
            if (!root.dashboard) {
                return "";
            }
            const summary = root.dashboard.summary;
            return i18n("%1 healthy · %2 degraded · %3 unavailable",
                summary.healthy,
                summary.degraded,
                summary.unavailable);
        }
        wrapMode: Text.Wrap
        Accessible.name: text
    }

    RowLayout {
        Layout.fillWidth: true

        PlasmaComponents3.Button {
            id: issuesButton
            checkable: true
            checked: root.issuesOnly
            icon.name: checked ? "view-filter" : "view-filter-symbolic"
            text: i18n("Issues only")
            activeFocusOnTab: true
            Accessible.name: text
            Accessible.description: checked
                ? i18n("Only resources needing attention are shown")
                : i18n("All resources are shown")
            Accessible.checkable: true
            Accessible.checked: checked
            onToggled: root.issuesOnlyChangedByUser(checked)
        }

        Item {
            Layout.fillWidth: true
        }
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        visible: root.viewState === "stale"
            || root.viewState === "collector-unavailable"
            || root.viewState === "partial-failure"
        type: root.viewState === "collector-unavailable"
            ? Kirigami.MessageType.Error
            : Kirigami.MessageType.Warning
        text: {
            if (root.viewState === "stale") {
                return i18n("%1 Showing last-known-good data from %2.",
                    root.failureMessage,
                    root.lastUpdatedAge);
            }
            if (root.viewState === "partial-failure") {
                return i18n("The collector responded, but one or more providers failed or are stale.");
            }
            return root.failureMessage;
        }
    }
}
