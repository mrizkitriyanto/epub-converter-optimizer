from eco import __version__
from eco.cli import main


def test_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"eco {__version__}"
