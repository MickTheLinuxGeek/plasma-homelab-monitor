import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.FormLayout {
    id: page

    property alias cfg_collectorUrl: collectorUrl.text
    property alias cfg_refreshInterval: refreshInterval.value

    QQC2.TextField {
        id: collectorUrl
        Kirigami.FormData.label: i18n("Collector URL:")
        placeholderText: "http://127.0.0.1:8765"
        inputMethodHints: Qt.ImhUrlCharactersOnly
    }

    QQC2.SpinBox {
        id: refreshInterval
        Kirigami.FormData.label: i18n("Refresh interval:")
        from: 5
        to: 3600
        stepSize: 5
        textFromValue: function(value) {
            return i18np("%1 second", "%1 seconds", value);
        }
        valueFromText: function(text) {
            const parsed = parseInt(text, 10);
            return isNaN(parsed) ? 30 : parsed;
        }
    }

    QQC2.Label {
        Kirigami.FormData.label: i18n("Security:")
        Layout.maximumWidth: Kirigami.Units.gridUnit * 18
        text: i18n("The widget only receives normalized status data. Keep Portainer and Jellyfin tokens in the collector environment.")
        wrapMode: Text.WordWrap
    }
}
