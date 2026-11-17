"""Every English text of the web GUI. The page gets STRINGS as JSON in
`<script id="strings" type="application/json">`, and the server's own refusals use them too."""

STRINGS = {
    "title": "eco",
    "local_only": "Everything is processed on this computer.",
    "error_token": "Missing or invalid token",
    "error_host": "This address is not allowed. Open eco at the address that eco web printed.",
    "error_origin": "Requests from other websites are not allowed.",
}
