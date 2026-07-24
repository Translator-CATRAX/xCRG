import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from translator_tom import CURIE, Query, TOMBase

from .config import XCRGConfig as Config # TODO
from .debugging import DebugContext, debug_dump_json
from .reporting import Reporter

@dataclass
class RunnerContext:
    """A RunnerContext maintains state for a run through the xCRG module."""
    query_id: str
    original_query: Query
    config: Config
    reporter: Reporter
    debug_ctx: DebugContext | None = None

    @staticmethod
    def new(
        query_id: str,
        query: Query,
        config: Config,
        reporter: Reporter,
    ) -> "RunnerContext":

        debug_dir: Path | None = None
        if isinstance(config.debug_dir, Path):
            debug_dir = config.debug_dir
        elif isinstance(config.debug_dir, str):
            debug_dir = Path(config.debug_dir)

        debug_ctx: DebugContext | None = None
        if debug_dir and debug_dir.exists():
            debug_ctx = DebugContext.new(debug_dir = debug_dir, query = query, query_id = query_id)

        return RunnerContext(
            query_id = query_id,
            original_query = query,
            config = config,
            reporter = reporter,
            debug_ctx = debug_ctx
        )

    def debug_dump_json(self, label: str, payload: object | TOMBase) -> None:
        if self.debug_ctx:
            try:
                debug_dump_json(self.debug_ctx, label, payload)
            except Exception as e:
                self.reporter.warning(str(e))


    def load_tf_list(self) -> list[CURIE]:
        """Load transcription factors from config or bundled package resources."""
        tf_file = path_or_none(self.config.tf_path)

        # Fallback if the configured file is not valid
        if not tf_file or not tf_file.exists():
            tf_file = resources.files("xcrg.resources").joinpath("transcription_factors.json")

        with tf_file.open(encoding = "utf-8") as f:
            tf_data = json.load(f)

        tf_list = tf_data.get("tf") or []
        if not tf_list:
            raise ValueError("No transcription factors were found in transcription_factors.json.")

        return tf_list


def path_or_none(path: str | Path | None) -> Path | None:
    if isinstance(path, Path):
        return path
    elif isinstance(path, str):
        return Path(path)
    else:
        return None
