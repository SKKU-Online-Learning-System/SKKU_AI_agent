"""Synthetic speech through real Silero VAD -> ASR -> voice/RAG -> streaming TTS.

Run in .venv-app (Python 3.12). No browser playback/network timings are measured.
Memory recall/writes are disabled; inference and deferred visuals remain real.
"""
import argparse
import asyncio
import audioop
from dataclasses import asdict
import json
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import wave

from app.core.config import get_settings
from app.services.model_server.speech_client import SpeechClient
from app.services.voice import brain
from app.services.voice.local_cascade import LocalCascadeTransport
from app.services.voice.transport import AgentAudio, AgentTurnDone, Failed
from app.services.voice.turn_detector import FRAME_BYTES


def save_wav(path, pcm, rate):
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(pcm)


async def main(output_path):
    settings = get_settings()
    client = SpeechClient(settings)
    root = Path('/tmp') / Path(output_path).stem
    root.mkdir(exist_ok=True)
    output = Path(output_path)
    for name, text in [('causal', '인과 마스크에서 삼 번 행은 어디까지 볼 수 있어요?'),
                       ('unsure', '설명은 들었는데 아직 잘 모르겠어요.'),
                       ('pause', '잠깐 기다려 주세요.')]:
        synthesized = await client.synthesize(text)
        pcm, _ = audioop.ratecv(synthesized.pcm, 2, 1, synthesized.sample_rate, 16000, None)
        save_wav(root / f'{name}-input.wav', pcm, 16000)
        context = brain.VoiceContext('384a5d06-f329-4e51-8b42-f817273df9c2',
                                     'Transformer 강의', 'voice-audio-eval', None)
        if name != 'causal':
            context.history = [
                {'role': 'user', 'content': '인과 마스크를 공부하자'},
                {'role': 'assistant', 'content': '3번 행은 0번부터 3번 열까지 볼 수 있어요. 왜 그럴까요?'},
            ]
        transport = LocalCascadeTransport(context=context, settings=settings)
        events, metrics, chunks = [], [], []
        started = time.perf_counter()
        fed_until = None

        async def feed():
            nonlocal fed_until
            framed = pcm + b'\0' * ((-len(pcm)) % FRAME_BYTES)
            framed += b'\0' * (16000 * 2 * 2)
            for offset in range(0, len(framed), FRAME_BYTES):
                await transport.send_audio(framed[offset:offset+FRAME_BYTES])
                if offset < len(pcm):
                    fed_until = round((time.perf_counter()-started)*1000)
                await asyncio.sleep(0.02)

        with (patch.object(brain, 'recent_weak_concepts', AsyncMock(return_value={'found': False})),
              patch('app.services.voice.session_store.external_brain_for',
                    return_value=SimpleNamespace(schedule=Mock())),
              patch.object(transport, '_log_metrics', side_effect=lambda **kw: metrics.append(kw))):
            await transport.start()
            feeder = asyncio.create_task(feed())
            try:
                async with asyncio.timeout(180):
                    async for event in transport.events():
                        elapsed = round((time.perf_counter()-started)*1000)
                        if isinstance(event, AgentAudio):
                            chunks.append(event.pcm)
                            if not any(e['type'] == 'AgentAudio' for e in events):
                                events.append({'type': 'AgentAudio', 'ms': elapsed, 'rate': event.rate})
                        else:
                            events.append({'type': type(event).__name__, 'ms': elapsed, **asdict(event)})
                        if isinstance(event, (AgentTurnDone, Failed)):
                            break
                    await feeder
            except TimeoutError:
                events.append({'type': 'timeout'})
            finally:
                feeder.cancel()
                await asyncio.gather(feeder, return_exceptions=True)
                await transport.close()
        save_wav(root / f'{name}-reply.wav', b''.join(chunks), 24000)
        row = {'case': name, 'vad_threshold': settings.vad_threshold, 'synthetic_input': text, 'input_duration_ms': round(len(pcm)/32),
               'input_feed_end_ms': fed_until, 'events': events, 'metrics': metrics,
               'audio_chunks': len(chunks), 'output_duration_ms': round(sum(map(len,chunks))/48),
               'citations': context.last_material_sources,
               'input_wav': str(root / f'{name}-input.wav'),
               'reply_wav': str(root / f'{name}-reply.wav')}
        with output.open('a') as file:
            file.write(json.dumps(row, ensure_ascii=False)+'\n')
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",
                        default="docs/evaluations/voice-post-rag-audio-20260911.jsonl")
    asyncio.run(main(parser.parse_args().output))
