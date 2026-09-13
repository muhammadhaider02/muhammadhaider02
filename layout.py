"""Shared row geometry for the profile card.

A row renders as '. ' + key + ':' + ' ' + dots + ' ' + value, exactly 60 chars wide. The
stats block splits that span into two columns joined by ' | ', so L + R == ROW_WIDTH and the
'|' lands on column 35 of every stats row.

These numbers live here because they used to exist twice: as literal dot runs written into
generate_svg.py's stat rows, and as magic numbers (49, 23, 14, 7, 10, 15) passed to
today.py's justify_format. Nothing kept the two in step, so any value that changed width
moved the separators out of alignment and only the rendered SVG showed it.
"""

ROW_WIDTH = 55  # key + dots + value; excludes '. ', ':' and the two spaces around the dots
L = 34          # left stats column
R = 21          # right stats column
assert L + R == ROW_WIDTH, 'columns must fill the row or the | separators drift'
# The Lines of Code row is a single full-width field carrying the ++/-- breakdown, so it has
# no separator and is not bound by L/R. Only the two-column rows above it use them.


def field_len(key, width, extra=0):
    """
    The `length` justify_format needs: the combined width of the dots run and the value.

    `extra` is literal text that shares the column after the value -- the Repos column also
    carries ' {Coded: NN}', so its dot count depends on how many digits Coded has. A static
    length cannot express that, which is why the separators drifted before.
    """
    return width - len(key) - 3 - extra


def dots(key, value, width, extra=0):
    """The dots span for a field, including the single space on either side."""
    count = field_len(key, width, extra) - len(str(value))
    assert count >= 1, f'{key}: {value!r} overflows its {width}-char column by {1 - count}'
    return ' ' + '.' * count + ' '
