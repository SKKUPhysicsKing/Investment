from types import SimpleNamespace

import matplotlib

matplotlib.use("Agg")

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from investment.rates_ui import RatePanel


def test_plot_keeps_percent_scale_missing_gaps_and_loaded_snapshot(rate_history):
    figure = Figure(layout="constrained")
    panel = object.__new__(RatePanel)
    panel.figure = figure
    panel.canvas = FigureCanvasAgg(figure)
    panel.ax = figure.subplots()
    panel.app = SimpleNamespace(chart_font="DejaVu Sans")
    panel.history = rate_history
    panel.visible = {"DFF", "DGS10"}
    rate_history.metadata["series"][0]["policy"] = True
    rate_history.data.loc[rate_history.data.series_id == "DGS10", "rate"] = [float("nan"), 3.91]
    original_rows = len(rate_history.data)
    panel.draw()
    assert panel.ax.lines[0].get_ydata().tolist() == [5.33, 5.33]
    assert panel.ax.lines[0].get_drawstyle() == "steps-post"
    assert np.isnan(panel.ax.lines[1].get_ydata()[0])
    assert panel.ax.get_ylabel() == "Interest rate (%)"
    panel.visible = {"DGS10"}
    panel.draw()
    assert len(panel.ax.lines) == 1
    assert len(rate_history.data) == original_rows
