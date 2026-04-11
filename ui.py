from fasthtml.common import *


APP_STYLES = """
:root {
  color-scheme: light;
  --ink: #18211d;
  --muted: #68736e;
  --panel: #ffffff;
  --line: #dce3df;
  --route: #267c67;
  --route-soft: #d9ebe5;
  --accent: #d4523a;
  --map-bg: #edf1ee;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-height: 100vh;
  color: var(--ink);
  background: var(--map-bg);
  overflow: hidden;
}
"""


def app_shell():
    return Main(
        Header(
            Div(
                H1("Tenerife Cycling Routes"),
                cls="page-heading",
            ),
            Div(
                Span("Selected route", cls="section-label"),
                Div("Select a route", id="route-detail", cls="route-detail compact empty"),
                cls="detail-section top-detail",
            ),
            Div(
                Span(cls="legend-line"),
                Span("Selected route"),
                cls="legend",
            ),
            cls="app-header",
        ),
        Section(
            Div(id="map", aria_label="Cycling route map"),
            Div(
                Strong("Tenerife"),
                Span("Routes load from data/processed/routes.geojson"),
                id="map-status",
                cls="map-status",
            ),
            cls="map-panel",
        ),
        Div(
            Span("Drag to resize route list"),
            id="route-resizer",
            cls="route-resizer",
            role="separator",
            aria_orientation="horizontal",
            tabindex="0",
        ),
        Section(
            Header(
                Div(
                    Div("Routes", cls="section-label"),
                    H2("Route list"),
                    Button("Deselect all", id="toggle-all-routes", cls="toggle-all-routes", type="button"),
                    cls="list-title",
                ),
                Div(
                    Span("", cls="route-head-spacer"),
                    Span("", cls="route-head-spacer"),
                    Span("Route", cls="route-head-route"),
                    Span("Distance", cls="route-head-stat"),
                    Span("Elevation", cls="route-head-stat"),
                    cls="route-column-head",
                ),
                cls="routes-header",
            ),
            Div("Loading routes...", id="route-list", cls="route-list"),
            cls="routes-panel",
        ),
        cls="app-layout",
    )
