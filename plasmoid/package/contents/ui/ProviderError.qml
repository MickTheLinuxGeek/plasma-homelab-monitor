import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.InlineMessage {
    id: root

    required property string providerName
    required property var providerError
    property string lastSuccessAge: ""

    Layout.fillWidth: true
    visible: !!root.providerError
    type: Kirigami.MessageType.Error
    text: root.providerError
        ? (root.lastSuccessAge
            ? i18n("%1: %2 Last successful observation was %3.",
                root.providerName,
                root.providerError.message,
                root.lastSuccessAge)
            : i18n("%1: %2 No successful observation is available.",
                root.providerName,
                root.providerError.message))
        : ""
    Accessible.name: i18n("%1 provider error", root.providerName)
    Accessible.description: root.providerError
        ? i18n("Category: %1. %2",
            root.providerError.category,
            root.providerError.message)
        : ""
}
