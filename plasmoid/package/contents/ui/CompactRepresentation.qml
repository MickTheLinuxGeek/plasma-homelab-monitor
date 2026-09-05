pragma ComponentBehavior: Bound

import QtQuick
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.plasmoid

Item {
    id: root

    required property PlasmoidItem plasmoidItem
    required property string status
    required property string activity
    required property string accessibleStatus

    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: i18n("Home-lab Monitor")
    Accessible.description: root.accessibleStatus
    Keys.onSpacePressed: root.plasmoidItem.expanded = !root.plasmoidItem.expanded
    Keys.onReturnPressed: root.plasmoidItem.expanded = !root.plasmoidItem.expanded
    Keys.onEnterPressed: root.plasmoidItem.expanded = !root.plasmoidItem.expanded

    Rectangle {
        anchors.fill: parent
        color: "transparent"
        border.width: root.activeFocus ? Math.max(2, Kirigami.Units.smallSpacing / 2) : 0
        border.color: Kirigami.Theme.highlightColor
        radius: Kirigami.Units.cornerRadius
    }

    MouseArea {
        anchors.fill: parent
        onClicked: {
            root.forceActiveFocus();
            root.plasmoidItem.expanded = !root.plasmoidItem.expanded;
        }
    }

    Kirigami.Icon {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.smallSpacing
        source: "server-database"
        opacity: root.activity === "idle" ? 1 : 0.65
        Accessible.ignored: true
    }

    StatusIndicator {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: Kirigami.Units.smallSpacing / 2
        status: root.status
        showLabel: false
    }

    PlasmaComponents3.BusyIndicator {
        anchors.left: parent.left
        anchors.top: parent.top
        visible: root.activity !== "idle"
        running: visible
        implicitWidth: Kirigami.Units.iconSizes.small
        implicitHeight: implicitWidth
        Accessible.ignored: true
    }
}
