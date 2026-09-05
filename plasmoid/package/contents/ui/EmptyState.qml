import QtQuick
import QtQuick.Layouts
import org.kde.plasma.extras as PlasmaExtras

PlasmaExtras.PlaceholderMessage {
    id: root

    required property string viewState
    required property string failureMessage
    property bool filtered: false

    Layout.fillWidth: true
    Layout.margins: 16
    iconName: root.viewState === "collector-unavailable"
        ? "network-disconnect"
        : (root.filtered ? "view-filter" : "server-database")
    text: {
        if (root.viewState === "collector-unavailable") {
            return root.failureMessage || i18n("Collector unavailable");
        }
        if (root.filtered) {
            return i18n("No issues found");
        }
        return i18n("No dashboard data");
    }
    explanation: root.viewState === "collector-unavailable"
        ? i18n("Check the collector URL and service, then refresh.")
        : (root.filtered
            ? i18n("Turn off the issues-only filter to show healthy resources.")
            : i18n("Configure resources in the collector, then refresh."))
    Accessible.name: text
    Accessible.description: explanation
}
