// android/core/src/main/kotlin/io/github/shark2558/jarvis/core/SosMachine.kt
// R7 D19: the SOS state machine, idle -> holding -> countdown -> sending -> sent / cancelled /
// failed. Pure: the screen passes a monotonic clock in milliseconds (SystemClock.elapsedRealtime)
// and does the sending itself. `send` is called at most once, and never after a cancel: a
// cancelled countdown sends nothing at all. Inside JARVIS a 2-second hold comes before a 5-second
// countdown; from the tile or a shortcut the 10-second countdown takes the hold's place.
package io.github.shark2558.jarvis.core

sealed interface SosState {
    data object Idle : SosState

    data class Holding(val sinceMs: Long) : SosState

    data class Counting(val untilMs: Long) : SosState

    data object Sending : SosState

    data class Sent(val reached: Int) : SosState

    data object Cancelled : SosState

    data class Failed(val why: String) : SosState
}

class SosMachine(
    private val kind: SosKind,
    private val holdMs: Long,
    private val countdownMs: Long,
    private val send: (SosKind) -> Unit,
) {
    var state: SosState = SosState.Idle
        private set

    /** A finger on the button (the hold starts). */
    fun press(nowMs: Long) {
        if (state == SosState.Idle) state = SosState.Holding(nowMs)
    }

    /** The finger left the button: before the hold is complete, nothing happens. */
    fun release(nowMs: Long) {
        tick(nowMs)
        if (state is SosState.Holding) state = SosState.Idle
    }

    /** From the tile or a shortcut: the countdown starts at once. */
    fun startCountdown(nowMs: Long) {
        if (state == SosState.Idle) state = SosState.Counting(nowMs + countdownMs)
    }

    fun tick(nowMs: Long) {
        val s = state
        if (s is SosState.Holding && nowMs - s.sinceMs >= holdMs) {
            state = SosState.Counting(s.sinceMs + holdMs + countdownMs)
            return
        }
        if (s is SosState.Counting && nowMs >= s.untilMs) {
            state = SosState.Sending
            send(kind)
        }
    }

    /** Cancel works until the send has started; after that only "I'm safe" can follow. */
    fun cancel(nowMs: Long) {
        val s = state
        if (s == SosState.Idle || s is SosState.Holding || s is SosState.Counting) {
            state = SosState.Cancelled
        }
    }

    fun done(ok: Boolean, reached: Int, why: String) {
        if (state != SosState.Sending) return
        state = if (ok) SosState.Sent(reached) else SosState.Failed(why)
    }

    /** Whole seconds left, rounded up, for the screen. */
    fun remainingSeconds(nowMs: Long): Long = when (val s = state) {
        is SosState.Counting -> maxOf(0L, (s.untilMs - nowMs + 999L) / 1000L)
        is SosState.Holding -> maxOf(0L, (s.sinceMs + holdMs + countdownMs - nowMs + 999L) / 1000L)
        else -> 0L
    }
}
