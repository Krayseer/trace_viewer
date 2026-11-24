"""Python entry point for workbooks opened in a browser worker."""

import json
from pathlib import Path

from .api import api_response
from .application import TraceApplication
from .data import XlsDataset


class WorkbookApi:
    def __init__(self, directory: str):
        self.dataset = XlsDataset(Path(directory))
        self.app = TraceApplication(self.dataset)

    def request(self, path: str, query_json: str) -> str:
        response = api_response(self.app, self.dataset, path, json.loads(query_json))
        return json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
