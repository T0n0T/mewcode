from __future__ import annotations

import os
from threading import Lock
from time import monotonic

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.message import Message
from textual.widgets import Static
from textual.worker import Worker

from mewcode.errors import MewCodeError
from mewcode.runtime import ChatRuntime
from mewcode.tui.events import (
    ActivityState,
    ConfirmationRequestedMessage,
    INTERNAL_ERROR_SUGGESTION,
    ToolBudgetMessage,
    ToolFinishedMessage,
    ToolStartedMessage,
    TOOL_BUDGET_SUGGESTION,
    TurnCompletedMessage,
    TurnErrorMessage,
    TurnErrorPayload,
    TurnInterruptedMessage,
    TurnLifecyclePayload,
    TurnPhaseMessage,
    TurnPhasePayload,
    TurnTextMessage,
    TurnTextPayload,
)
from mewcode.tui.interaction import TuiEventBridge
from mewcode.tui.metadata import SessionMetadata
from mewcode.tui.widgets import (
    ActivityIndicator,
    AssistantMessageView,
    ConfirmationModal,
    ConversationView,
    ErrorCard,
    NewOutputIndicator,
    PromptComposer,
    SessionFooter,
    ToolCard,
    UserMessageView,
    WelcomeCard,
)
from mewcode.turns import (
    TurnCancellation,
    TurnCompleted,
    TurnInterrupted,
    TurnPhase,
    TurnPhaseChanged,
    TurnTextDelta,
)


