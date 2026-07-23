from research import hourly_orderbook_transfer as transfer

_original_choose_col = transfer.choose_col

def _choose_col_with_ts_ms(names, *candidates):
    if candidates == ('timestamp_ms', 'timestamp'):
        candidates = candidates + ('ts_ms',)
    return _original_choose_col(names, *candidates)

transfer.choose_col = _choose_col_with_ts_ms

if __name__ == '__main__':
    transfer.main()
