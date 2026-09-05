pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

ColumnLayout {
    id: root

    required property var jellyfin
    required property bool expanded
    required property bool issuesOnly
    signal expansionRequested(bool value)

    readonly property int issueCount: root.jellyfin.status !== "healthy"
        || !!root.jellyfin.error ? 1 : 0
    readonly property int itemCount: 1 + root.jellyfin.active_sessions.length

    Layout.fillWidth: true
    spacing: 0

    SectionHeader {
        title: i18n("Jellyfin")
        sectionIcon: "jellyfin"
        expanded: root.expanded
        itemCount: root.itemCount
        issueCount: root.issueCount
        onToggledByUser: root.expansionRequested(!root.expanded)
    }

    ResourceRow {
        Layout.leftMargin: Kirigami.Units.largeSpacing
        Layout.rightMargin: Kirigami.Units.smallSpacing
        visible: root.expanded && (!root.issuesOnly || root.issueCount > 0)
        name: root.jellyfin.server_name || i18n("Jellyfin server")
        status: root.jellyfin.status
        detail: root.jellyfin.version
            ? i18n("Version %1", root.jellyfin.version)
            : ""
        actionUrl: root.jellyfin.dashboard_url || ""
        actionLabel: i18n("Open Jellyfin")
    }

    ProviderError {
        Layout.leftMargin: Kirigami.Units.largeSpacing
        Layout.rightMargin: Kirigami.Units.smallSpacing
        visible: root.expanded && root.jellyfin.error
        providerName: i18n("Jellyfin")
        errorMessage: root.jellyfin.error || ""
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.gridUnit * 2
        Layout.rightMargin: Kirigami.Units.smallSpacing
        visible: root.expanded
            && !root.issuesOnly
            && root.jellyfin.active_sessions.length === 0
            && !root.jellyfin.error
        text: i18n("Nothing is playing")
        opacity: 0.75
        font: Kirigami.Theme.smallFont
    }

    Repeater {
        model: root.expanded && !root.issuesOnly
            ? root.jellyfin.active_sessions
            : []

        delegate: Item {
            id: sessionRow

            required property var modelData
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.gridUnit * 2
            Layout.rightMargin: Kirigami.Units.smallSpacing
            implicitHeight: Math.max(
                Kirigami.Units.iconSizes.medium,
                sessionLayout.implicitHeight + Kirigami.Units.smallSpacing * 2)
            activeFocusOnTab: true
            Accessible.role: Accessible.ListItem
            Accessible.name: modelData.item_name
            Accessible.description: i18n("%1 using %2 on %3",
                modelData.user_name,
                modelData.client,
                modelData.device_name)
            Keys.onUpPressed: sessionRow.moveFocus(false)
            Keys.onDownPressed: sessionRow.moveFocus(true)

            function moveFocus(forward) {
                const item = sessionRow.nextItemInFocusChain(forward);
                if (item) {
                    item.forceActiveFocus();
                }
            }

            Rectangle {
                anchors.fill: parent
                color: sessionRow.activeFocus
                    ? Kirigami.Theme.alternateBackgroundColor
                    : "transparent"
                border.width: sessionRow.activeFocus ? 1 : 0
                border.color: Kirigami.Theme.highlightColor
                radius: Kirigami.Units.cornerRadius
            }

            ColumnLayout {
                id: sessionLayout
                anchors.fill: parent
                anchors.leftMargin: Kirigami.Units.smallSpacing
                anchors.rightMargin: Kirigami.Units.smallSpacing
                spacing: 0

                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: sessionRow.modelData.item_name
                    elide: Text.ElideRight
                    Accessible.ignored: true
                }

                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: i18n("%1 · %2 on %3",
                        sessionRow.modelData.user_name,
                        sessionRow.modelData.client,
                        sessionRow.modelData.device_name)
                    opacity: 0.75
                    font: Kirigami.Theme.smallFont
                    elide: Text.ElideRight
                    Accessible.ignored: true
                }
            }
        }
    }
}
