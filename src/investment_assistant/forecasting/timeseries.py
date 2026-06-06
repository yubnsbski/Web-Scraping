"""Time-series container and CSV loading for forecasting."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TimeSeries:
    """An ordered numeric series with aligned date labels."""

    dates: tuple[str, ...]
    values: tuple[float, ...]
    name: str = "series"

    def __post_init__(self) -> None:
        if len(self.dates) != len(self.values):
            msg = "dates and values must have equal length"
            raise ValueError(msg)

    def __len__(self) -> int:
        return len(self.values)

    def split(self, train_size: int) -> tuple[TimeSeries, TimeSeries]:
        """Split chronologically into (train, test) at ``train_size`` points."""

        if not 0 < train_size < len(self.values):
            msg = f"train_size must be between 1 and {len(self.values) - 1}"
            raise ValueError(msg)
        return (
            TimeSeries(self.dates[:train_size], self.values[:train_size], self.name),
            TimeSeries(self.dates[train_size:], self.values[train_size:], self.name),
        )

    def tail(self, count: int) -> TimeSeries:
        """Return the last ``count`` observations."""

        if count <= 0:
            msg = "count must be positive"
            raise ValueError(msg)
        return TimeSeries(self.dates[-count:], self.values[-count:], self.name)


def load_timeseries_csv(
    path: str | Path,
    *,
    date_column: str = "Date",
    value_column: str = "SP500",
    drop_nonpositive: bool = True,
) -> TimeSeries:
    """Load a numeric time series from a CSV file.

    Rows whose value is missing, non-numeric, or (by default) non-positive are
    dropped. Public financial CSVs often carry a trailing incomplete period with
    zero/blank values, which would otherwise corrupt returns and metrics.
    """

    csv_path = Path(path)
    dates: list[str] = []
    values: list[float] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        for required in (date_column, value_column):
            if required not in fieldnames:
                msg = f"CSV is missing required column: {required}"
                raise ValueError(msg)
        for row in reader:
            raw_value = (row.get(value_column) or "").strip()
            if not raw_value:
                continue
            try:
                value = float(raw_value)
            except ValueError:
                continue
            if drop_nonpositive and value <= 0:
                continue
            dates.append((row.get(date_column) or "").strip())
            values.append(value)

    if not values:
        msg = f"No usable numeric rows found in {csv_path}"
        raise ValueError(msg)
    return TimeSeries(tuple(dates), tuple(values), name=value_column)
