import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.InlineMessage {
    id: root

    required property string providerName
    required property string errorMessage

    Layout.fillWidth: true
    visible: root.errorMessage.length > 0
    type: Kirigami.MessageType.Error
    text: i18n("%1: %2", root.providerName, root.errorMessage)
    Accessible.name: i18n("%1 provider error", root.providerName)
    Accessible.description: root.errorMessage
}
