pragma ComponentBehavior: Bound

import QtQuick
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid

PlasmoidItem {
    id: root

    property var dashboard: null
    property bool requestInFlight: false
    property string transportState: "unknown"
    property string failureCategory: ""
    property string failureMessage: ""
    property string lastUpdatedAt: ""
    property string lastSuccessfulConnectionAt: ""
    property int retryAttempt: 0
    property int ageTick: 0
    property bool issuesOnly: Plasmoid.configuration.issuesOnlyByDefault
    property var activeRequest: null

    readonly property int maximumRetryExponent: 5
    readonly property int maximumRetryDelay: 60000
    readonly property string requestActivity: requestInFlight
        ? (dashboard ? "refreshing" : "loading")
        : "idle"
    readonly property string dashboardHealth: dashboard
        ? dashboard.overall_status
        : "unknown"
    readonly property bool dashboardEmpty: dashboard
        && dashboard.hosts.length === 0
        && dashboard.docker.status === "unknown"
        && dashboard.jellyfin.status === "unknown"
    readonly property bool partialFailure: dashboard
        && ((dashboard.errors && dashboard.errors.length > 0)
            || !!dashboard.docker.error
            || !!dashboard.jellyfin.error)
    readonly property bool providerDataStale: dashboard
        && (dashboard.hosts.some(host => host.freshness === "stale")
            || dashboard.docker.freshness === "stale"
            || dashboard.jellyfin.freshness === "stale")
    readonly property string dataFreshness: {
        if (!dashboard) {
            return requestInFlight ? "loading" : "empty";
        }
        return transportState === "unavailable" || providerDataStale ? "stale" : "fresh";
    }
    readonly property string viewState: {
        if (requestInFlight) {
            return dashboard ? "refreshing" : "loading";
        }
        if (transportState === "unavailable") {
            return dashboard ? "stale" : "collector-unavailable";
        }
        if (providerDataStale) {
            return "partial-failure";
        }
        if (dashboardEmpty) {
            return "empty";
        }
        if (partialFailure) {
            return "partial-failure";
        }
        return dashboard ? "fresh" : "empty";
    }
    readonly property string compactStatus: {
        if (transportState === "unavailable") {
            if (!dashboard || dashboardHealth !== "healthy") {
                return "unavailable";
            }
            return "degraded";
        }
        return dashboardHealth;
    }
    readonly property string lastUpdatedAge: humanAge(lastUpdatedAt)

    Plasmoid.icon: "server-database"
    Plasmoid.status: {
        switch (root.compactStatus) {
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
        root.ageTick;
        if (root.transportState === "unavailable") {
            return root.dashboard
                ? i18n("Collector unavailable · showing data from %1", root.lastUpdatedAge)
                : root.failureMessage;
        }
        if (!root.dashboard) {
            return i18n("Waiting for collector");
        }
        const summary = root.dashboard.summary;
        return i18n("%1 healthy · %2 degraded · %3 unavailable · updated %4",
            summary.healthy,
            summary.degraded,
            summary.unavailable,
            root.lastUpdatedAge);
    }

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

    function humanAge(timestamp) {
        root.ageTick;
        if (!timestamp) {
            return i18n("never");
        }
        const observed = new Date(timestamp);
        if (isNaN(observed.getTime())) {
            return i18n("at an unknown time");
        }
        const seconds = Math.max(0, Math.floor((Date.now() - observed.getTime()) / 1000));
        if (seconds < 10) {
            return i18n("just now");
        }
        if (seconds < 60) {
            return i18np("%1 second ago", "%1 seconds ago", seconds);
        }
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) {
            return i18np("%1 minute ago", "%1 minutes ago", minutes);
        }
        const hours = Math.floor(minutes / 60);
        if (hours < 24) {
            return i18np("%1 hour ago", "%1 hours ago", hours);
        }
        const days = Math.floor(hours / 24);
        return i18np("%1 day ago", "%1 days ago", days);
    }

    function endpoint(path) {
        return Plasmoid.configuration.collectorUrl.replace(/\/+$/, "") + path;
    }

    function validProviderState(provider) {
        return provider
            && ["fresh", "stale", "unknown"].includes(provider.freshness)
            && typeof provider.consecutive_failure_count === "number"
            && provider.hasOwnProperty("observed_at")
            && provider.hasOwnProperty("last_success_at")
            && provider.hasOwnProperty("probe_duration_ms")
            && provider.hasOwnProperty("error")
            && (!provider.error
                || (typeof provider.error.category === "string"
                    && typeof provider.error.message === "string"));
    }

    function validStatus(status) {
        return ["healthy", "degraded", "unavailable", "unknown"].includes(status);
    }

    function validDashboardPayload(payload) {
        if (!payload
                || payload.schema_version !== "2"
                || !payload.summary
                || !Array.isArray(payload.hosts)
                || !payload.docker
                || !payload.jellyfin
                || !Array.isArray(payload.docker.environments)
                || !Array.isArray(payload.jellyfin.active_sessions)
                || !Array.isArray(payload.errors)) {
            return false;
        }
        for (const countName of ["healthy", "degraded", "unavailable", "unknown"]) {
            if (typeof payload.summary[countName] !== "number") {
                return false;
            }
        }
        if (!root.validStatus(payload.overall_status)
                || !root.validProviderState(payload.docker)
                || !root.validProviderState(payload.jellyfin)
                || !payload.hosts.every(host =>
                    root.validProviderState(host)
                    && typeof host.id === "string"
                    && typeof host.name === "string"
                    && root.validStatus(host.status))
                || !payload.docker.environments.every(environment =>
                    Array.isArray(environment.containers)
                    && root.validStatus(environment.status)
                    && environment.containers.every(container =>
                        typeof container.name === "string"
                        && root.validStatus(container.status)))) {
            return false;
        }
        return true;
    }

    function scheduleRegularPoll() {
        pollTimer.interval = Math.max(5, Plasmoid.configuration.refreshInterval) * 1000;
        pollTimer.restart();
    }

    function scheduleRetry() {
        root.retryAttempt = Math.min(root.maximumRetryExponent, root.retryAttempt + 1);
        const baseDelay = 2000 * Math.pow(2, root.retryAttempt - 1);
        const jitter = 0.75 + Math.random() * 0.5;
        pollTimer.interval = Math.min(root.maximumRetryDelay, Math.round(baseDelay * jitter));
        pollTimer.restart();
    }

    function completeFailure(request, category, message) {
        if (root.activeRequest !== request) {
            return;
        }
        root.activeRequest = null;
        root.requestInFlight = false;
        root.transportState = "unavailable";
        root.failureCategory = category;
        root.failureMessage = message;
        root.scheduleRetry();
    }

    function completeSuccess(request, payload) {
        if (root.activeRequest !== request) {
            return;
        }
        root.activeRequest = null;
        root.requestInFlight = false;
        root.dashboard = payload;
        root.transportState = "connected";
        root.failureCategory = "";
        root.failureMessage = "";
        root.lastSuccessfulConnectionAt = new Date().toISOString();
        root.lastUpdatedAt = payload.last_successful_observation_at
            || payload.generated_at
            || root.lastSuccessfulConnectionAt;
        root.retryAttempt = 0;
        root.scheduleRegularPoll();
    }

    function refresh() {
        if (root.requestInFlight) {
            return;
        }

        pollTimer.stop();
        root.requestInFlight = true;
        const request = new XMLHttpRequest();
        root.activeRequest = request;
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE || root.activeRequest !== request) {
                return;
            }
            if (request.status < 200 || request.status >= 300) {
                const category = request.status === 0 ? "network" : "http";
                const message = request.status === 0
                    ? i18n("Cannot reach the collector")
                    : i18n("Collector request failed (HTTP %1)", request.status);
                root.completeFailure(request, category, message);
                return;
            }

            try {
                const payload = JSON.parse(request.responseText);
                if (!root.validDashboardPayload(payload)) {
                    throw new Error(i18n("Dashboard response does not match API version 2"));
                }
                root.completeSuccess(request, payload);
            } catch (error) {
                root.completeFailure(
                    request,
                    "invalid-response",
                    i18n("Invalid collector response: %1", error.message));
            }
        };
        request.open("GET", root.endpoint("/api/v2/dashboard"));
        request.timeout = Math.min(
            30000,
            Math.max(5000, Plasmoid.configuration.refreshInterval * 500));
        request.ontimeout = function() {
            root.completeFailure(request, "timeout", i18n("Collector request timed out"));
        };
        request.onerror = function() {
            root.completeFailure(request, "network", i18n("Cannot reach the collector"));
        };
        request.send();
    }

    compactRepresentation: CompactRepresentation {
        plasmoidItem: root
        status: root.compactStatus
        activity: root.requestActivity
        accessibleStatus: root.transportState === "unavailable"
            ? (root.dashboard
                ? i18n("Collector unavailable. Showing stale data from %1.", root.lastUpdatedAge)
                : i18n("Collector unavailable."))
            : i18n("Dashboard status: %1.", root.statusLabel(root.dashboardHealth))
    }

    fullRepresentation: FullRepresentation {
        dashboard: root.dashboard
        viewState: root.viewState
        requestActivity: root.requestActivity
        transportState: root.transportState
        failureCategory: root.failureCategory
        failureMessage: root.failureMessage
        lastUpdatedAge: root.lastUpdatedAge
        lastSuccessfulConnectionAt: root.lastSuccessfulConnectionAt
        issuesOnly: root.issuesOnly
        showHosts: Plasmoid.configuration.showHosts
        showDocker: Plasmoid.configuration.showDocker
        showJellyfin: Plasmoid.configuration.showJellyfin
        hostsExpanded: Plasmoid.configuration.hostsExpanded
        dockerExpanded: Plasmoid.configuration.dockerExpanded
        jellyfinExpanded: Plasmoid.configuration.jellyfinExpanded
        sortMode: Plasmoid.configuration.sortMode
        formatAge: root.humanAge
        onRefreshRequested: root.refresh()
        onIssuesOnlyChangedByUser: value => root.issuesOnly = value
        onHostsExpandedChangedByUser: value => Plasmoid.configuration.hostsExpanded = value
        onDockerExpandedChangedByUser: value => Plasmoid.configuration.dockerExpanded = value
        onJellyfinExpandedChangedByUser: value => Plasmoid.configuration.jellyfinExpanded = value
    }

    Timer {
        id: pollTimer
        repeat: false
        onTriggered: root.refresh()
    }

    Timer {
        interval: 30000
        repeat: true
        running: true
        onTriggered: root.ageTick++
    }

    Component.onCompleted: root.refresh()

    onExpandedChanged: {
        if (root.expanded) {
            root.refresh();
        }
    }
}
