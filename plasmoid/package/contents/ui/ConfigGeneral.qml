pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.FormLayout {
    id: page

    property alias cfg_collectorUrl: collectorUrl.text
    property alias cfg_refreshInterval: refreshInterval.value
    property alias cfg_showHosts: showHosts.checked
    property alias cfg_showDocker: showDocker.checked
    property alias cfg_showJellyfin: showJellyfin.checked
    property alias cfg_hostsExpanded: hostsExpanded.checked
    property alias cfg_dockerExpanded: dockerExpanded.checked
    property alias cfg_jellyfinExpanded: jellyfinExpanded.checked
    property alias cfg_sortMode: sortMode.currentValue
    property alias cfg_issuesOnlyByDefault: issuesOnlyByDefault.checked
    property bool testInFlight: false
    property string testFeedback: ""
    property int testFeedbackType: Kirigami.MessageType.Information
    property var activeTestRequest: null

    function normalizedCollectorUrl() {
        return collectorUrl.text.replace(/\/+$/, "");
    }

    function finishTest(request, message, type) {
        if (page.activeTestRequest !== request) {
            return;
        }
        page.activeTestRequest = null;
        page.testInFlight = false;
        page.testFeedback = message;
        page.testFeedbackType = type;
    }

    function testConnection() {
        if (page.testInFlight || !collectorUrl.acceptableInput) {
            return;
        }
        page.testInFlight = true;
        page.testFeedback = i18n("Testing connection…");
        page.testFeedbackType = Kirigami.MessageType.Information;
        const request = new XMLHttpRequest();
        page.activeTestRequest = request;
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE
                    || page.activeTestRequest !== request) {
                return;
            }
            if (request.status < 200 || request.status >= 300) {
                page.finishTest(
                    request,
                    i18n("Collector returned HTTP %1.", request.status),
                    Kirigami.MessageType.Error);
                return;
            }
            try {
                const payload = JSON.parse(request.responseText);
                if (payload.status !== "ok") {
                    throw new Error(i18n("Unexpected health response"));
                }
                page.finishTest(
                    request,
                    i18n("Connected to collector %1 (API %2).",
                        payload.collector_version || i18n("unknown"),
                        payload.api_version || i18n("unknown")),
                    Kirigami.MessageType.Positive);
            } catch (error) {
                page.finishTest(
                    request,
                    i18n("Collector returned an invalid health response."),
                    Kirigami.MessageType.Error);
            }
        };
        request.open("GET", page.normalizedCollectorUrl() + "/healthz");
        request.timeout = 5000;
        request.ontimeout = function() {
            page.finishTest(
                request,
                i18n("Connection timed out."),
                Kirigami.MessageType.Error);
        };
        request.onerror = function() {
            page.finishTest(
                request,
                i18n("Collector could not be reached."),
                Kirigami.MessageType.Error);
        };
        request.send();
    }

    QQC2.TextField {
        id: collectorUrl
        Kirigami.FormData.label: i18n("Collector URL:")
        placeholderText: "http://127.0.0.1:8765"
        inputMethodHints: Qt.ImhUrlCharactersOnly
        activeFocusOnTab: true
        Accessible.name: i18n("Collector URL")
        Accessible.description: i18n("HTTP or HTTPS base URL for the local collector")
        validator: RegularExpressionValidator {
            regularExpression: /^https?:\/\/[^\s/]+(?::\d+)?(?:\/[^\s]*)?$/
        }
        onTextChanged: page.testFeedback = ""
    }

    QQC2.Label {
        visible: collectorUrl.text.length > 0 && !collectorUrl.acceptableInput
        text: i18n("Enter a complete HTTP or HTTPS URL, for example http://127.0.0.1:8765.")
        color: Kirigami.Theme.negativeTextColor
        wrapMode: Text.WordWrap
    }

    QQC2.Button {
        text: page.testInFlight ? i18n("Testing…") : i18n("Test Connection")
        icon.name: page.testInFlight ? "view-refresh" : "network-connect"
        enabled: collectorUrl.acceptableInput && !page.testInFlight
        activeFocusOnTab: true
        Accessible.name: text
        Accessible.description: i18n("Check the collector health endpoint")
        onClicked: page.testConnection()
    }

    Kirigami.InlineMessage {
        visible: page.testFeedback.length > 0
        text: page.testFeedback
        type: page.testFeedbackType
    }

    QQC2.SpinBox {
        id: refreshInterval
        Kirigami.FormData.label: i18n("Refresh interval:")
        from: 5
        to: 3600
        stepSize: 5
        editable: true
        activeFocusOnTab: true
        Accessible.name: i18n("Refresh interval in seconds")
        Accessible.description: i18n("Allowed range: 5 to 3600 seconds")
        textFromValue: function(value) {
            return i18np("%1 second", "%1 seconds", value);
        }
        valueFromText: function(text) {
            const parsed = parseInt(text, 10);
            return isNaN(parsed) ? 30 : parsed;
        }
    }

    QQC2.Label {
        Kirigami.FormData.isSection: true
        text: i18n("Dashboard sections")
        font.bold: true
    }

    QQC2.CheckBox {
        id: showHosts
        Kirigami.FormData.label: i18n("Visible sections:")
        text: i18n("Hosts")
        activeFocusOnTab: true
        Accessible.name: i18n("Show Hosts section")
    }

    QQC2.CheckBox {
        id: showDocker
        text: i18n("Docker")
        activeFocusOnTab: true
        Accessible.name: i18n("Show Docker section")
    }

    QQC2.CheckBox {
        id: showJellyfin
        text: i18n("Jellyfin")
        activeFocusOnTab: true
        Accessible.name: i18n("Show Jellyfin section")
    }

    QQC2.CheckBox {
        id: hostsExpanded
        Kirigami.FormData.label: i18n("Expanded sections:")
        text: i18n("Hosts")
        activeFocusOnTab: true
        Accessible.name: i18n("Keep Hosts section expanded")
    }

    QQC2.CheckBox {
        id: dockerExpanded
        text: i18n("Docker")
        activeFocusOnTab: true
        Accessible.name: i18n("Keep Docker section expanded")
    }

    QQC2.CheckBox {
        id: jellyfinExpanded
        text: i18n("Jellyfin")
        activeFocusOnTab: true
        Accessible.name: i18n("Keep Jellyfin section expanded")
    }

    QQC2.Label {
        Kirigami.FormData.isSection: true
        text: i18n("Resource display")
        font.bold: true
    }

    QQC2.ComboBox {
        id: sortMode
        Kirigami.FormData.label: i18n("Default sorting:")
        textRole: "text"
        valueRole: "value"
        model: [
            {"text": i18n("Unhealthy resources first"), "value": "status"},
            {"text": i18n("Name"), "value": "name"}
        ]
        activeFocusOnTab: true
        Accessible.name: i18n("Default resource sorting")
    }

    QQC2.CheckBox {
        id: issuesOnlyByDefault
        Kirigami.FormData.label: i18n("Filtering:")
        text: i18n("Show issues only when the widget opens")
        activeFocusOnTab: true
        Accessible.name: text
    }

    QQC2.Label {
        Kirigami.FormData.label: i18n("Security:")
        Layout.maximumWidth: Kirigami.Units.gridUnit * 20
        text: i18n("The widget only receives normalized status data. Keep Portainer and Jellyfin tokens in the collector environment.")
        wrapMode: Text.WordWrap
    }
}
