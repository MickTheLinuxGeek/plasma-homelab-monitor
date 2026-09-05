pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: root

    required property var docker
    required property bool expanded
    required property bool issuesOnly
    required property string sortMode
    signal expansionRequested(bool value)

    readonly property var environments: root.filteredEnvironments()
    readonly property int itemCount: root.resourceCount()
    readonly property int issueCount: root.countIssues()

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

    function sortResources(items) {
        const result = Array.from(items);
        result.sort(function(left, right) {
            if (root.sortMode === "name") {
                return left.name.localeCompare(right.name);
            }
            const difference = root.statusRank(left.status) - root.statusRank(right.status);
            return difference || left.name.localeCompare(right.name);
        });
        return result;
    }

    function filteredEnvironments() {
        const result = [];
        for (const environment of root.docker.environments) {
            if (!root.issuesOnly || environment.status !== "healthy") {
                result.push(environment);
            }
        }
        return root.sortResources(result);
    }

    function filteredContainers(containers) {
        const result = [];
        for (const container of containers) {
            if (!root.issuesOnly || container.status !== "healthy") {
                result.push(container);
            }
        }
        return root.sortResources(result);
    }

    function resourceCount() {
        let count = root.docker.environments.length;
        for (const environment of root.docker.environments) {
            count += environment.containers.length;
        }
        return count;
    }

    function countIssues() {
        let count = 0;
        for (const environment of root.docker.environments) {
            let environmentIssues = 0;
            for (const container of environment.containers) {
                if (container.status !== "healthy") {
                    environmentIssues++;
                }
            }
            count += environmentIssues > 0
                ? environmentIssues
                : (environment.status !== "healthy" ? 1 : 0);
        }
        if (root.docker.error && count === 0) {
            count = 1;
        }
        return count;
    }

    SectionHeader {
        title: i18n("Docker")
        sectionIcon: "docker"
        expanded: root.expanded
        itemCount: root.itemCount
        issueCount: root.issueCount
        onToggledByUser: root.expansionRequested(!root.expanded)
    }

    ProviderError {
        Layout.leftMargin: Kirigami.Units.largeSpacing
        Layout.rightMargin: Kirigami.Units.smallSpacing
        visible: root.expanded && root.docker.error
        providerName: i18n("Docker")
        errorMessage: root.docker.error || ""
    }

    Repeater {
        model: root.expanded ? root.environments : []

        delegate: ColumnLayout {
            id: environmentColumn

            required property var modelData
            Layout.fillWidth: true
            spacing: 0

            ResourceRow {
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.smallSpacing
                name: environmentColumn.modelData.name
                status: environmentColumn.modelData.status
                detail: i18n("%1 of %2 containers running",
                    environmentColumn.modelData.running,
                    environmentColumn.modelData.total)
            }

            Repeater {
                model: root.filteredContainers(environmentColumn.modelData.containers)

                delegate: ResourceRow {
                    id: containerRow

                    required property var modelData
                    Layout.leftMargin: Kirigami.Units.gridUnit * 2
                    Layout.rightMargin: Kirigami.Units.smallSpacing
                    name: modelData.name
                    status: modelData.status
                    detail: modelData.detail
                }
            }
        }
    }
}
