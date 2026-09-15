import pytest

from otwin.runtime import engine_available

BACKENDS = ["numpy"] + (["rust"] if engine_available() else [])


@pytest.fixture(params=BACKENDS)
def backend(request):
    return request.param


def pytest_configure(config):
    config.addinivalue_line("markers", "rust: needs the otwin_engine extension")
