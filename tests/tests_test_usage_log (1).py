from core import usage_log


class _Table:
    def __init__(self, fail=False, no_returning=False):
        self.rows, self.fail, self.no_returning, self.kwargs = [], fail, no_returning, None

    def insert(self, row, **kwargs):
        if self.no_returning and kwargs:
            raise TypeError("unexpected keyword")
        self.kwargs = kwargs
        self.rows.append(row)
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("new row violates row-level security policy")
        return self


class _Client:
    def __init__(self, table):
        self._table = table

    def table(self, name):
        assert name == "api_usage_log"
        return self._table


def _use(monkeypatch, table):
    import core.supabase_client as sc
    monkeypatch.setattr(usage_log, "ACTIVE_DB_BACKEND", "supabase")
    monkeypatch.setattr(sc, "get_supabase_client", lambda: _Client(table), raising=False)


def test_record_is_written_without_asking_for_the_row_back(monkeypatch):
    table = _Table()
    _use(monkeypatch, table)
    usage_log.log_api_request(3, "gemini_invoice_scan", "success", model="m", duration_seconds=1.5)
    assert table.rows[0]["store_id"] == 3 and table.rows[0]["status"] == "success"
    assert "returning" in table.kwargs and "minimal" in str(table.kwargs["returning"]).lower()
    assert usage_log.last_error is None


def test_old_library_without_returning_still_records(monkeypatch):
    table = _Table(no_returning=True)
    _use(monkeypatch, table)
    usage_log.log_api_request(3, "gemini_invoice_scan", "error", error_message="x" * 500)
    assert len(table.rows) == 1 and len(table.rows[0]["error_message"]) == 300


def test_failure_never_raises_and_is_reported(monkeypatch, capsys):
    _use(monkeypatch, _Table(fail=True))
    usage_log.log_api_request(3, "gemini_invoice_scan", "success")
    assert "row-level security" in usage_log.last_error
    assert "usage_log" in capsys.readouterr().err