class TextFlushRequested(Message):
    """Ask the Textual thread to drain one generation's pending text."""

    def __init__(self, generation_id: int) -> None:
        super().__init__()
        self.generation_id = generation_id


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
        runtime: ChatRuntime,
        metadata: SessionMetadata,
        bridge: TuiEventBridge,
        *,
        unicode_output: bool = True,
    ) -> None:
        super().__init__()
        self.runtime = runtime
        self.metadata = metadata
        self.bridge = bridge
        self.unicode_output = unicode_output

        self.activity_state = ActivityState.READY
        self._generation_counter = 0
        self._active_generation: int | None = None
        self._cancellation: TurnCancellation | None = None
        self._turn_worker: Worker[None] | None = None
        self._activity: ActivityIndicator | None = None
        self._assistant: AssistantMessageView | None = None
        self._tool_cards: dict[str, ToolCard] = {}
        self._confirmation = None
        self._exit_armed_until = 0.0

        self._text_lock = Lock()
        self._text_buffers: dict[int, list[str]] = {}
        self._flush_scheduled: set[int] = set()
        self._interrupted_generations: set[int] = set()

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
        self.bridge.bind(self)
        if "NO_COLOR" in os.environ:
            self.screen.add_class("no-color")
        if not self.unicode_output:
            self.screen.add_class("ascii-output")
        self._apply_size_classes(self.size.width, self.size.height)
        self.query_one(PromptComposer).focus()

    def on_unmount(self) -> None:
        if self._cancellation is not None:
            self._cancellation.cancel()
        if self._confirmation is not None:
            self.bridge.resolve_confirmation(self._confirmation, False)
        self.bridge.close()

    async def on_prompt_composer_submitted(
        self,
        event: PromptComposer.Submitted,
    ) -> None:
        prompt = event.prompt
        if self._active_generation is not None:
            return
        if prompt.strip().lower() in {"exit", "quit"}:
            self.exit(0)
            return

        self._disarm_exit()
        composer = self.query_one(PromptComposer)
        composer.record_submission(prompt)
        composer.set_busy(True)
        conversation = self.query_one(ConversationView)
        await conversation.append_widget(
            UserMessageView(prompt, unicode=self.unicode_output)
        )

        self._generation_counter += 1
        generation_id = self._generation_counter
        self._active_generation = generation_id
        self.bridge.begin_generation(generation_id)
        cancellation = TurnCancellation()
        self._cancellation = cancellation
        self._assistant = None
        self._tool_cards.clear()
        await self._show_activity(
            ActivityState.UPLINKING,
            self.metadata.model,
        )
        self._turn_worker = self._run_turn(generation_id, prompt, cancellation)
        composer.focus()

    @work(thread=True, group="turn", exclusive=True, exit_on_error=False)
    def _run_turn(
        self,
        generation_id: int,
        prompt: str,
        cancellation: TurnCancellation,
    ) -> None:
        try:
            for event in self.runtime.stream_turn(prompt, cancellation):
                if isinstance(event, TurnTextDelta):
                    self._queue_text(generation_id, event.text)
                elif isinstance(event, TurnPhaseChanged):
                    self._flush_text_from_thread(generation_id)
                    self._post_from_thread(
                        TurnPhaseMessage(
                            TurnPhasePayload(generation_id, event.phase)
                        )
                    )
                elif isinstance(event, TurnCompleted):
                    self._flush_text_from_thread(generation_id)
                    self._post_from_thread(
                        TurnCompletedMessage(TurnLifecyclePayload(generation_id))
                    )
        except TurnInterrupted:
            self._flush_text_from_thread(generation_id)
            self._post_from_thread(
                TurnInterruptedMessage(TurnLifecyclePayload(generation_id))
            )
        except MewCodeError as exc:
            self._flush_text_from_thread(generation_id)
            self._post_from_thread(
                TurnErrorMessage(
                    TurnErrorPayload(generation_id, exc.user_message)
                )
            )
        except Exception as exc:
            self._flush_text_from_thread(generation_id)
            self._post_from_thread(
                TurnErrorMessage(
                    TurnErrorPayload(
                        generation_id,
                        "Internal turn worker failure.",
                        type(exc).__name__,
                        INTERNAL_ERROR_SUGGESTION,
                    )
                )
            )

    def _queue_text(self, generation_id: int, text: str) -> None:
        should_schedule = False
        with self._text_lock:
            self._text_buffers.setdefault(generation_id, []).append(text)
            if generation_id not in self._flush_scheduled:
                self._flush_scheduled.add(generation_id)
                should_schedule = True
        if should_schedule:
            self.post_message(TextFlushRequested(generation_id))

    def _flush_text_from_thread(self, generation_id: int) -> None:
        text = self._take_buffer(generation_id)
        if text:
            self._post_from_thread(
                TurnTextMessage(TurnTextPayload(generation_id, text))
            )

    def _flush_text_on_main(self, generation_id: int) -> None:
        text = self._take_buffer(generation_id)
        if text:
            self.post_message(
                TurnTextMessage(TurnTextPayload(generation_id, text))
            )

    def on_text_flush_requested(self, message: TextFlushRequested) -> None:
        self._flush_text_on_main(message.generation_id)

    def _take_buffer(self, generation_id: int) -> str:
        with self._text_lock:
            chunks = self._text_buffers.pop(generation_id, [])
            self._flush_scheduled.discard(generation_id)
        return "".join(chunks)

    def _post_from_thread(self, message: object) -> None:
        try:
            self.call_from_thread(self.post_message, message)
        except RuntimeError:
            pass

    async def on_turn_phase_message(self, message: TurnPhaseMessage) -> None:
        payload = message.payload
        if not self._is_current(payload.generation_id):
            return
        if payload.phase is TurnPhase.INITIAL_RESPONSE:
            await self._show_activity(
                ActivityState.UPLINKING,
                self.metadata.model,
            )
            return

        await self._finalize_assistant()
        await self._show_activity(ActivityState.SYNTHESIZING)

    async def on_turn_text_message(self, message: TurnTextMessage) -> None:
        payload = message.payload
        if not self._is_current(payload.generation_id):
            return
        if self._cancellation is not None and self._cancellation.is_cancelled:
            return
        if self._activity is not None:
            await self._activity.remove()
            self._activity = None
        if self._assistant is None:
            self._assistant = AssistantMessageView(
                unicode=self.unicode_output
            )
            await self.query_one(ConversationView).append_widget(self._assistant)
        self._set_activity(ActivityState.STREAMING)
        await self._assistant.append_markdown(payload.text)
        self.query_one(ConversationView).note_output()

    async def on_turn_completed_message(
        self,
        message: TurnCompletedMessage,
    ) -> None:
        if self._is_interrupted_generation(message.payload.generation_id):
            self._finish_turn(ActivityState.INTERRUPTED)
            return
        if not self._is_current(message.payload.generation_id):
            return
        await self._finalize_assistant()
        await self._remove_activity()
        self._finish_turn(ActivityState.READY)

    async def on_turn_interrupted_message(
        self,
        message: TurnInterruptedMessage,
    ) -> None:
        if message.payload.generation_id != self._active_generation:
            return
        await self._mark_interrupted()
        self._finish_turn(ActivityState.INTERRUPTED)

    async def on_turn_error_message(self, message: TurnErrorMessage) -> None:
        if self._is_interrupted_generation(message.payload.generation_id):
            self._finish_turn(ActivityState.INTERRUPTED)
            return
        if not self._is_current(message.payload.generation_id):
            return
        await self._finalize_assistant()
        await self._remove_activity()
        await self.query_one(ConversationView).append_widget(
            ErrorCard(message.payload, unicode=self.unicode_output)
        )
        self._finish_turn(ActivityState.ERROR)

    async def on_tool_started_message(self, message: ToolStartedMessage) -> None:
        payload = message.payload
        if not self._is_current(payload.generation_id):
            return
        await self._finalize_assistant()
        await self._remove_activity()
        card = ToolCard(payload, unicode=self.unicode_output)
        self._tool_cards[payload.call_id] = card
        await self.query_one(ConversationView).append_widget(card)
        await self._show_activity(ActivityState.EXECUTING, payload.name)

    async def on_tool_finished_message(self, message: ToolFinishedMessage) -> None:
        payload = message.payload
        if not self._is_current(payload.generation_id):
            return
        await self._remove_activity()
        card = self._tool_cards.get(payload.call_id)
        if card is not None:
            card.finish(payload)
            self.query_one(ConversationView).note_output()

    async def on_tool_budget_message(self, message: ToolBudgetMessage) -> None:
        payload = message.payload
        if not self._is_current(payload.generation_id):
            return
        await self.query_one(ConversationView).append_widget(
            ErrorCard(
                TurnErrorPayload(
                    payload.generation_id,
                    "Tool limit reached for this turn.",
                    suggestion=TOOL_BUDGET_SUGGESTION,
                ),
                unicode=self.unicode_output,
            )
        )

    def on_confirmation_requested_message(
        self,
        message: ConfirmationRequestedMessage,
    ) -> None:
        payload = message.payload
        if not self._is_current(payload.generation_id):
            self.bridge.resolve_confirmation(payload.decision, False)
            return
        self._confirmation = payload.decision

        def resolve(approved: bool) -> None:
            self.bridge.resolve_confirmation(payload.decision, approved)
            if self._confirmation is payload.decision:
                self._confirmation = None

        self.push_screen(ConfirmationModal(payload.preview), resolve)

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

    async def action_interrupt(self) -> None:
        if self._active_generation is None or self._cancellation is None:
            return
        generation_id = self._active_generation
        if generation_id in self._interrupted_generations:
            return
        self._interrupted_generations.add(generation_id)
        self._cancellation.cancel()
        if isinstance(self.screen, ConfirmationModal):
            self.screen.dismiss(False)
        if self._confirmation is not None:
            self.bridge.resolve_confirmation(self._confirmation, False)
            self._confirmation = None
        await self._mark_interrupted()
        self._set_activity(ActivityState.INTERRUPTED)

    async def action_ctrl_c(self) -> None:
        if self._active_generation is not None:
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
            self.exit(0)
            return
        self._exit_armed_until = now + 2.0
        self.query_one("#exit-hint", Static).update(
            "Press Ctrl+C again within 2s to exit."
        )

    def action_ctrl_d(self) -> None:
        composer = self.query_one(PromptComposer)
        if self._active_generation is None and not composer.text:
            self.exit(0)

    def action_return_to_bottom(self) -> None:
        self.query_one(ConversationView).return_to_bottom()

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

    def _finish_turn(self, state: ActivityState) -> None:
        if self._active_generation is not None:
            self._interrupted_generations.discard(self._active_generation)
        self._set_activity(state)
        self._active_generation = None
        self._cancellation = None
        self._turn_worker = None
        composer = self.query_one(PromptComposer)
        composer.set_busy(False)
        composer.focus()

    def _is_current(self, generation_id: int) -> bool:
        return (
            generation_id == self._active_generation
            and generation_id not in self._interrupted_generations
        )

    def _is_interrupted_generation(self, generation_id: int) -> bool:
        return (
            generation_id == self._active_generation
            and generation_id in self._interrupted_generations
        )

    def _disarm_exit(self) -> None:
        self._exit_armed_until = 0.0
        self.query_one("#exit-hint", Static).update("")
