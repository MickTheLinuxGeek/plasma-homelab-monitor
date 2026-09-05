pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: root

    required property var hosts
    required property bool expanded
    required property bool issuesOnly
    required property string sortMode
    signal expansionRequested(bool value)

    readonly property int issueCount: root.countIssues()
    readonly property var displayHosts: root.filteredHosts()

    Layout.fillWidth: true
    spacing: 0

    function statusRank(status) {
        switch (status) {
        case "unavailable":
            return 0;
        case "degraded":
            return 1;
        case "unknown":
            return 2;
        default:
            return 3;
        }
    }

    function countIssues() {
        let count = 0;
        for (const host of root.hosts) {
            if (host.status !== "healthy") {
                count++;
            }
        }
        return count;
    }

    function filteredHosts() {
        const result = [];
        for (const host of root.hosts) {
            if (!root.issuesOnly || host.status !== "healthy") {
                result.push(host);
            }
        }
        result.sort(function(left, right) {
            if (root.sortMode === "name") {
                return left.name.localeCompare(right.name);
            }
            const difference = root.statusRank(left.status) - root.statusRank(right.status);
            return difference || left.name.localeCompare(right.name);
        });
        return result;
    }

    SectionHeader {
        title: i18n("Hosts")
        sectionIcon: "computer"
        expanded: root.expanded
        itemCount: root.hosts.length
        issueCount: root.issueCount
        onToggledByUser: root.expansionRequested(!root.expanded)
    }

    Repeater {
        model: root.expanded ? root.displayHosts : []

        delegate: ResourceRow {
            id: hostRow

            required property var modelData
            Layout.leftMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.smallSpacing
            name: modelData.name
            status: modelData.status
            detail: modelData.detail
                + (modelData.latency_ms !== null
                    ? i18n(" · %1 ms", modelData.latency_ms)
                    : "")
            actionUrl: modelData.dashboard_url || ""
        }
    }
}
