import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

ColumnLayout {
    id: root

    required property var dashboard
    required property string transportState
    required property string lastSuccessfulConnectionAt
    required property string dataAge
    required property string failureCategory

    Layout.fillWidth: true
    Layout.margins: Kirigami.Units.smallSpacing
    spacing: Kirigami.Units.smallSpacing
    Accessible.role: Accessible.Grouping
    Accessible.name: i18n("Diagnostics")

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        text: i18n("Diagnostics")
        font.bold: true
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        text: root.dashboard
            ? i18n("Collector %1 · API %2",
                root.dashboard.collector_version || i18n("unknown"),
                root.dashboard.api_version || root.dashboard.schema_version)
            : i18n("Collector and API versions unavailable")
        wrapMode: Text.Wrap
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        text: root.lastSuccessfulConnectionAt
            ? i18n("Last connection: %1",
                Qt.formatDateTime(new Date(root.lastSuccessfulConnectionAt), Locale.ShortFormat))
            : i18n("Last connection: never")
        wrapMode: Text.Wrap
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        text: i18n("Data age: %1", root.dataAge)
        wrapMode: Text.Wrap
    }
    PlasmaComponents3.Label {
        Layout.fillWidth: true
        visible: !!root.dashboard
        text: {
            if (!root.dashboard) {
                return "";
            }
            const features = root.dashboard.features;
            if (!features.history_enabled) {
                return i18n("Collector history: disabled");
            }
            if (!features.history_available) {
                return i18n("Collector history: enabled but unavailable");
            }
            return i18np(
                "Collector history: available · %1-day retention",
                "Collector history: available · %1-day retention",
                features.history_retention_days);
        }
        wrapMode: Text.Wrap
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        visible: !!root.dashboard
        text: root.dashboard && root.dashboard.features.notifications_enabled
            ? i18n("Collector notifications: enabled")
            : i18n("Collector notifications: disabled")
        wrapMode: Text.Wrap
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        visible: !!root.dashboard
        text: i18n("Notification policy and incident history are owned by the collector.")
        opacity: 0.75
        font: Kirigami.Theme.smallFont
        wrapMode: Text.Wrap
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        visible: root.failureCategory.length > 0
        text: i18n("Failure category: %1", root.failureCategory)
        color: Kirigami.Theme.negativeTextColor
        wrapMode: Text.Wrap
    }
}
