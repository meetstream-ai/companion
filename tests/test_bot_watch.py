"""
The bot watcher: a launched bot's meeting follows the call and is processed
afterwards even when MeetStream's webhooks never reach this install.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.database.connection import get_db_context
from app.database.repositories import MeetingRepository
from app.services.bot_watch import (
    NO_TRANSCRIPT_MESSAGE,
    BotWatcher,
    local_status,
    ready_transcript_id,
    transcription_failure,
)
from tests.test_webhooks import _launch


class FakeMeetStream:
    """Answers status and transcription-run queries from a script."""

    def __init__(self, status="Joining", runs=None, status_error=None):
        self.status = status
        self.runs = runs or []
        self.status_error = status_error
        self.calls = []

    async def get_bot_status(self, bot_id, api_key=None):
        self.calls.append(("status", bot_id, api_key))
        if self.status_error:
            raise self.status_error
        return self.status

    async def list_bot_transcriptions(self, bot_id, api_key=None):
        self.calls.append(("runs", bot_id, api_key))
        return list(self.runs)


class FakePipeline:
    def __init__(self):
        self.started = []

    def start_in_background(self, meeting_id, **kwargs):
        self.started.append((meeting_id, kwargs))


async def _meeting(meeting_id):
    async with get_db_context() as db:
        return await MeetingRepository(db).get_by_id_unscoped(uuid.UUID(meeting_id))


def test_meetstream_states_map_to_ours():
    assert local_status("Joining") == "joining"
    assert local_status("InWaitingRoom") == "joining"
    assert local_status("InMeeting") == "in_meeting"
    assert local_status("in_meeting") == "in_meeting"
    assert local_status("Recording") == "recording"
    assert local_status("MediaProcessing") == "stopped"
    assert local_status("Done") == "completed"
    assert local_status("NotAllowed") == "failed"
    assert local_status("SomethingNew") is None


#: What MeetStream really lists: the platform's caption file sits next to
#: the transcription run, "Success" with no transcript id.
CAPTIONS = {"transcript_id": None, "provider": "meeting_captions", "status": "Success"}


def test_finished_run_is_found_by_meetstreams_spelling():
    runs = [{"transcript_id": "t-new", "status": "Processing"}, {"transcript_id": "t-old", "status": "Success"}, CAPTIONS]
    assert ready_transcript_id(runs) == "t-old"
    assert ready_transcript_id([{"transcript_id": "t", "status": "Failed"}, CAPTIONS]) is None
    assert ready_transcript_id([CAPTIONS]) is None


def test_failed_run_reports_meetstreams_reason():
    runs = [{"transcript_id": "t", "status": "Failed", "error": "Transcript processing failed. Check recording availability."}, CAPTIONS]
    assert transcription_failure(runs) == "Transcript processing failed. Check recording availability."
    assert transcription_failure([CAPTIONS]) is None
    assert transcription_failure([{"transcript_id": "t", "status": "Processing"}, {"transcript_id": "u", "status": "Failed"}]) is None


@pytest.mark.asyncio
async def test_meeting_follows_the_bot_and_is_processed_after_the_call(authed_client, monkeypatch):
    meeting = await _launch(authed_client, monkeypatch)
    meetstream = FakeMeetStream(status="Joining")
    pipeline = FakePipeline()
    watcher = BotWatcher(client=meetstream, pipeline=pipeline)

    await watcher.sweep()
    assert (await _meeting(meeting["id"])).status == "joining"
    # The bot's own key, not the default one, is what the poll is made with.
    assert meetstream.calls[0] == ("status", "bot-123", "ms_test")

    meetstream.status = "InMeeting"
    await watcher.sweep()
    row = await _meeting(meeting["id"])
    assert row.status == "in_meeting"
    assert row.started_at is not None
    assert pipeline.started == []

    # The call ends; MeetStream is still transcribing.
    meetstream.status = "Stopped"
    meetstream.runs = [{"transcript_id": "tr-123", "status": "Processing"}, CAPTIONS]
    await watcher.sweep()
    row = await _meeting(meeting["id"])
    assert row.status == "stopped"
    assert row.ended_at is not None
    assert row.processing_status == "pending"
    assert pipeline.started == []

    meetstream.status = "Done"
    meetstream.runs = [{"transcript_id": "tr-123", "status": "Success"}, CAPTIONS]
    assert await watcher.sweep() == [uuid.UUID(meeting["id"])]
    row = await _meeting(meeting["id"])
    assert row.status == "completed"
    assert row.processing_status == "queued_for_processing"
    assert pipeline.started == [(uuid.UUID(meeting["id"]), {"transcript_id": "tr-123"})]

    # Claimed once: the next sweep has nothing to do with it.
    await watcher.sweep()
    assert len(pipeline.started) == 1


@pytest.mark.asyncio
async def test_watcher_runs_the_real_pipeline(authed_client, monkeypatch):
    from app.services.processing import processing_pipeline

    meeting = await _launch(authed_client, monkeypatch)
    watcher = BotWatcher(client=FakeMeetStream(status="Done", runs=[{"transcript_id": "tr-123", "status": "Success"}]))
    await watcher.sweep()
    await processing_pipeline.wait_for(uuid.UUID(meeting["id"]))

    r = await authed_client.get(f"/api/meetings/{meeting['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["processing_status"] == "completed"
    assert body["memories"] or body["action_items"] or body["summary"]


@pytest.mark.asyncio
async def test_webhook_finds_nothing_left_once_the_watcher_claimed(authed_client, monkeypatch):
    from app.api.webhooks import process_webhook_event_async

    meeting = await _launch(authed_client, monkeypatch)
    pipeline = FakePipeline()
    watcher = BotWatcher(client=FakeMeetStream(status="Done", runs=[{"transcript_id": "tr-123", "status": "Success"}]), pipeline=pipeline)
    await watcher.sweep()
    assert len(pipeline.started) == 1

    async def never(*args, **kwargs):
        raise AssertionError("the pipeline must not run a second time")

    monkeypatch.setattr("app.services.processing.processing_pipeline.process_meeting_transcript", never)
    await process_webhook_event_async(uuid.uuid4(), "bot-123", "transcription.processed", {"bot_id": "bot-123"})
    assert (await _meeting(meeting["id"])).processing_status == "queued_for_processing"


@pytest.mark.asyncio
async def test_bot_turned_away_is_a_failed_meeting(authed_client, monkeypatch):
    meeting = await _launch(authed_client, monkeypatch)
    watcher = BotWatcher(client=FakeMeetStream(status="Denied"), pipeline=FakePipeline())
    await watcher.sweep()
    row = await _meeting(meeting["id"])
    assert row.status == "failed"
    assert row.processing_status == "failed"
    assert "did not admit" in row.processing_error
    # Failed is final: it is not polled again.
    async with get_db_context() as db:
        assert await MeetingRepository(db).list_awaiting_bot() == []


@pytest.mark.asyncio
async def test_failed_transcription_is_reported_not_retried_forever(authed_client, monkeypatch):
    meeting = await _launch(authed_client, monkeypatch)
    pipeline = FakePipeline()
    runs = [{"transcript_id": "tr-123", "status": "Failed", "error": "Transcript processing failed."}, CAPTIONS]
    watcher = BotWatcher(client=FakeMeetStream(status="Done", runs=runs), pipeline=pipeline)
    await watcher.sweep()
    row = await _meeting(meeting["id"])
    assert row.status == "completed"
    assert row.processing_status == "failed"
    assert row.processing_error.startswith("MeetStream could not transcribe this call (Transcript processing failed).")
    assert pipeline.started == []


@pytest.mark.asyncio
async def test_bot_meetstream_forgot_is_failed(authed_client, monkeypatch):
    meeting = await _launch(authed_client, monkeypatch)
    request = httpx.Request("GET", "https://api.meetstream.ai/api/v1/bots/bot-123/status")
    error = httpx.HTTPStatusError("gone", request=request, response=httpx.Response(404, request=request))
    watcher = BotWatcher(client=FakeMeetStream(status_error=error), pipeline=FakePipeline())
    await watcher.sweep()
    row = await _meeting(meeting["id"])
    assert row.status == "failed"
    assert "no longer knows" in row.processing_error


@pytest.mark.asyncio
async def test_meetstream_outage_changes_nothing(authed_client, monkeypatch):
    meeting = await _launch(authed_client, monkeypatch)
    watcher = BotWatcher(client=FakeMeetStream(status_error=httpx.ConnectError("down")), pipeline=FakePipeline())
    await watcher.sweep()
    row = await _meeting(meeting["id"])
    assert row.status == "joining"
    assert row.processing_status == "pending"


@pytest.mark.asyncio
async def test_call_that_ended_long_ago_with_no_transcript_gives_up(authed_client, monkeypatch):
    meeting = await _launch(authed_client, monkeypatch)
    async with get_db_context() as db:
        await MeetingRepository(db).update_status(
            uuid.UUID(meeting["id"]), status="stopped", ended_at=datetime.now(timezone.utc) - timedelta(hours=7)
        )
        await db.commit()
    watcher = BotWatcher(client=FakeMeetStream(status="Stopped", runs=[CAPTIONS]), pipeline=FakePipeline())
    await watcher.sweep()
    row = await _meeting(meeting["id"])
    assert row.processing_status == "failed"
    assert row.processing_error == NO_TRANSCRIPT_MESSAGE
