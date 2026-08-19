import QtQuick
import org.kde.kirigami as Kirigami

Rectangle {
    id: root

    required property string status

    implicitWidth: Kirigami.Units.smallSpacing * 2
    implicitHeight: implicitWidth
    radius: width / 2
    border.width: 1
    border.color: Kirigami.Theme.backgroundColor
    color: {
        switch (status) {
        case "healthy":
            return Kirigami.Theme.positiveTextColor;
        case "degraded":
            return Kirigami.Theme.neutralTextColor;
        case "unavailable":
            return Kirigami.Theme.negativeTextColor;
        default:
            return Kirigami.Theme.disabledTextColor;
        }
    }
}
