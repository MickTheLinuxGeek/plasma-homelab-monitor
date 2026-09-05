pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

ColumnLayout {
    id: root

    required property var docker
    required property bool expanded
    required property bool issuesOnly
    required property string sortMode
    required property var formatAge
    signal expansionRequested(bool value)

    readonly property int maximumEnvironments: 6
    readonly property var matchingEnvironments: root.filteredEnvironments()
    readonly property var environments: root.matchingEnvironments.slice(
        0,
        root.maximumEnvironments)
    readonly property int itemCount: root.resourceCount()
    readonly property int issueCount: root.countIssues()
    readonly property int maximumProjectsPerEnvironment: 6

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

    function freshnessLabel(freshness) {
        switch (freshness) {
        case "fresh":
            return i18n("Fresh");
        case "stale":
            return i18n("Stale");
        default:
            return i18n("Freshness unknown");
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
            if (!root.issuesOnly
                    || environment.status !== "healthy"
                    || root.environmentContainerIssues(environment) > 0) {
                result.push(environment);
            }
        }
        result.sort(function(left, right) {
            if (root.sortMode === "name") {
                return left.name.localeCompare(right.name);
            }
            const leftStatus = root.effectiveEnvironmentStatus(left);
            const rightStatus = root.effectiveEnvironmentStatus(right);
            const difference = root.statusRank(leftStatus) - root.statusRank(rightStatus);
            return difference || left.name.localeCompare(right.name);
        });
        return result;
    }
    function effectiveEnvironmentStatus(environment) {
        if (root.environmentContainerIssues(environment) === 0) {
            return environment.status;
        }
        return root.statusRank(environment.status) < root.statusRank("degraded")
            ? environment.status
            : "degraded";
    }

    function resourceCount() {
        let count = root.docker.environments.length;
        for (const environment of root.docker.environments) {
            count += environment.containers.length;
            count += root.projectsForEnvironment(environment).length;
        }
        return count;
    }
    function environmentContainerIssues(environment) {
        let count = 0;
        for (const container of environment.containers) {
            if (container.status !== "healthy") {
                count++;
            }
        }
        return count;
    }
    function projectsForEnvironment(environment) {
        const groups = {};
        for (const container of environment.containers) {
            const name = container.project || i18n("Ungrouped containers");
            if (!groups[name]) {
                groups[name] = [];
            }
            groups[name].push(container);
        }
        const projects = Object.keys(groups).map(function(name) {
            const containers = groups[name];
            return {
                "name": name,
                "containers": containers,
                "issues": containers.filter(
                    container => container.status !== "healthy").length
            };
        }).filter(function(project) {
            return !root.issuesOnly || project.issues > 0;
        });
        projects.sort(function(left, right) {
            if (root.sortMode === "name") {
                return left.name.localeCompare(right.name);
            }
            return right.issues - left.issues || left.name.localeCompare(right.name);
        });
        return projects;
    }

    function visibleProjects(environment) {
        return root.projectsForEnvironment(environment).slice(
            0,
            root.maximumProjectsPerEnvironment);
    }

    function countIssues() {
        let count = 0;
        for (const environment of root.docker.environments) {
            const environmentIssues = root.environmentContainerIssues(environment);
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

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.largeSpacing
        Layout.rightMargin: Kirigami.Units.smallSpacing
        visible: root.expanded
        text: root.docker.last_success_at
            ? i18n("%1 · last success %2",
                root.freshnessLabel(root.docker.freshness),
                root.formatAge(root.docker.last_success_at))
            : i18n("%1 · no successful observation",
                root.freshnessLabel(root.docker.freshness))
        opacity: 0.75
        font: Kirigami.Theme.smallFont
        wrapMode: Text.Wrap
    }

    ProviderError {
        Layout.leftMargin: Kirigami.Units.largeSpacing
        Layout.rightMargin: Kirigami.Units.smallSpacing
        visible: root.expanded && root.docker.error
        providerName: i18n("Docker")
        providerError: root.docker.error
        lastSuccessAge: root.docker.last_success_at
            ? root.formatAge(root.docker.last_success_at)
            : ""
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
                status: root.effectiveEnvironmentStatus(environmentColumn.modelData)
                detail: i18n("%1 of %2 containers running",
                    environmentColumn.modelData.running,
                    environmentColumn.modelData.total)
                    + (root.docker.last_success_at
                        ? i18n(" · last success %1",
                            root.formatAge(root.docker.last_success_at))
                        : "")
            }

            Repeater {
                model: root.visibleProjects(environmentColumn.modelData)

                delegate: DockerProjectGroup {
                    id: projectGroup

                    required property var modelData
                    Layout.leftMargin: Kirigami.Units.gridUnit * 2
                    Layout.rightMargin: Kirigami.Units.smallSpacing
                    projectName: modelData.name
                    containers: modelData.containers
                    issuesOnly: root.issuesOnly
                    sortMode: root.sortMode
                    formatAge: root.formatAge
                }
            }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.gridUnit * 2
                Layout.rightMargin: Kirigami.Units.smallSpacing
                visible: root.projectsForEnvironment(environmentColumn.modelData).length
                    > root.maximumProjectsPerEnvironment
                text: i18np(
                    "%1 additional Docker project hidden",
                    "%1 additional Docker projects hidden",
                    root.projectsForEnvironment(environmentColumn.modelData).length
                        - root.maximumProjectsPerEnvironment)
                opacity: 0.7
                font: Kirigami.Theme.smallFont
                wrapMode: Text.Wrap
            }
        }
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.largeSpacing
        Layout.rightMargin: Kirigami.Units.smallSpacing
        visible: root.expanded
            && root.matchingEnvironments.length > root.maximumEnvironments
        text: i18np(
            "%1 additional Docker environment hidden",
            "%1 additional Docker environments hidden",
            root.matchingEnvironments.length - root.maximumEnvironments)
        opacity: 0.7
        font: Kirigami.Theme.smallFont
        wrapMode: Text.Wrap
    }
}
