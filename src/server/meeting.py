"""
Meeting assistant — real-time transcription, speaker diarization, and minutes.

Features:
  - Continuous audio capture and transcription
  - Speaker separation (voice print clustering)
  - Automatic meeting minutes generation
  - Action item extraction
"""

import asyncio
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

MEETING_DIR = Path("data/meetings")
MEETING_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Utterance:
    speaker: str
    text: str
    start_time: float
    end_time: float = 0.0
    emotion: str = "neutral"


@dataclass
class MeetingRecord:
    id: str
    title: str
    start_time: float
    end_time: float = 0.0
    utterances: List[Utterance] = field(default_factory=list)
    participants: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)
    summary: str = ""


class SpeakerDiarizer:
    """Simple speaker separation based on voice embeddings."""

    def __init__(self):
        self._embeddings: Dict[str, list] = {}
        self._speaker_count = 0

    def identify(self, audio_segment) -> str:
        """
        Identify or assign a speaker label.
        Uses basic energy-based heuristic as a starting point;
        can be upgraded to use resemblyzer or pyannote.
        """
        try:
            import numpy as np
            energy = float(np.sqrt(np.mean(audio_segment ** 2)))
            volume_bin = "loud" if energy > 0.05 else "quiet"
            label = f"Speaker_{volume_bin}"
            return label
        except Exception:
            self._speaker_count += 1
            return f"Speaker_{self._speaker_count}"

    def get_speakers(self) -> List[str]:
        return list(set(self._embeddings.keys())) or ["Speaker_1"]


class MeetingAssistant:
    """Manages a meeting session: capture -> transcribe -> summarize."""

    def __init__(self, stt=None, ai_router=None):
        self._stt = stt
        self._router = ai_router
        self._diarizer = SpeakerDiarizer()
        self._current: Optional[MeetingRecord] = None
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def current_meeting(self) -> Optional[MeetingRecord]:
        return self._current

    def start_meeting(self, title: str = "") -> MeetingRecord:
        meeting_id = f"meeting_{int(time.time())}"
        self._current = MeetingRecord(
            id=meeting_id,
            title=title or f"Meeting {time.strftime('%Y-%m-%d %H:%M')}",
            start_time=time.time(),
        )
        self._recording = True
        logger.info(f"Meeting started: {self._current.title}")
        return self._current

    def stop_meeting(self) -> Optional[MeetingRecord]:
        if not self._current:
            return None
        self._current.end_time = time.time()
        self._recording = False
        self._save_meeting()
        logger.info(
            f"Meeting ended: {self._current.title} "
            f"({len(self._current.utterances)} utterances)")
        return self._current

    async def process_audio_chunk(
        self, audio, timestamp: float = 0.0
    ) -> Optional[Utterance]:
        if not self._recording or not self._stt:
            return None

        try:
            result = await self._stt.transcribe(audio)
            if not result.text or len(result.text.strip()) < 2:
                return None

            speaker = self._diarizer.identify(audio)
            utt = Utterance(
                speaker=speaker,
                text=result.text.strip(),
                start_time=timestamp or time.time(),
                emotion=result.emotion,
            )
            self._current.utterances.append(utt)

            if speaker not in self._current.participants:
                self._current.participants.append(speaker)

            return utt
        except Exception as e:
            logger.debug(f"Meeting chunk error: {e}")
            return None

    async def generate_minutes(self) -> str:
        if not self._current or not self._current.utterances:
            return "没有会议记录可生成纪要。"

        transcript = self._format_transcript()

        if self._router:
            try:
                prompt = (
                    "请根据以下会议转录生成一份结构化的会议纪要，包括：\n"
                    "1. 会议主题\n"
                    "2. 主要讨论内容（按议题分段）\n"
                    "3. 关键决策\n"
                    "4. 行动项（TODO，标注负责人）\n\n"
                    f"会议转录：\n{transcript}"
                )
                minutes = ""
                async for chunk, _pid in self._router.chat_stream(
                    [{"role": "user", "content": prompt}],
                    max_tokens=1000,
                ):
                    if not chunk.startswith("__"):
                        minutes += chunk

                self._current.summary = minutes
                self._current.action_items = self._extract_actions(minutes)
                self._save_meeting()
                return minutes
            except Exception as e:
                logger.error(f"Minutes generation failed: {e}")

        return self._simple_minutes()

    def _format_transcript(self) -> str:
        lines = []
        for u in self._current.utterances:
            ts = time.strftime("%H:%M:%S",
                               time.localtime(u.start_time))
            lines.append(f"[{ts}] {u.speaker}: {u.text}")
        return "\n".join(lines)

    def _simple_minutes(self) -> str:
        meeting = self._current
        lines = [
            f"# 会议纪要 — {meeting.title}",
            f"时间: {time.strftime('%Y-%m-%d %H:%M', time.localtime(meeting.start_time))}",
            f"参与者: {', '.join(meeting.participants)}",
            f"发言数: {len(meeting.utterances)}",
            "",
            "## 转录记录",
            self._format_transcript(),
        ]
        return "\n".join(lines)

    @staticmethod
    def _extract_actions(text: str) -> List[str]:
        actions = []
        for line in text.split("\n"):
            line = line.strip()
            if any(kw in line for kw in
                   ("TODO", "行动项", "负责人", "截止", "待办")):
                actions.append(line)
        return actions

    def _save_meeting(self):
        if not self._current:
            return
        path = MEETING_DIR / f"{self._current.id}.json"
        data = {
            "id": self._current.id,
            "title": self._current.title,
            "start_time": self._current.start_time,
            "end_time": self._current.end_time,
            "participants": self._current.participants,
            "utterances": [
                {"speaker": u.speaker, "text": u.text,
                 "start": u.start_time, "emotion": u.emotion}
                for u in self._current.utterances
            ],
            "summary": self._current.summary,
            "action_items": self._current.action_items,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    @staticmethod
    def list_meetings() -> List[dict]:
        meetings = []
        for f in sorted(MEETING_DIR.glob("meeting_*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                meetings.append({
                    "id": data["id"],
                    "title": data["title"],
                    "start_time": data["start_time"],
                    "utterances": len(data.get("utterances", [])),
                    "has_summary": bool(data.get("summary")),
                })
            except Exception:
                pass
        return meetings
