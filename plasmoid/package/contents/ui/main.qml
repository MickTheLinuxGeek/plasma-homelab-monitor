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

    function isObject(value) {
        return value !== null && typeof value === "object" && !Array.isArray(value);
    }

    function hasExactProperties(value, properties) {
        if (!root.isObject(value)) {
            return false;
        }
        const actual = Object.keys(value).sort();
        const expected = Array.from(properties).sort();
        return actual.length === expected.length
            && actual.every((name, index) => name === expected[index]);
    }

    function validTimestamp(value) {
        return typeof value === "string"
            && value.length > 0
            && !isNaN(Date.parse(value));
    }

    function validNullableTimestamp(value) {
        return value === null || root.validTimestamp(value);
    }

    function validNullableString(value) {
        return value === null || typeof value === "string";
    }

    function validNullableInteger(value) {
        return value === null || Number.isInteger(value);
    }

    function validErrorCategory(category) {
        return [
            "timeout",
            "tls",
            "authentication",
            "dns",
            "connection",
            "malformed_response",
            "unexpected"
        ].includes(category);
    }

    function validProviderError(error) {
        return error === null
            || (root.hasExactProperties(error, ["category", "message"])
                && root.validErrorCategory(error.category)
                && typeof error.message === "string"
                && error.message.length > 0);
    }

    function validProviderState(provider) {
        return root.isObject(provider)
            && ["fresh", "stale", "unknown"].includes(provider.freshness)
            && Number.isInteger(provider.consecutive_failure_count)
            && provider.consecutive_failure_count >= 0
            && root.validNullableTimestamp(provider.observed_at)
            && root.validNullableTimestamp(provider.last_success_at)
            && root.validNullableInteger(provider.probe_duration_ms)
            && (provider.probe_duration_ms === null || provider.probe_duration_ms >= 0)
            && root.validProviderError(provider.error);
    }

    function validStatus(status) {
        return ["healthy", "degraded", "unavailable", "unknown"].includes(status);
    }
    function validThreshold(threshold) {
        return root.hasExactProperties(
                threshold,
                ["direction", "warning", "critical", "sustained_samples"])
            && ["above", "below", "categorical"].includes(threshold.direction)
            && (threshold.warning === null || typeof threshold.warning === "number")
            && (threshold.critical === null || typeof threshold.critical === "number")
            && Number.isInteger(threshold.sustained_samples)
            && threshold.sustained_samples >= 1;
    }

    function validMeasurement(measurement) {
        const valueType = typeof measurement.value;
        return root.hasExactProperties(measurement, [
                "id",
                "label",
                "kind",
                "status",
                "value",
                "unit",
                "detail",
                "thresholds",
                "observed_at",
                "freshness"
            ])
            && typeof measurement.id === "string"
            && typeof measurement.label === "string"
            && typeof measurement.kind === "string"
            && root.validStatus(measurement.status)
            && (measurement.value === null
                || valueType === "number"
                || valueType === "string"
                || valueType === "boolean")
            && root.validNullableString(measurement.unit)
            && typeof measurement.detail === "string"
            && (measurement.thresholds === null
                || root.validThreshold(measurement.thresholds))
            && root.validNullableTimestamp(measurement.observed_at)
            && ["fresh", "stale", "unknown"].includes(measurement.freshness);
    }

    function validHostMetrics(metrics) {
        return root.hasExactProperties(metrics, [
                "status",
                "measurements",
                "boot_id",
                "observed_at",
                "last_success_at",
                "consecutive_failure_count",
                "probe_duration_ms",
                "freshness",
                "error"
            ])
            && root.validStatus(metrics.status)
            && Array.isArray(metrics.measurements)
            && metrics.measurements.every(root.validMeasurement)
            && root.validNullableString(metrics.boot_id)
            && root.validProviderState(metrics);
    }

    function validHost(host) {
        return root.hasExactProperties(host, [
                "id",
                "name",
                "status",
                "detail",
                "dashboard_url",
                "latency_ms",
                "observed_at",
                "last_success_at",
                "consecutive_failure_count",
                "probe_duration_ms",
                "freshness",
                "error",
                "certificate_expires_at",
                "certificate_days_remaining",
                "metrics"
            ])
            && typeof host.id === "string"
            && typeof host.name === "string"
            && root.validStatus(host.status)
            && typeof host.detail === "string"
            && root.validNullableString(host.dashboard_url)
            && root.validNullableInteger(host.latency_ms)
            && (host.latency_ms === null || host.latency_ms >= 0)
            && root.validNullableTimestamp(host.certificate_expires_at)
            && root.validNullableInteger(host.certificate_days_remaining)
            && (host.metrics === null || root.validHostMetrics(host.metrics))
            && root.validProviderState(host);
    }

    function validContainer(container) {
        return root.hasExactProperties(container, [
                "id",
                "name",
                "image",
                "state",
                "status",
                "detail",
                "health",
                "health_failing_streak",
                "restart_count",
                "restarting",
                "oom_killed",
                "exit_code",
                "started_at",
                "finished_at",
                "recent_exit",
                "project"
            ])
            && typeof container.id === "string"
            && typeof container.name === "string"
            && typeof container.image === "string"
            && typeof container.state === "string"
            && root.validStatus(container.status)
            && typeof container.detail === "string"
            && ["none", "starting", "healthy", "unhealthy", "unknown"].includes(container.health)
            && Number.isInteger(container.health_failing_streak)
            && container.health_failing_streak >= 0
            && root.validNullableInteger(container.restart_count)
            && (container.restart_count === null || container.restart_count >= 0)
            && typeof container.restarting === "boolean"
            && typeof container.oom_killed === "boolean"
            && root.validNullableInteger(container.exit_code)
            && root.validNullableTimestamp(container.started_at)
            && root.validNullableTimestamp(container.finished_at)
            && typeof container.recent_exit === "boolean"
            && root.validNullableString(container.project);
    }

    function validEnvironment(environment) {
        return root.hasExactProperties(environment, [
                "id",
                "name",
                "status",
                "running",
                "stopped",
                "total",
                "containers",
                "host_id"
            ])
            && Number.isInteger(environment.id)
            && typeof environment.name === "string"
            && root.validStatus(environment.status)
            && Number.isInteger(environment.running)
            && environment.running >= 0
            && Number.isInteger(environment.stopped)
            && environment.stopped >= 0
            && Number.isInteger(environment.total)
            && environment.total >= 0
            && Array.isArray(environment.containers)
            && environment.containers.every(root.validContainer)
            && root.validNullableString(environment.host_id);
    }

    function validDocker(docker) {
        return root.hasExactProperties(docker, [
                "status",
                "environments",
                "observed_at",
                "last_success_at",
                "consecutive_failure_count",
                "probe_duration_ms",
                "freshness",
                "error"
            ])
            && root.validStatus(docker.status)
            && Array.isArray(docker.environments)
            && docker.environments.every(root.validEnvironment)
            && root.validProviderState(docker);
    }

    function validSession(session) {
        return root.hasExactProperties(
                session,
                ["user_name", "client", "device_name", "item_name"])
            && typeof session.user_name === "string"
            && typeof session.client === "string"
            && typeof session.device_name === "string"
            && typeof session.item_name === "string";
    }

    function validJellyfin(jellyfin) {
        return root.hasExactProperties(jellyfin, [
                "status",
                "server_name",
                "version",
                "active_sessions",
                "dashboard_url",
                "observed_at",
                "last_success_at",
                "consecutive_failure_count",
                "probe_duration_ms",
                "freshness",
                "error"
            ])
            && root.validStatus(jellyfin.status)
            && typeof jellyfin.server_name === "string"
            && typeof jellyfin.version === "string"
            && Array.isArray(jellyfin.active_sessions)
            && jellyfin.active_sessions.every(root.validSession)
            && root.validNullableString(jellyfin.dashboard_url)
            && root.validProviderState(jellyfin);
    }

    function validSourceError(error) {
        return root.hasExactProperties(error, ["source", "category", "message", "observed_at"])
            && typeof error.source === "string"
            && root.validErrorCategory(error.category)
            && typeof error.message === "string"
            && root.validTimestamp(error.observed_at);
    }

    function validTimelineEvent(event) {
        return root.hasExactProperties(event, [
                "id",
                "resource_id",
                "resource_name",
                "event_type",
                "severity",
                "message",
                "occurred_at",
                "previous_status",
                "current_status",
                "incident_id",
                "parent_event_id",
                "recovered_at"
            ])
            && Number.isInteger(event.id)
            && event.id >= 1
            && typeof event.resource_id === "string"
            && typeof event.resource_name === "string"
            && typeof event.event_type === "string"
            && ["info", "warning", "critical"].includes(event.severity)
            && typeof event.message === "string"
            && root.validTimestamp(event.occurred_at)
            && (event.previous_status === null || root.validStatus(event.previous_status))
            && (event.current_status === null || root.validStatus(event.current_status))
            && root.validNullableInteger(event.incident_id)
            && (event.incident_id === null || event.incident_id >= 1)
            && root.validNullableInteger(event.parent_event_id)
            && (event.parent_event_id === null || event.parent_event_id >= 1)
            && root.validNullableTimestamp(event.recovered_at);
    }

    function validTrendSeries(series) {
        return root.hasExactProperties(
                series,
                ["resource_id", "label", "metric", "unit", "points"])
            && typeof series.resource_id === "string"
            && typeof series.label === "string"
            && typeof series.metric === "string"
            && root.validNullableString(series.unit)
            && Array.isArray(series.points)
            && series.points.every(function(point) {
                return root.hasExactProperties(point, ["observed_at", "status", "value"])
                    && root.validTimestamp(point.observed_at)
                    && root.validStatus(point.status)
                    && (point.value === null || typeof point.value === "number");
            });
    }

    function validFeatures(features) {
        return root.hasExactProperties(features, [
                "history_enabled",
                "history_available",
                "history_retention_days",
                "notifications_enabled"
            ])
            && typeof features.history_enabled === "boolean"
            && typeof features.history_available === "boolean"
            && Number.isInteger(features.history_retention_days)
            && features.history_retention_days >= 0
            && typeof features.notifications_enabled === "boolean";
    }

    function validDashboardPayload(payload) {
        if (!root.hasExactProperties(payload, [
                "schema_version",
                "api_version",
                "collector_version",
                "generated_at",
                "last_successful_observation_at",
                "overall_status",
                "summary",
                "hosts",
                "docker",
                "jellyfin",
                "errors",
                "recent_events",
                "trends",
                "features"
            ])
                || payload.schema_version !== "3"
                || payload.api_version !== "3"
                || typeof payload.collector_version !== "string"
                || !root.validTimestamp(payload.generated_at)
                || !root.validNullableTimestamp(payload.last_successful_observation_at)
                || !root.hasExactProperties(
                    payload.summary,
                    ["healthy", "degraded", "unavailable", "unknown"])
                || !Array.isArray(payload.hosts)
                || !Array.isArray(payload.errors)
                || !Array.isArray(payload.recent_events)
                || !Array.isArray(payload.trends)) {
            return false;
        }
        for (const countName of ["healthy", "degraded", "unavailable", "unknown"]) {
            if (!Number.isInteger(payload.summary[countName])
                    || payload.summary[countName] < 0) {
                return false;
            }
        }
        if (!root.validStatus(payload.overall_status)
                || !payload.hosts.every(root.validHost)
                || !root.validDocker(payload.docker)
                || !root.validJellyfin(payload.jellyfin)
                || !payload.errors.every(root.validSourceError)
                || !payload.recent_events.every(root.validTimelineEvent)
                || !payload.trends.every(root.validTrendSeries)
                || !root.validFeatures(payload.features)) {
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
                    throw new Error(i18n("Dashboard response does not match API version 3"));
                }
                root.completeSuccess(request, payload);
            } catch (error) {
                root.completeFailure(
                    request,
                    "invalid-response",
                    i18n("Invalid collector response: %1", error.message));
            }
        };
        request.open("GET", root.endpoint("/api/v3/dashboard"));
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
