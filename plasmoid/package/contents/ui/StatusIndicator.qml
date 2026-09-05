import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

RowLayout {
    id: root

    required property string status
    property bool showLabel: false
    readonly property string statusText: {
        switch (root.status) {
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
    readonly property string iconName: {
        switch (root.status) {
        case "healthy":
            return "emblem-success";
        case "degraded":
            return "data-warning";
        case "unavailable":
            return "dialog-error";
        default:
            return "question";
        }
    }

    spacing: Kirigami.Units.smallSpacing
    Accessible.role: Accessible.StaticText
    Accessible.name: root.statusText

    Kirigami.Icon {
        source: root.iconName
        implicitWidth: Kirigami.Units.iconSizes.small
        implicitHeight: implicitWidth
        Accessible.ignored: true
    }

    PlasmaComponents3.Label {
        visible: root.showLabel
        text: root.statusText
        Accessible.ignored: true
    }
}
