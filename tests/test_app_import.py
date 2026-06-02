from fastapi import FastAPI


def test_app_import_smoke() -> None:
    from app.api.main import app

    assert isinstance(app, FastAPI)
    assert app.title == "Finance Assistant Bot"
