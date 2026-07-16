from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from time import monotonic

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.worker import Worker
from textual.widgets import Static

from mewcode.agent import (
    AgentEvent,
    AgentRun,
    AgentSession,
    ConfirmationRequested,
    ConfirmationResolved,
    ProgressChanged,
    RunStarted,
    RunStopped,
    StopReason,
    TextDeltaEvent,
    ToolFinished,
    ToolStarted,
    UsageReported,
)
from mewcode.errors import MewCodeError
from mewcode.tui.metadata import SessionMetadata
from mewcode.tui.presentation import (
    ActivityState,
    ErrorPresentation,
    activity_for_progress,
    activity_for_stop,
    error_for_stop,
    stop_label,
    usage_text,
)
from mewcode.tui.widgets.chrome import (
    ActivityIndicator,
    NewOutputIndicator,
    SessionFooter,
    WelcomeCard,
)
from mewcode.tui.widgets.composer import PromptComposer
from mewcode.tui.widgets.confirmation import ConfirmationModal
from mewcode.tui.widgets.conversation import (
    AssistantMessageView,
    ConversationView,
    ErrorCard,
    ToolCard,
    UserMessageView,
)


class CyberpunkChatApp(App[int]):
    CSS_PATH = "cyberpunk.tcss"
    TITLE = "MewCode"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("escape", "interrupt", "Interrupt", show=False),
        Binding("ctrl+c", "ctrl_c", "Interrupt / exit", show=False, priority=True),
        Binding("ctrl+d", "ctrl_d", "Exit", show=False, priority=True),
        Binding("end", "return_to_bottom", "Latest output", show=False),
    ]

    def __init__(
        self,
        session: AgentSession,
        metadata: SessionMetadata,
        *,
        unicode_output: bool = True,
    ) -> None:
        super().__init__()
        self.session = session
        self.metadata = metadata
        self.unicode_output = unicode_output

        self.activity_state = ActivityState.READY
        self._active_run: AgentRun | None = None
        self._active_run_id: str | None = None
        self._turn_worker: Worker[None] | None = None
        self._activity: ActivityIndicator | None = None
        self._assistant: AssistantMessageView | None = None
        self._tool_cards: dict[str, ToolCard] = {}
        self._confirmation_request_id: str | None = None
        self._exit_armed_until = 0.0
        self._pending_text: list[str] = []
        self._text_flush_task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        yield ConversationView(WelcomeCard(self.metadata))
        yield NewOutputIndicator(unicode=self.unicode_output)
        with Container(id="composer-shell"):
            yield Static("", id="exit-hint")
            yield PromptComposer(unicode=self.unicode_output)
        yield SessionFooter(self.metadata, unicode=self.unicode_output)
        yield Static(
            (
                "Terminal too small — resize to at least 48×14."
                if self.unicode_output
                else "Terminal too small - resize to at least 48x14."
            ),
            id="size-warning",
        )

    def on_mount(self) -> None:
        if "NO_COLOR" in os.environ:
            self.screen.add_class("no-color")
        if not self.unicode_output:
            self.screen.add_class("ascii-output")
        self._apply_size_classes(self.size.width, self.size.height)
        self.query_one(PromptComposer).focus()

    async def on_unmount(self) -> None:
        await self._cancel_text_flush()
        if self._active_run is not None:
            await self._active_run.cancel()
        await self.session.close()

    async def on_prompt_composer_submitted(
        self,
        event: PromptComposer.Submitted,
    ) -> None:
        prompt = event.prompt
        if self._active_run is not None:
            return
        if prompt.strip().lower() in {"exit", "quit"}:
            await self.session.close()
            self.exit(0)
            return

        self._disarm_exit()
        composer = self.query_one(PromptComposer)
        composer.record_submission(prompt)
        composer.set_busy(True)
        await self.query_one(ConversationView).append_widget(
            UserMessageView(prompt, unicode=self.unicode_output)
        )

        try:
            run = await self.session.start(prompt)
        except MewCodeError as exc:
            await self.query_one(ConversationView).append_widget(
                ErrorCard(
                    ErrorPresentation(exc.user_message),
                    unicode=self.unicode_output,
                )
            )
            self._finish_run(ActivityState.ERROR)
            return

        self._active_run = run
        self._active_run_id = run.run_id
        self._assistant = None
        self._tool_cards.clear()
        self._pending_text.clear()
        await self._show_activity(
            ActivityState.UPLINKING,
            f"{self.metadata.model} round 1",
        )
        self._turn_worker = self._consume_run(run)
        composer.focus()

    @work(group="turn", exclusive=True, exit_on_error=False)
    async def _consume_run(self, run: AgentRun) -> None:
        try:
            async for event in run:
                if isinstance(event, TextDeltaEvent):
                    self._queue_text(event)
                    continue
                await self._flush_before_event()
                await self._handle_event(event)
        except asyncio.CancelledError:
            await asyncio.shield(run.cancel())
            raise
        except Exception:
            await asyncio.shield(run.cancel())
            await self._flush_before_event()
            if self._is_current(run.run_id):
                await self._remove_activity()
                await self.query_one(ConversationView).append_widget(
                    ErrorCard(
                        ErrorPresentation(
                            "Internal interface worker failure.",
                            suggestion="Restart MewCode and retry the request.",
                        ),
                        unicode=self.unicode_output,
                    )
                )
                self._finish_run(ActivityState.ERROR)

    async def _handle_event(self, event: AgentEvent) -> None:
        if not self._is_current(event.context.run_id):
            return
        if isinstance(event, RunStarted):
            return
        if isinstance(event, ProgressChanged):
            state, detail = activity_for_progress(event)
            await self._show_activity(state, detail)
            return
        if isinstance(event, ToolStarted):
            await self._finalize_assistant()
            await self._remove_activity()
            card = ToolCard(event, unicode=self.unicode_output)
            self._tool_cards[event.call_id] = card
            await self.query_one(ConversationView).append_widget(card)
            await self._show_activity(ActivityState.EXECUTING, event.name)
            return
        if isinstance(event, ToolFinished):
            card = self._tool_cards.get(event.call_id)
            if card is not None:
                card.finish(event)
                self.query_one(ConversationView).note_output()
            return
        if isinstance(event, ConfirmationRequested):
            self._confirmation_request_id = event.request_id
            await self._show_activity(
                ActivityState.CONFIRMING,
                event.preview.title,
            )

            def resolve(approved: bool) -> None:
                run = self._active_run
                if run is not None and self._confirmation_request_id == event.request_id:
                    run.resolve_confirmation(event.request_id, approved)
                    self._confirmation_request_id = None

            self.push_screen(ConfirmationModal(event.preview), resolve)
            return
        if isinstance(event, ConfirmationResolved):
            if self._confirmation_request_id == event.request_id:
                self._confirmation_request_id = None
            return
        if isinstance(event, UsageReported):
            await self.query_one(ConversationView).append_widget(
                Static(usage_text(event), classes="usage", markup=False)
            )
            return
        if isinstance(event, RunStopped):
            await self._handle_stop(event)

    def _queue_text(self, event: TextDeltaEvent) -> None:
        if not self._is_current(event.context.run_id):
            return
        self._pending_text.append(event.text)
        if self._text_flush_task is None:
            self._text_flush_task = asyncio.create_task(self._flush_after_yield())

    async def _flush_after_yield(self) -> None:
        try:
            await asyncio.sleep(0)
            await self._flush_pending_text()
        finally:
            if self._text_flush_task is asyncio.current_task():
                self._text_flush_task = None

    async def _flush_before_event(self) -> None:
        task = self._text_flush_task
        self._text_flush_task = None
        if task is not None and task is not asyncio.current_task() and not task.done():
            with suppress(asyncio.CancelledError):
                await task
        await self._flush_pending_text()

    async def _cancel_text_flush(self) -> None:
        task = self._text_flush_task
        self._text_flush_task = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._pending_text.clear()

    async def _flush_pending_text(self) -> None:
        if not self._pending_text or self._active_run_id is None:
            return
        text = "".join(self._pending_text)
        self._pending_text.clear()
        await self._render_text(text)

    async def _render_text(self, text: str) -> None:
        if self._activity is not None:
            await self._activity.remove()
            self._activity = None
        if self._assistant is None:
            self._assistant = AssistantMessageView(unicode=self.unicode_output)
            await self.query_one(ConversationView).append_widget(self._assistant)
        self._set_activity(ActivityState.STREAMING)
        await self._assistant.append_markdown(text)
        self.query_one(ConversationView).note_output()

    async def _handle_stop(self, event: RunStopped) -> None:
        if event.reason is StopReason.CANCELLED:
            await self._mark_interrupted()
            for card in self._tool_cards.values():
                card.interrupt()
        else:
            await self._finalize_assistant()
        await self._remove_activity()
        error = error_for_stop(event)
        if error is not None:
            await self.query_one(ConversationView).append_widget(
                ErrorCard(error, unicode=self.unicode_output)
            )
        elif event.reason is not StopReason.COMPLETED:
            await self.query_one(ConversationView).append_widget(
                Static(stop_label(event), classes="status-warning", markup=False)
            )
        self._finish_run(activity_for_stop(event))

    async def action_interrupt(self) -> None:
        run = self._active_run
        if run is None:
            return
        if isinstance(self.screen, ConfirmationModal):
            self.screen.dismiss(False)
        await run.cancel()
        await self._mark_interrupted()
        for card in self._tool_cards.values():
            card.interrupt()
        self._set_activity(ActivityState.INTERRUPTED)

    async def action_ctrl_c(self) -> None:
        if self._active_run is not None:
            await self.action_interrupt()
            return
        composer = self.query_one(PromptComposer)
        if composer.text:
            composer.load_text("")
            composer.prompt_history.reset_navigation()
            self._disarm_exit()
            return
        now = monotonic()
        if now <= self._exit_armed_until:
            await self.session.close()
            self.exit(0)
            return
        self._exit_armed_until = now + 2.0
        self.query_one("#exit-hint", Static).update(
            "Press Ctrl+C again within 2s to exit."
        )

    async def action_ctrl_d(self) -> None:
        composer = self.query_one(PromptComposer)
        if self._active_run is None and not composer.text:
            await self.session.close()
            self.exit(0)

    def action_return_to_bottom(self) -> None:
        self.query_one(ConversationView).return_to_bottom()

    def on_conversation_view_unread_changed(
        self,
        message: ConversationView.UnreadChanged,
    ) -> None:
        self.query_one(NewOutputIndicator).set_count(message.count)

    def on_new_output_indicator_return_to_bottom(
        self,
        message: NewOutputIndicator.ReturnToBottom,
    ) -> None:
        self.action_return_to_bottom()

    def on_resize(self, event: events.Resize) -> None:
        self._apply_size_classes(event.size.width, event.size.height)

    def _apply_size_classes(self, width: int, height: int) -> None:
        screen = self.screen_stack[0] if self.screen_stack else self.screen
        was_too_small = screen.has_class("too-small")
        for class_name in ("wide", "compact", "narrow", "too-small"):
            screen.remove_class(class_name)
        is_too_small = width < 48 or height < 14
        if is_too_small:
            screen.add_class("too-small")
        elif width >= 100:
            screen.add_class("wide")
        elif width >= 72:
            screen.add_class("compact")
        else:
            screen.add_class("narrow")
        self.query_one(NewOutputIndicator).set_size_hidden(is_too_small)
        if was_too_small and not is_too_small and self.screen is screen:
            self.call_after_refresh(self.query_one(PromptComposer).focus)

    async def _show_activity(
        self,
        state: ActivityState,
        detail: str | None = None,
    ) -> None:
        if self._activity is None:
            self._activity = ActivityIndicator(unicode=self.unicode_output)
            await self.query_one(ConversationView).append_widget(self._activity)
        self._activity.set_activity(state, detail)
        self._set_activity(state)

    async def _remove_activity(self) -> None:
        if self._activity is not None:
            await self._activity.remove()
            self._activity = None

    async def _finalize_assistant(self) -> None:
        if self._assistant is not None:
            await self._assistant.finalize()
            self._assistant = None

    async def _mark_interrupted(self) -> None:
        if self._assistant is not None:
            await self._assistant.mark_interrupted()
            self._assistant = None
        elif self._activity is not None:
            self._activity.set_activity(ActivityState.INTERRUPTED)

    def _set_activity(self, state: ActivityState) -> None:
        self.activity_state = state
        self.query_one(SessionFooter).set_status(state)

    def _finish_run(self, state: ActivityState) -> None:
        self._set_activity(state)
        self._active_run = None
        self._active_run_id = None
        self._turn_worker = None
        self._confirmation_request_id = None
        composer = self.query_one(PromptComposer)
        composer.set_busy(False)
        composer.focus()

    def _is_current(self, run_id: str) -> bool:
        return run_id == self._active_run_id

    def _disarm_exit(self) -> None:
        self._exit_armed_until = 0.0
        self.query_one("#exit-hint", Static).update("")
