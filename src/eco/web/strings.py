"""Every English text of the web GUI. The page gets STRINGS as JSON in
`<script id="strings" type="application/json">`, and the server's own refusals use them too."""

STRINGS = {
    "title": "eco",
    "local_only": "Everything is processed on this computer.",
    "error_token": "Missing or invalid token",
    "error_host": "This address is not allowed. Open eco at the address that eco web printed.",
    "error_origin": "Requests from other websites are not allowed.",
    # The jobs API answers every error as {"error": <one of these>}.
    "error_unsupported": "Unsupported file type: {name}",
    "error_too_large": "File too large (limit {mb} MB)",
    "error_not_form": "Send the files as multipart/form-data",
    "error_unreadable": "The upload could not be read",
    "error_no_files": "No files were uploaded",
    "error_options_json": "The options are not valid JSON",
    "error_options_object": "The options must be a JSON object",
    "error_options_long": "The options are too long",
    "error_option_unknown": "Unknown option: {name}",
    "error_option_value": "Invalid value for {name}",
    "error_font_size": "font_size must be a whole number from {low} to {high}",
    "error_job": "No such job",
    "error_file": "No such file in this job",
    "error_output": "No such output file",
    "error_finished": "This job has already finished",
    "error_server": "Something went wrong on the server",
}
