"""What the POS WAI app needs that a browser does not.

The web page keeps its session in an httponly cookie. The app cannot: its pages
are files inside the app, so every call to the shop's server is cross-origin,
and iOS refuses a cross-site cookie outright. The app therefore holds its own
session token and sends it in a header on each request.

That swap is safe here, and in one way safer. A header is never attached
automatically by the browser, so a page on some other site cannot make an
authenticated request on the signed-in person's behalf — the cross-site request
forgery that the cookie path has to guard against with an origin check. What it
gives up is httponly: script running inside the app can read the token. The app
ships its own files and loads no third-party script, so there is no page there
to inject into.
"""

from urllib.parse import urlencode

# Capacitor serves the app's own files from these origins: https on Android
# (androidScheme "https"), the capacitor scheme on iOS. Nothing else is an app.
APP_ORIGINS = ("https://localhost", "capacitor://localhost", "ionic://localhost")

# The link that brings a finished sign-in back into the app. Registered by the
# app on both platforms; nothing else on the phone answers it.
APP_LINK_SCHEME = "poswai"

STAFF_HEADER = "x-poswai-session"
OWNER_HEADER = "x-poswai-owner"
APP_HEADER = "x-poswai-app"

# Headers the app sends that a cross-origin request must be allowed to carry.
ALLOWED_HEADERS = ("content-type", "accept", STAFF_HEADER, OWNER_HEADER, APP_HEADER,
                   "x-member-token")


def is_app(request) -> bool:
    """Whether this request came from the app rather than from a web page.

    The app says so, and says so from an origin only the app has. Either alone
    would be a claim a web page could make too.
    """
    return bool(request.headers.get(APP_HEADER)) or request.headers.get("origin", "") in APP_ORIGINS


def staff_token(request) -> str:
    """The staff session token, from the app's header or the page's cookie."""
    return request.headers.get(STAFF_HEADER, "") or request.cookies.get("poswai_session", "")


def owner_token(request, cookie_name: str) -> str:
    """The owner account token, from the app's header or the page's cookie."""
    return request.headers.get(OWNER_HEADER, "") or request.cookies.get(cookie_name, "")


def app_link(path: str, **params) -> str:
    """A link into the app, with the empty values dropped so the app sees only
    what actually happened."""
    kept = {name: value for name, value in params.items() if value not in ("", None)}
    query = ("?" + urlencode(kept)) if kept else ""
    return f"{APP_LINK_SCHEME}://{path}{query}"
