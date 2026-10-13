from job_finder import style


def test_score_colors_by_band():
    good, ok, maybe = style.score_colors(9), style.score_colors(7), style.score_colors(5)
    assert len({good, ok, maybe}) == 3  # three different colors
    assert style.score_colors(8) == good  # 8–10 green
    assert style.score_colors(6) == maybe  # 5–6 amber
