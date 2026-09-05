pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

Item {
    id: root

    required property var series
    readonly property int maximumPoints: 24
    readonly property var boundedPoints: root.series.points.slice(-root.maximumPoints)
    readonly property var latestPoint: root.boundedPoints.length > 0
        ? root.boundedPoints[root.boundedPoints.length - 1]
        : null

    Layout.fillWidth: true
    implicitHeight: Math.max(
        Kirigami.Units.gridUnit * 2,
        trendLayout.implicitHeight + Kirigami.Units.smallSpacing * 2)
    activeFocusOnTab: true
    Accessible.role: Accessible.ListItem
    Accessible.name: root.series.label
    Accessible.description: root.latestPoint
        ? i18n("Latest value %1, status %2, from %3 bounded points.",
            root.valueText(root.latestPoint.value),
            latestStatus.statusText,
            root.boundedPoints.length)
        : i18n("No trend observations")
    Keys.onUpPressed: root.moveFocus(false)
    Keys.onDownPressed: root.moveFocus(true)
    onSeriesChanged: sparkline.requestPaint()

    function moveFocus(forward) {
        const item = root.nextItemInFocusChain(forward);
        if (item) {
            item.forceActiveFocus();
        }
    }

    function valueText(value) {
        if (value === null) {
            return i18n("unknown");
        }
        return root.series.unit
            ? i18n("%1 %2", value, root.series.unit)
            : String(value);
    }

    Rectangle {
        anchors.fill: parent
        color: root.activeFocus ? Kirigami.Theme.alternateBackgroundColor : "transparent"
        border.width: root.activeFocus ? 1 : 0
        border.color: Kirigami.Theme.highlightColor
        radius: Kirigami.Units.cornerRadius
    }

    RowLayout {
        id: trendLayout

        anchors.fill: parent
        anchors.leftMargin: Kirigami.Units.smallSpacing
        anchors.rightMargin: Kirigami.Units.smallSpacing
        spacing: Kirigami.Units.smallSpacing

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                text: root.series.label
                elide: Text.ElideRight
                Accessible.ignored: true
            }

            RowLayout {
                spacing: Kirigami.Units.smallSpacing

                StatusIndicator {
                    id: latestStatus
                    status: root.latestPoint ? root.latestPoint.status : "unknown"
                    showLabel: true
                }

                PlasmaComponents3.Label {
                    text: root.latestPoint
                        ? root.valueText(root.latestPoint.value)
                        : i18n("No data")
                    font: Kirigami.Theme.smallFont
                    opacity: 0.8
                    Accessible.ignored: true
                }
            }
        }

        Canvas {
            id: sparkline

            Layout.preferredWidth: Kirigami.Units.gridUnit * 7
            Layout.preferredHeight: Kirigami.Units.gridUnit * 2
            Accessible.ignored: true

            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            onPaint: {
                const context = getContext("2d");
                context.reset();
                const numericPoints = root.boundedPoints.filter(
                    point => point.value !== null);
                if (numericPoints.length === 0) {
                    return;
                }
                const values = numericPoints.map(point => point.value);
                const minimum = Math.min(...values);
                const maximum = Math.max(...values);
                const range = Math.max(1, maximum - minimum);
                const padding = Math.max(2, Kirigami.Units.smallSpacing / 2);
                const drawWidth = Math.max(1, width - padding * 2);
                const drawHeight = Math.max(1, height - padding * 2);

                context.strokeStyle = Kirigami.Theme.highlightColor;
                context.lineWidth = 2;
                context.beginPath();
                for (let index = 0; index < numericPoints.length; index++) {
                    const x = padding + (numericPoints.length === 1
                        ? drawWidth / 2
                        : index * drawWidth / (numericPoints.length - 1));
                    const y = padding
                        + (maximum - numericPoints[index].value) * drawHeight / range;
                    if (index === 0) {
                        context.moveTo(x, y);
                    } else {
                        context.lineTo(x, y);
                    }
                }
                context.stroke();
            }
        }
    }
}
