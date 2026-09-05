pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

ColumnLayout {
    id: root

    required property var events
    required property var formatAge
    required property bool issuesOnly
    property bool expanded: true
    readonly property int maximumEvents: 6
    readonly property int issueCount: root.activeEventCount()
    readonly property var visibleEvents: root.boundedEvents()

    Layout.fillWidth: true
    spacing: 0
    Accessible.role: Accessible.Grouping
    Accessible.name: i18n("Recent incidents")

    function isActive(event) {
        return event.recovered_at === null
            && event.current_status !== null
            && event.current_status !== "healthy";
    }

    function activeEventCount() {
        let count = 0;
        for (const event of root.events) {
            if (root.isActive(event)) {
                count++;
            }
        }
        return count;
    }

    function boundedEvents() {
        const result = root.events.filter(function(event) {
            return !root.issuesOnly || root.isActive(event);
        });
        result.sort(function(left, right) {
            const activeDifference = Number(root.isActive(right))
                - Number(root.isActive(left));
            if (activeDifference !== 0) {
                return activeDifference;
            }
            return Date.parse(right.occurred_at) - Date.parse(left.occurred_at);
        });
        return result.slice(0, root.maximumEvents);
    }

    function severityText(severity) {
        switch (severity) {
        case "critical":
            return i18n("Critical");
        case "warning":
            return i18n("Warning");
        default:
            return i18n("Information");
        }
    }

    function severityIcon(severity) {
        switch (severity) {
        case "critical":
            return "dialog-error";
        case "warning":
            return "data-warning";
        default:
            return "dialog-information";
        }
    }

    SectionHeader {
        title: i18n("Recent incidents")
        sectionIcon: "view-history"
        expanded: root.expanded
        itemCount: root.events.length
        issueCount: root.issueCount
        onToggledByUser: root.expanded = !root.expanded
    }

    Repeater {
        model: root.expanded ? root.visibleEvents : []

        delegate: Item {
            id: eventRow

            required property var modelData
            Layout.fillWidth: true
            Layout.leftMargin: modelData.parent_event_id === null
                ? Kirigami.Units.largeSpacing
                : Kirigami.Units.gridUnit * 2
            Layout.rightMargin: Kirigami.Units.smallSpacing
            implicitHeight: eventLayout.implicitHeight + Kirigami.Units.smallSpacing * 2
            activeFocusOnTab: true
            Accessible.role: Accessible.ListItem
            Accessible.name: i18n("%1 incident for %2",
                root.severityText(modelData.severity),
                modelData.resource_name)
            Accessible.description: modelData.message
                + i18n(". Occurred %1.", root.formatAge(modelData.occurred_at))
                + (modelData.parent_event_id === null
                    ? ""
                    : i18n(" Related to a parent incident."))
            Keys.onUpPressed: eventRow.moveFocus(false)
            Keys.onDownPressed: eventRow.moveFocus(true)

            function moveFocus(forward) {
                const item = eventRow.nextItemInFocusChain(forward);
                if (item) {
                    item.forceActiveFocus();
                }
            }

            Rectangle {
                anchors.fill: parent
                color: eventRow.activeFocus
                    ? Kirigami.Theme.alternateBackgroundColor
                    : "transparent"
                border.width: eventRow.activeFocus ? 1 : 0
                border.color: Kirigami.Theme.highlightColor
                radius: Kirigami.Units.cornerRadius
            }

            RowLayout {
                id: eventLayout

                anchors.fill: parent
                anchors.leftMargin: Kirigami.Units.smallSpacing
                anchors.rightMargin: Kirigami.Units.smallSpacing
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Icon {
                    source: root.severityIcon(eventRow.modelData.severity)
                    implicitWidth: Kirigami.Units.iconSizes.small
                    implicitHeight: implicitWidth
                    Accessible.ignored: true
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0

                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        text: i18n("%1 · %2",
                            root.severityText(eventRow.modelData.severity),
                            eventRow.modelData.resource_name)
                        font.bold: root.isActive(eventRow.modelData)
                        elide: Text.ElideRight
                        Accessible.ignored: true
                    }

                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        text: eventRow.modelData.message
                        opacity: 0.8
                        font: Kirigami.Theme.smallFont
                        elide: Text.ElideRight
                        Accessible.ignored: true
                    }

                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        text: (root.isActive(eventRow.modelData)
                                ? i18n("Active")
                                : i18n("Recovered"))
                            + i18n(" · %1", root.formatAge(eventRow.modelData.occurred_at))
                            + (eventRow.modelData.parent_event_id === null
                                ? ""
                                : i18n(" · related incident"))
                        opacity: 0.7
                        font: Kirigami.Theme.smallFont
                        elide: Text.ElideRight
                        Accessible.ignored: true
                    }
                }
            }
        }
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.largeSpacing
        Layout.rightMargin: Kirigami.Units.smallSpacing
        visible: root.expanded
            && root.events.filter(function(event) {
                return !root.issuesOnly || root.isActive(event);
            }).length > root.maximumEvents
        text: i18n("Showing the %1 most actionable events.", root.maximumEvents)
        opacity: 0.7
        font: Kirigami.Theme.smallFont
        wrapMode: Text.Wrap
    }
}
