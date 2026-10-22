"""Errors of the data sources (spec §12: a failing source stops the calculation)."""


class SourceUnavailable(Exception):
    """A source could not answer. The API answers 503 naming it; nothing is inferred."""

    def __init__(self, source: str, detail: str):
        super().__init__(f"{source}: {detail}")
        self.source = source
        self.detail = detail
