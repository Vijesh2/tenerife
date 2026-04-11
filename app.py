from fasthtml.common import *

from ui import APP_STYLES, app_shell


APP_TITLE = "Tenerife Cycling Routes"

hdrs = (
    Meta(name="viewport", content="width=device-width, initial-scale=1"),
    Link(
        rel="stylesheet",
        href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
        integrity="sha256-p4NxAoJBhIINfQen/ZXLGgkJkAHptjMAqAvZVXyHYk=",
        crossorigin="",
    ),
    Link(rel="stylesheet", href="/static/app.css"),
    Style(APP_STYLES),
)

ftrs = (
    Script(
        src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=",
        crossorigin="",
    ),
    Script(src="/static/app.js", defer=True),
)

app, rt = fast_app(
    title=APP_TITLE,
    hdrs=hdrs,
    ftrs=ftrs,
    pico=False,
    secret_key="gpxconverter-v01-dev",
)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/data", StaticFiles(directory="data"), name="data")


@rt("/")
def get():
    return Title(APP_TITLE), app_shell()


if __name__ == "__main__":
    serve()
