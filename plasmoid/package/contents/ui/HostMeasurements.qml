pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

ColumnLayout {
    id: root

    required property var metrics
    required property bool issuesOnly
    required property var formatAge
    readonly property int maximumMeasurements: 6
    readonly property var matchingMeasurements: root.filteredMeasurements()
    readonly property var visibleMeasurements: root.matchingMeasurements.slice(
        0,
        root.maximumMeasurements)

    Layout.fillWidth: true
    spacing: 0
    Accessible.role: Accessible.Grouping
    Accessible.name: i18n("Host measurements")

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

    function filteredMeasurements() {
        if (!root.metrics) {
            return [];
        }
        const result = root.metrics.measurements.filter(function(measurement) {
            return !root.issuesOnly || measurement.status !== "healthy";
        });
        result.sort(function(left, right) {
            const difference = root.statusRank(left.status) - root.statusRank(right.status);
            return difference || left.label.localeCompare(right.label);
        });
        return result;
    }

    function valueText(measurement) {
        if (measurement.value === null) {
            return i18n("Unknown value");
        }
        const value = typeof measurement.value === "boolean"
            ? (measurement.value ? i18n("Yes") : i18n("No"))
            : String(measurement.value);
        return measurement.unit
            ? i18n("%1 %2", value, measurement.unit)
            : value;
    }

    function thresholdText(measurement) {
        const threshold = measurement.thresholds;
        if (!threshold) {
            return i18n("No numeric threshold");
        }
        if (threshold.direction === "categorical") {
            return i18n("Categorical health threshold");
        }
        const unit = measurement.unit ? " " + measurement.unit : "";
        let text = "";
        if (threshold.warning !== null) {
            text = threshold.direction === "above"
                ? i18n("Warn above %1%2", threshold.warning, unit)
                : i18n("Warn below %1%2", threshold.warning, unit);
        }
        if (threshold.critical !== null) {
            const criticalText = threshold.direction === "above"
                ? i18n(" · critical above %1%2", threshold.critical, unit)
                : i18n(" · critical below %1%2", threshold.critical, unit);
            text += text ? criticalText : criticalText.replace(/^ · /, "");
        }
        text = text || i18n("Configured threshold");
        if (threshold.sustained_samples > 1) {
            text += i18np(
                " · after %1 sample",
                " · after %1 samples",
                threshold.sustained_samples);
        }
        return text;
    }

    function freshnessText(measurement) {
        let freshness;
        switch (measurement.freshness) {
        case "fresh":
            freshness = i18n("Fresh");
            break;
        case "stale":
            freshness = i18n("Stale");
            break;
        default:
            freshness = i18n("Freshness unknown");
        }
        return measurement.observed_at
            ? i18n("%1 · observed %2", freshness, root.formatAge(measurement.observed_at))
            : i18n("%1 · observation age unknown", freshness);
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        text: i18n("Measurements")
        font.bold: true
        opacity: 0.8
        Accessible.ignored: true
    }

    ProviderError {
        visible: !!root.metrics && !!root.metrics.error
        providerName: i18n("Host metrics")
        providerError: root.metrics ? root.metrics.error : null
        lastSuccessAge: root.metrics && root.metrics.last_success_at
            ? root.formatAge(root.metrics.last_success_at)
            : ""
    }

    Repeater {
        model: root.visibleMeasurements

        delegate: ResourceRow {
            id: measurementRow

            required property var modelData
            name: i18n("%1: %2",
                modelData.label,
                root.valueText(modelData))
            status: modelData.status
            detail: root.thresholdText(modelData)
                + i18n(" · %1", root.freshnessText(modelData))
                + (modelData.detail ? i18n(" · %1", modelData.detail) : "")
        }
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        visible: root.matchingMeasurements.length > root.maximumMeasurements
        text: i18np(
            "%1 additional measurement hidden",
            "%1 additional measurements hidden",
            root.matchingMeasurements.length - root.maximumMeasurements)
        opacity: 0.7
        font: Kirigami.Theme.smallFont
        wrapMode: Text.Wrap
    }
}
