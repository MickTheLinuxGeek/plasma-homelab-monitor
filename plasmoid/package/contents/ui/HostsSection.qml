pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

ColumnLayout {
    id: root

    required property var hosts
    required property bool expanded
    required property bool issuesOnly
    required property string sortMode
    required property var formatAge
    signal expansionRequested(bool value)

    readonly property int issueCount: root.countIssues()
    readonly property int maximumHosts: 8
    readonly property var matchingHosts: root.filteredHosts()
    readonly property var displayHosts: root.matchingHosts.slice(0, root.maximumHosts)

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
            count += root.hostIssueCount(host);
        }
        return count;
    }
    function hostIssueCount(host) {
        let count = host.status !== "healthy" ? 1 : 0;
        if (!host.metrics) {
            return count;
        }
        count += root.metricsIssueCount(host.metrics);
        return count;
    }

    function metricsIssueCount(metrics) {
        let count = 0;
        for (const measurement of metrics.measurements) {
            if (measurement.status !== "healthy") {
                count++;
            }
        }
        if ((metrics.status !== "healthy" || metrics.error) && count === 0) {
            count = 1;
        }
        return count;
    }

    function effectiveHostStatus(host) {
        let status = host.status;
        if (host.metrics
                && root.statusRank(host.metrics.status) < root.statusRank(status)) {
            status = host.metrics.status;
        }
        if (host.metrics) {
            for (const measurement of host.metrics.measurements) {
                if (root.statusRank(measurement.status) < root.statusRank(status)) {
                    status = measurement.status;
                }
            }
        }
        return status;
    }

    function filteredHosts() {
        const result = [];
        for (const host of root.hosts) {
            if (!root.issuesOnly || root.hostIssueCount(host) > 0) {
                result.push(host);
            }
        }
        result.sort(function(left, right) {
            if (root.sortMode === "name") {
                return left.name.localeCompare(right.name);
            }
            const difference = root.statusRank(root.effectiveHostStatus(left))
                - root.statusRank(root.effectiveHostStatus(right));
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

        delegate: ColumnLayout {
            id: hostColumn

            required property var modelData
            Layout.fillWidth: true
            spacing: 0

            ResourceRow {
                Layout.leftMargin: Kirigami.Units.largeSpacing
                Layout.rightMargin: Kirigami.Units.smallSpacing
                name: hostColumn.modelData.name
                status: root.effectiveHostStatus(hostColumn.modelData)
                detail: (hostColumn.modelData.error
                        ? hostColumn.modelData.error.message
                        : hostColumn.modelData.detail)
                    + (hostColumn.modelData.latency_ms !== null
                        ? i18n(" · %1 ms", hostColumn.modelData.latency_ms)
                        : "")
                    + (hostColumn.modelData.certificate_days_remaining !== null
                        ? i18np(
                            " · certificate expires in %1 day",
                            " · certificate expires in %1 days",
                            hostColumn.modelData.certificate_days_remaining)
                        : "")
                    + (hostColumn.modelData.last_success_at
                        ? i18n(" · last success %1",
                            root.formatAge(hostColumn.modelData.last_success_at))
                        : i18n(" · no successful observation"))
                actionUrl: hostColumn.modelData.dashboard_url || ""
            }

            HostMeasurements {
                Layout.leftMargin: Kirigami.Units.gridUnit * 2
                Layout.rightMargin: Kirigami.Units.smallSpacing
                visible: !!hostColumn.modelData.metrics
                    && (!root.issuesOnly
                        || root.metricsIssueCount(hostColumn.modelData.metrics) > 0)
                metrics: hostColumn.modelData.metrics
                issuesOnly: root.issuesOnly
                formatAge: root.formatAge
            }
        }
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.largeSpacing
        Layout.rightMargin: Kirigami.Units.smallSpacing
        visible: root.expanded && root.matchingHosts.length > root.maximumHosts
        text: i18np(
            "%1 additional host hidden",
            "%1 additional hosts hidden",
            root.matchingHosts.length - root.maximumHosts)
        opacity: 0.7
        font: Kirigami.Theme.smallFont
        wrapMode: Text.Wrap
    }
}
