"""Central byte/count limits for every untrusted runtime surface."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeLimits:
    model_text_bytes: int = 1 * 1024 * 1024
    reasoning_bytes: int = 256 * 1024
    tool_arguments_bytes: int = 64 * 1024
    tool_calls_per_turn: int = 64
    history_bytes: int = 8 * 1024 * 1024
    history_messages: int = 500
    event_data_bytes: int = 256 * 1024
    events_per_run: int = 50_000
    cli_stderr_bytes: int = 128 * 1024
    cli_stdout_line_bytes: int = 1 * 1024 * 1024
    cli_stdout_total_bytes: int = 16 * 1024 * 1024
    provider_error_bytes: int = 8 * 1024
    final_message_bytes: int = 1 * 1024 * 1024
    diff_bytes: int = 8 * 1024 * 1024
    projection_bytes: int = 8 * 1024 * 1024


RUNTIME_LIMITS = RuntimeLimits()
