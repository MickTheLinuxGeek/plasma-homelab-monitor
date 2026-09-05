pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

ColumnLayout {
    id: root

    required property string projectName
    required property var containers
    required property bool issuesOnly
    required property string sortMode
    required property var formatAge
    property bool expanded: root.issueCount > 0
    readonly property int maximumContainers: 8
    readonly property int issueCount: root.countIssues()
    readonly property var matchingContainers: root.filteredContainers()
    readonly property var visibleContainers: root.matchingContainers.slice(
        0,
        root.maximumContainers)

    Layout.fillWidth: true
    spacing: 0
    Accessible.role: Accessible.Grouping
    Accessible.name: i18n("Docker project %1", root.projectName)

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
        for (const container of root.containers) {
            if (container.status !== "healthy") {
                count++;
            }
        }
        return count;
    }

    function filteredContainers() {
        const result = root.containers.filter(function(container) {
            return !root.issuesOnly || container.status !== "healthy";
        });
        result.sort(function(left, right) {
            if (root.sortMode === "name") {
                return left.name.localeCompare(right.name);
            }
            const difference = root.statusRank(left.status) - root.statusRank(right.status);
            return difference || left.name.localeCompare(right.name);
        });
        return result;
    }

    function healthText(health) {
        switch (health) {
        case "healthy":
            return i18n("health check healthy");
        case "unhealthy":
            return i18n("health check failing");
        case "starting":
            return i18n("health check starting");
        case "none":
            return i18n("no health check");
        default:
            return i18n("health unknown");
        }
    }

    function containerDetail(container) {
        const parts = [];
        if (container.detail) {
            parts.push(container.detail);
        } else {
            parts.push(i18n("State: %1", container.state));
        }
        parts.push(root.healthText(container.health));
        if (container.health_failing_streak > 0) {
            parts.push(i18np(
                "%1 failing check",
                "%1 failing checks",
                container.health_failing_streak));
        }
        if (container.restarting) {
            parts.push(i18n("restarting"));
        }
        if (container.restart_count !== null && container.restart_count > 0) {
            parts.push(i18np(
                "%1 restart",
                "%1 restarts",
                container.restart_count));
        }
        if (container.oom_killed) {
            parts.push(i18n("out-of-memory kill"));
        }
        if (container.exit_code !== null) {
            parts.push(i18n("exit code %1", container.exit_code));
        }
        if (container.recent_exit && container.finished_at) {
            parts.push(i18n("exited %1", root.formatAge(container.finished_at)));
        }
        if (container.image) {
            parts.push(container.image);
        }
        return parts.join(" · ");
    }

    SectionHeader {
        title: root.projectName
        sectionIcon: "folder-docker"
        expanded: root.expanded
        itemCount: root.containers.length
        issueCount: root.issueCount
        onToggledByUser: root.expanded = !root.expanded
    }

    Repeater {
        model: root.expanded ? root.visibleContainers : []

        delegate: ResourceRow {
            id: containerRow

            required property var modelData
            Layout.leftMargin: Kirigami.Units.largeSpacing
            name: modelData.name
            status: modelData.status
            detail: root.containerDetail(modelData)
        }
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.largeSpacing
        visible: root.expanded
            && root.matchingContainers.length > root.maximumContainers
        text: i18np(
            "%1 additional container hidden",
            "%1 additional containers hidden",
            root.matchingContainers.length - root.maximumContainers)
        opacity: 0.7
        font: Kirigami.Theme.smallFont
        wrapMode: Text.Wrap
    }
}
