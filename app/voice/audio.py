"""Ограниченное преобразование Ogg/WebM в одноканальный Ogg Opus для SpeechKit."""
import asyncio
import math
from pathlib import Path
from tempfile import TemporaryDirectory


class AudioError(Exception):
    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code
        super().__init__(code)


async def run(*args: str) -> bytes:
    try:
        process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    except FileNotFoundError as error:
        raise AudioError(503, "stt_unavailable") from error
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5)
    except (TimeoutError, asyncio.CancelledError):
        process.kill()
        await process.communicate()
        raise
    if process.returncode:
        raise AudioError(415, "unsupported_audio")
    return stdout


async def ogg_opus(audio: bytes, kind: str) -> bytes:
    if kind not in ("audio/webm", "audio/ogg"):
        raise AudioError(415, "unsupported_audio")
    if len(audio) > 1024 * 1024:
        raise AudioError(413, "audio_too_long")
    with TemporaryDirectory(prefix="stevens-audio-") as directory:
        source, result = Path(directory) / "source", Path(directory) / "result.ogg"
        source.write_bytes(audio)
        try:
            await run("ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-threads", "1",
                      "-f", "matroska" if kind == "audio/webm" else "ogg", "-i", str(source),
                      "-map", "0:a:0", "-vn", "-t", "30.1", "-ac", "1", "-ar", "16000",
                      "-map_metadata", "-1", "-c:a", "libopus", "-b:a", "24k", "-f", "ogg", str(result))
            duration = float((await run("ffprobe", "-v", "error", "-show_entries", "format=duration",
                                       "-of", "default=noprint_wrappers=1:nokey=1", str(result))).decode().strip())
        except TimeoutError as error:
            raise AudioError(503, "stt_unavailable") from error
        except ValueError as error:
            raise AudioError(415, "unsupported_audio") from error
        # Небольшой допуск только на служебные семплы Opus; >30-секундная речь не обрезается молча.
        if not math.isfinite(duration) or duration > 30.05:
            raise AudioError(413, "audio_too_long")
        normalized = result.read_bytes()
        if len(normalized) > 1024 * 1024:
            raise AudioError(413, "audio_too_long")
        return normalized
