pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

Item {
    id: root

    required property string name
    required property string status
    property string detail: ""
    property string actionUrl: ""
    property string actionLabel: i18n("Open dashboard")

    Layout.fillWidth: true
    implicitHeight: Math.max(
        Kirigami.Units.iconSizes.medium,
        rowLayout.implicitHeight + Kirigami.Units.smallSpacing * 2)
    activeFocusOnTab: true
    Accessible.role: Accessible.ListItem
    Accessible.name: i18n("%1: %2", root.name, statusIndicator.statusText)
    Accessible.description: root.detail
    Keys.onUpPressed: root.moveFocus(false)
    Keys.onDownPressed: root.moveFocus(true)

    function moveFocus(forward) {
        const item = root.nextItemInFocusChain(forward);
        if (item) {
            item.forceActiveFocus();
        }
    }

    Rectangle {
        anchors.fill: parent
        color: root.activeFocus ? Kirigami.Theme.alternateBackgroundColor : "transparent"
        border.width: root.activeFocus ? 1 : 0
        border.color: Kirigami.Theme.highlightColor
        radius: Kirigami.Units.cornerRadius
    }

    RowLayout {
        id: rowLayout
        anchors.fill: parent
        anchors.leftMargin: Kirigami.Units.smallSpacing
        anchors.rightMargin: Kirigami.Units.smallSpacing
        spacing: Kirigami.Units.smallSpacing

        StatusIndicator {
            id: statusIndicator
            status: root.status
            showLabel: false
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                text: root.name
                elide: Text.ElideRight
                Accessible.ignored: true
            }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                visible: root.detail.length > 0
                text: root.detail
                opacity: 0.75
                font: Kirigami.Theme.smallFont
                elide: Text.ElideRight
                Accessible.ignored: true
            }
        }

        PlasmaComponents3.ToolButton {
            visible: root.actionUrl.length > 0
            icon.name: "internet-web-browser"
            text: root.actionLabel
            display: QQC2.AbstractButton.IconOnly
            activeFocusOnTab: true
            Accessible.name: text
            Accessible.description: i18n("Open %1 in the default browser", root.name)
            onClicked: Qt.openUrlExternally(root.actionUrl)
            PlasmaComponents3.ToolTip.text: text
            PlasmaComponents3.ToolTip.visible: hovered
        }
    }
}
