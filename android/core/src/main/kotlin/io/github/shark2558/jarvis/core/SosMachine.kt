// android/core/src/main/kotlin/io/github/shark2558/jarvis/core/SosMachine.kt
// R7 D19: the SOS state machine, idle -> holding -> countdown -> sending -> sent / cancelled /
// failed. Pure: the screen passes a monotonic clock in milliseconds (SystemClock.elapsedRealtime)
// and does the sending itself. `send` is called at most once, and never after a cancel: a
// cancelled countdown sends nothing at all. Inside JARVIS a 2-second hold comes before a 5-second
// countdown; from the tile or a shortcut the 10-second countdown takes the hold's place.
// One press is at most one send, ever: every press has an id, the process-wide PressLedger lets
// the send go out once per id (so a recreated screen cannot send it again) and keeps the answer,
// and the machine can be saved and restored across a recreation. A new tile press starts a
// fresh countdown unless a real one is already counting or sending (SosPress.startsFresh).
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

/** Which presses have sent, and what came back, for the life of the process. */
class PressLedger {
    data class Outcome(val ok: Boolean, val reached: Int, val why: String)

    private val claimed = HashSet<String>()
    private val outcomes = HashMap<String, Outcome>()

    /** True exactly once per press id: the right to send. */
    @Synchronized
    fun claim(id: String): Boolean = claimed.add(id)

    @Synchronized
    fun isClaimed(id: String): Boolean = id in claimed

    @Synchronized
    fun record(id: String, outcome: Outcome) {
        outcomes[id] = outcome
    }

    @Synchronized
    fun outcome(id: String): Outcome? = outcomes[id]
}

/** The rule for a press that arrives while the screen already exists (a tile pressed again). */
object SosPress {
    /** A new press always gets a live flow, except that a real countdown or send in progress
     *  stands (it is never sent twice, and a second tap must not restart its cancel window).
     *  A test in progress gives way to a real press: nothing real has gone yet. */
    fun startsFresh(state: SosState, current: SosKind, next: SosKind): Boolean = when (state) {
        SosState.Idle, SosState.Cancelled, is SosState.Sent, is SosState.Failed -> true
        is SosState.Counting, SosState.Sending -> current == SosKind.TEST && next == SosKind.REAL
        is SosState.Holding -> false
    }
}

class SosMachine(
    private val kind: SosKind,
    private val holdMs: Long,
    private val countdownMs: Long,
    private val pressId: String = "",
    private val ledger: PressLedger = PressLedger(),
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
            if (ledger.claim(pressId)) send(kind) // a press that already sent never sends again
            return
        }
        if (s == SosState.Sending) ledger.outcome(pressId)?.let { done(it.ok, it.reached, it.why) }
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
        ledger.record(pressId, PressLedger.Outcome(ok, reached, why))
        state = if (ok) SosState.Sent(reached) else SosState.Failed(why)
    }

    /** What a screen keeps across a recreation (plain values only). */
    data class Saved(val pressId: String, val phase: Int, val untilMs: Long, val reached: Int, val why: String)

    fun saved(): Saved = when (val s = state) {
        is SosState.Counting -> Saved(pressId, COUNTING, s.untilMs, 0, "")
        SosState.Sending -> Saved(pressId, SENDING, 0L, 0, "")
        is SosState.Sent -> Saved(pressId, SENT, 0L, s.reached, "")
        SosState.Cancelled -> Saved(pressId, CANCELLED, 0L, 0, "")
        is SosState.Failed -> Saved(pressId, FAILED, 0L, 0, s.why)
        else -> Saved(pressId, IDLE, 0L, 0, "")
    }

    /** Whole seconds left, rounded up, for the screen. */
    fun remainingSeconds(nowMs: Long): Long = when (val s = state) {
        is SosState.Counting -> maxOf(0L, (s.untilMs - nowMs + 999L) / 1000L)
        is SosState.Holding -> maxOf(0L, (s.sinceMs + holdMs + countdownMs - nowMs + 999L) / 1000L)
        else -> 0L
    }

    companion object {
        private const val IDLE = 0
        private const val COUNTING = 2
        private const val SENDING = 3
        private const val SENT = 4
        private const val CANCELLED = 5
        private const val FAILED = 6

        /** The same press after a recreation. It never sends what was already sent; a countdown
         *  that ran out while the screen was away is not fired late (nothing is sent after the
         *  owner's cancel window has gone by unseen), unless the ledger knows it had been sent. */
        fun restore(
            saved: Saved,
            kind: SosKind,
            holdMs: Long,
            countdownMs: Long,
            nowMs: Long,
            ledger: PressLedger,
            send: (SosKind) -> Unit,
        ): SosMachine {
            val m = SosMachine(kind, holdMs, countdownMs, saved.pressId, ledger, send)
            m.state = when (saved.phase) {
                COUNTING -> when {
                    nowMs < saved.untilMs -> SosState.Counting(saved.untilMs)
                    ledger.isClaimed(saved.pressId) -> SosState.Sending
                    else -> SosState.Cancelled
                }
                SENDING -> SosState.Sending
                SENT -> SosState.Sent(saved.reached)
                FAILED -> SosState.Failed(saved.why)
                CANCELLED -> SosState.Cancelled
                else -> SosState.Idle
            }
            return m
        }
    }
}
