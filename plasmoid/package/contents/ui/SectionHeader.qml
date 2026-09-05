pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

PlasmaComponents3.ToolButton {
    id: root

    required property string title
    required property string sectionIcon
    required property bool expanded
    required property int itemCount
    required property int issueCount
    signal toggledByUser

    Layout.fillWidth: true
    implicitHeight: Math.max(
        Kirigami.Units.iconSizes.medium,
        contentItem.implicitHeight + Kirigami.Units.smallSpacing * 2)
    display: QQC2.AbstractButton.TextOnly
    activeFocusOnTab: true
    Accessible.name: root.title
    Accessible.description: root.expanded
        ? i18np("Expanded, %1 item", "Expanded, %1 items", root.itemCount)
        : i18np("Collapsed, %1 item", "Collapsed, %1 items", root.itemCount)
    Accessible.checkable: true
    Accessible.checked: root.expanded
    onClicked: root.toggledByUser()
    Keys.onRightPressed: {
        if (!root.expanded) {
            root.toggledByUser();
        }
    }
    Keys.onLeftPressed: {
        if (root.expanded) {
            root.toggledByUser();
        }
    }

    contentItem: RowLayout {
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Icon {
            source: root.sectionIcon
            implicitWidth: Kirigami.Units.iconSizes.smallMedium
            implicitHeight: implicitWidth
            Accessible.ignored: true
        }

        PlasmaComponents3.Label {
            Layout.fillWidth: true
            text: root.title
            font.bold: true
            elide: Text.ElideRight
            Accessible.ignored: true
        }

        PlasmaComponents3.Label {
            visible: root.issueCount > 0
            text: i18np("%1 issue", "%1 issues", root.issueCount)
            color: Kirigami.Theme.negativeTextColor
            font: Kirigami.Theme.smallFont
            Accessible.ignored: true
        }

        PlasmaComponents3.Label {
            visible: root.issueCount === 0
            text: root.itemCount
            opacity: 0.7
            font: Kirigami.Theme.smallFont
            Accessible.ignored: true
        }

        Kirigami.Icon {
            source: root.expanded ? "go-down" : "go-next"
            implicitWidth: Kirigami.Units.iconSizes.small
            implicitHeight: implicitWidth
            Accessible.ignored: true
        }
    }
}
