"""Conservative transcription estimates; preparation/download time is not predicted."""
from datetime import datetime, timezone, timedelta
import math
import sqlite3


def queue_estimates(connection: sqlite3.Connection, clock: datetime | None = None) -> dict:
    clock = clock or datetime.now(timezone.utc)
    samples = connection.execute("""
        SELECT t.seconds, t.duration_ms, r.model_source FROM transcription_timings t
        JOIN runs r ON r.id=t.run_id JOIN videos v ON v.id=r.video_id
        WHERE r.state='succeeded' AND v.platform!='fixture' AND t.seconds>0 AND t.duration_ms>0
        ORDER BY t.rowid DESC LIMIT 20
    """).fetchall()
    rows = connection.execute("""
        SELECT v.id, v.duration_ms, v.paused, r.state, r.current_step, r.model_source, c.started_at
        FROM videos v JOIN runs r ON r.id=v.active_run_id
        LEFT JOIN step_clocks c ON c.run_id=r.id
        WHERE v.stage='processing' AND r.state IN ('queued','running')
        ORDER BY CASE WHEN r.state='running' AND v.paused=0 THEN 0 ELSE 1 END, r.rowid
    """).fetchall()
    result, ahead, position = {}, 0.0, 0
    for row in rows:
        matching = [s for s in samples if s['model_source'] == row['model_source']]
        # Duration-weighted recent speed: 60s/60s + 120s/120s => 1 second per second.
        rate = sum(s['seconds'] for s in matching) / (sum(s['duration_ms'] for s in matching)/1000) if matching else None
        total = row['duration_ms']/1000*rate if rate and row['duration_ms'] else None
        value = dict(status='learning', sample_count=len(matching), transcription_seconds=round(total) if total else None,
                     remaining_seconds=None, estimated_finish_at=None, queue_position=None, ahead_seconds=None)
        result[row['id']] = value
        if row['paused']:
            value['status'] = 'paused'
            continue
        position += 1
        value['queue_position'] = position
        value['ahead_seconds'] = math.ceil(ahead) if ahead is not None else None
        if rate is None:
            ahead = None
            continue
        if total is None:
            value['status'] = 'unknown_duration'
            ahead = None
            continue
        if row['state'] == 'queued':
            value['status'] = 'waiting'
            ahead = ahead + total if ahead is not None else None
        elif row['current_step'] == 'transcribe' and row['started_at']:
            elapsed = max(0, (clock-datetime.fromisoformat(row['started_at'])).total_seconds())
            remaining = total-elapsed
            if remaining <= 0:
                value['status'] = 'overdue'
                ahead = None
            else:
                value.update(status='estimating', remaining_seconds=math.ceil(remaining),
                             estimated_finish_at=(clock+timedelta(seconds=remaining)).isoformat())
                ahead = remaining
        else:
            value['status'] = 'finishing' if row['current_step'] in ('format','publish') else 'preparing'
            ahead = None
    return result
