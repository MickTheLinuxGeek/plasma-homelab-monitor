WIDGET_ID := org.mickgeeklabs.homelabmonitor
PACKAGE_DIR := plasmoid/package

.PHONY: setup config run test lint format check install-widget uninstall-widget preview package install-service

setup:
	uv sync --extra dev

config:
	test -f config.yaml || cp config.example.yaml config.yaml

run:
	uv run homelab-monitor --config config.yaml

test:
	uv run pytest

lint:
	uv run ruff check collector

format:
	uv run ruff format collector

check: lint test
	python3 -m json.tool $(PACKAGE_DIR)/metadata.json >/dev/null
	python3 -m json.tool collector/src/homelab_monitor/schema/dashboard-v2.schema.json >/dev/null
	python3 -c 'from xml.etree import ElementTree; ElementTree.parse("$(PACKAGE_DIR)/contents/config/main.xml")'

install-widget:
	kpackagetool6 --type Plasma/Applet --upgrade $(PACKAGE_DIR) || \
		kpackagetool6 --type Plasma/Applet --install $(PACKAGE_DIR)

uninstall-widget:
	kpackagetool6 --type Plasma/Applet --remove $(WIDGET_ID)

preview: install-widget
	plasmawindowed $(WIDGET_ID)

package:
	mkdir -p dist
	cd $(PACKAGE_DIR) && zip -r ../../../dist/home-lab-monitor.plasmoid .

install-service:
	mkdir -p ~/.config/systemd/user
	cp systemd/homelab-monitor.service ~/.config/systemd/user/
	systemctl --user daemon-reload
	systemctl --user enable --now homelab-monitor.service
