"""
Text and transcript chunking engine.
Preserves speaker metadata, timestamps, and segment linkages across chunks.
"""
from typing import List, Dict, Any, Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.config import settings


class TranscriptChunk:
    def __init__(
        self,
        text: str,
        speaker: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        segment_indices: Optional[List[int]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.text = text
        self.speaker = speaker
        self.start_time = start_time
        self.end_time = end_time
        self.segment_indices = segment_indices or []
        self.metadata = metadata or {}


class TranscriptChunker:
    def __init__(
        self,
        chunk_size: int = settings.CHUNK_SIZE,
        chunk_overlap: int = settings.CHUNK_OVERLAP,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def chunk_transcript_segments(self, segments: List[Dict[str, Any]]) -> List[TranscriptChunk]:
        """
        Group consecutive speaker utterances and split into semantic chunks.
        Each chunk is annotated with the dominant speaker, time window, and text.
        """
        if not segments:
            return []

        chunks: List[TranscriptChunk] = []

        # 1. First format transcript with speaker tags
        formatted_blocks = []
        for i, seg in enumerate(segments):
            speaker = seg.get("speaker") or "Unknown"
            text = (seg.get("text") or "").strip()
            start_t = seg.get("start_time")
            end_t = seg.get("end_time")
            if text:
                formatted_blocks.append({
                    "index": i,
                    "speaker": speaker,
                    "start_time": start_t,
                    "end_time": end_t,
                    "text": f"{speaker}: {text}",
                })

        if not formatted_blocks:
            return []

        # 2. Merge consecutive blocks up to chunk_size
        current_text = []
        current_len = 0
        current_start = formatted_blocks[0]["start_time"]
        current_end = formatted_blocks[0]["end_time"]
        current_indices = []
        current_speakers = set()

        for block in formatted_blocks:
            block_len = len(block["text"])
            if current_len + block_len > self.chunk_size and current_text:
                # Flush chunk
                combined_text = "\n".join(current_text)
                dominant_speaker = list(current_speakers)[0] if len(current_speakers) == 1 else "Multiple"
                chunks.append(
                    TranscriptChunk(
                        text=combined_text,
                        speaker=dominant_speaker,
                        start_time=current_start,
                        end_time=current_end,
                        segment_indices=list(current_indices),
                        metadata={"speakers": list(current_speakers)},
                    )
                )
                # Overlap: keep last block if possible
                if self.chunk_overlap > 0 and len(current_text) > 1:
                    last_block = formatted_blocks[block["index"] - 1]
                    current_text = [last_block["text"], block["text"]]
                    current_len = len(last_block["text"]) + block_len
                    current_start = last_block["start_time"]
                    current_end = block["end_time"]
                    current_indices = [last_block["index"], block["index"]]
                    current_speakers = {last_block["speaker"], block["speaker"]}
                else:
                    current_text = [block["text"]]
                    current_len = block_len
                    current_start = block["start_time"]
                    current_end = block["end_time"]
                    current_indices = [block["index"]]
                    current_speakers = {block["speaker"]}
            else:
                current_text.append(block["text"])
                current_len += block_len
                current_end = block["end_time"]
                current_indices.append(block["index"])
                current_speakers.add(block["speaker"])

        # Flush final chunk
        if current_text:
            combined_text = "\n".join(current_text)
            dominant_speaker = list(current_speakers)[0] if len(current_speakers) == 1 else "Multiple"
            chunks.append(
                TranscriptChunk(
                    text=combined_text,
                    speaker=dominant_speaker,
                    start_time=current_start,
                    end_time=current_end,
                    segment_indices=list(current_indices),
                    metadata={"speakers": list(current_speakers)},
                )
            )

        return chunks


transcript_chunker = TranscriptChunker()
