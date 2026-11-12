import io
import zipfile

from app.logs import affected_file, extract, extract_from_zip


def _log() -> str:
    return "\n".join(
        [
            "2024-11-01T12:00:00.0000000Z Current runner version: '2.320.0'",
            "2024-11-01T12:00:01.0000000Z ##[group]Run pip install",
            "2024-11-01T12:00:01.1000000Z 40% downloading wheels",
            "2024-11-01T12:00:01.2000000Z 40% downloading wheels",
            "2024-11-01T12:00:01.3000000Z Affected file: requirements.txt",
            "2024-11-01T12:00:01.4000000Z ERROR: ResolutionImpossible cannot install numpy",
            "2024-11-01T12:00:01.5000000Z TOKEN=ghp_abcdefghijklmnopqrstuvwxyz012345",
            "2024-11-01T12:00:01.6000000Z ##[error]Process completed with exit code 1.",
            "2024-11-01T12:00:01.7000000Z ##[endgroup]",
        ]
    )


def test_extract_trims_redacts_and_signatures():
    prepared = extract(_log())
    assert "2024-11-01" not in prepared.error_window
    assert "downloading wheels" not in prepared.error_window
    assert "ghp_" not in prepared.error_window
    assert "[REDACTED]" in prepared.error_window
    assert "process completed with exit code" not in prepared.signature
    assert "resolutionimpossible" in prepared.signature
    assert affected_file(_log()) == "requirements.txt"


def test_extract_from_zip_reads_job_files():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("0_build.txt", _log())
    prepared = extract_from_zip(buffer.getvalue())
    assert "resolutionimpossible" in prepared.signature
