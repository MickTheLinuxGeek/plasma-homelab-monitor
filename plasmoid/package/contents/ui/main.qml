pragma ComponentBehavior: Bound

import QtQuick
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid

PlasmoidItem {
    id: root

    property var dashboard: null
    property bool loading: false
    property string errorMessage: ""
    property string lastUpdated: ""

    readonly property string overallStatus: dashboard
        ? dashboard.overall_status
        : (errorMessage ? "unavailable" : "unknown")

    Plasmoid.icon: "server-database"
    Plasmoid.status: {
        switch (root.overallStatus) {
        case "healthy":
            return PlasmaCore.Types.ActiveStatus;
        case "degraded":
        case "unavailable":
            return PlasmaCore.Types.NeedsAttentionStatus;
        default:
            return PlasmaCore.Types.PassiveStatus;
        }
    }

    toolTipMainText: i18n("Home-lab Monitor")
    toolTipSubText: {
        if (root.errorMessage) {
            return root.errorMessage;
        }
        if (!root.dashboard) {
            return i18n("Waiting for collector");
        }
        const summary = root.dashboard.summary;
        return i18n("%1 healthy · %2 degraded · %3 unavailable",
            summary.healthy,
            summary.degraded,
            summary.unavailable);
    }

    function endpoint() {
        return Plasmoid.configuration.collectorUrl.replace(/\/+$/, "")
            + "/api/v1/dashboard";
    }

    function refresh() {
        if (root.loading) {
            return;
        }

        root.loading = true;
        root.errorMessage = "";
        const request = new XMLHttpRequest();
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) {
                return;
            }

            root.loading = false;
            if (request.status < 200 || request.status >= 300) {
                root.errorMessage = i18n("Collector request failed (HTTP %1)", request.status);
                return;
            }

            try {
                const payload = JSON.parse(request.responseText);
                if (payload.schema_version !== "1") {
                    throw new Error(i18n("Unsupported collector schema"));
                }
                root.dashboard = payload;
                root.lastUpdated = Qt.formatTime(new Date(), Locale.ShortFormat);
            } catch (error) {
                root.errorMessage = i18n("Invalid collector response: %1", error.message);
            }
        };
        request.open("GET", root.endpoint());
        request.timeout = Math.max(5000, Plasmoid.configuration.refreshInterval * 500);
        request.ontimeout = function() {
            root.loading = false;
            root.errorMessage = i18n("Collector request timed out");
        };
        request.onerror = function() {
            root.loading = false;
            root.errorMessage = i18n("Cannot reach the collector");
        };
        request.send();
    }

    compactRepresentation: CompactRepresentation {
        plasmoidItem: root
        status: root.overallStatus
        loading: root.loading
    }

    fullRepresentation: FullRepresentation {
        dashboard: root.dashboard
        loading: root.loading
        errorMessage: root.errorMessage
        lastUpdated: root.lastUpdated
        onRefreshRequested: root.refresh()
    }

    Timer {
        interval: Math.max(5, Plasmoid.configuration.refreshInterval) * 1000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: root.refresh()
    }

    onExpandedChanged: {
        if (root.expanded) {
            root.refresh();
        }
    }
}
