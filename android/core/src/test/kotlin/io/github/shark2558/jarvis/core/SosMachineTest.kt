// android/core/src/test/kotlin/io/github/shark2558/jarvis/core/SosMachineTest.kt
// R7 D19, D24: the SOS state machine (idle -> holding -> countdown -> sending -> sent / cancelled /
// failed). The must: a cancel at ANY moment before the countdown ends sends nothing at all.
package io.github.shark2558.jarvis.core

private const val HOLD_MS = 2_000L
private const val SHORT_MS = 5_000L
private const val TILE_MS = 10_000L
private const val STEP_MS = 50L

private class Sends {
    val kinds = ArrayList<SosKind>()
    fun machine(kind: SosKind, holdMs: Long, countdownMs: Long): SosMachine =
        SosMachine(kind, holdMs, countdownMs) { kinds.add(it) }
}

private fun runUntil(m: SosMachine, fromMs: Long, toMs: Long) {
    var now = fromMs
    while (now <= toMs) {
        m.tick(now)
        now += STEP_MS
    }
}

fun sosCases(): List<Case> = cases(
    "sos",
    "from the tile: a 10-second countdown sends exactly once, at its end" to {
        val s = Sends()
        val m = s.machine(SosKind.REAL, 0L, TILE_MS)
        m.startCountdown(0L)
        runUntil(m, 0L, TILE_MS - STEP_MS)
        same(0, s.kinds.size, "nothing is sent before ten seconds")
        same(1L, m.remainingSeconds(TILE_MS - STEP_MS), "one second is shown last")
        runUntil(m, TILE_MS, TILE_MS + 5_000L)
        same(listOf(SosKind.REAL), s.kinds, "one real send")
        same<SosState>(SosState.Sending, m.state, "sending")
    },
    "a cancel at any moment of the tile's countdown sends nothing, ever" to {
        var at = 0L
        while (at < TILE_MS) {
            val s = Sends()
            val m = s.machine(SosKind.REAL, 0L, TILE_MS)
            m.startCountdown(0L)
            runUntil(m, 0L, at)
            m.cancel(at)
            runUntil(m, at, TILE_MS * 3)
            same(0, s.kinds.size, "cancelled at $at ms: nothing sent")
            same<SosState>(SosState.Cancelled, m.state, "cancelled at $at ms")
            at += STEP_MS
        }
    },
    "inside JARVIS: a 2-second hold, then a 5-second countdown" to {
        val s = Sends()
        val m = s.machine(SosKind.REAL, HOLD_MS, SHORT_MS)
        m.press(0L)
        runUntil(m, 0L, HOLD_MS)
        yes(m.state is SosState.Counting, "the hold became a countdown: ${m.state}")
        runUntil(m, HOLD_MS, HOLD_MS + SHORT_MS - STEP_MS)
        same(0, s.kinds.size, "nothing before the countdown ends")
        runUntil(m, HOLD_MS + SHORT_MS, HOLD_MS + SHORT_MS)
        same(listOf(SosKind.REAL), s.kinds, "one send after the hold and the countdown")
    },
    "letting go before two seconds goes back to idle and sends nothing" to {
        val s = Sends()
        val m = s.machine(SosKind.REAL, HOLD_MS, SHORT_MS)
        m.press(0L)
        runUntil(m, 0L, 1_500L)
        m.release(1_500L)
        same<SosState>(SosState.Idle, m.state, "idle after a short press")
        runUntil(m, 1_500L, 20_000L)
        same(0, s.kinds.size, "a short press sends nothing")
    },
    "letting go after two seconds keeps the countdown" to {
        val s = Sends()
        val m = s.machine(SosKind.TEST, HOLD_MS, SHORT_MS)
        m.press(0L)
        m.release(HOLD_MS + 10L)
        yes(m.state is SosState.Counting, "the countdown runs after a full hold: ${m.state}")
        runUntil(m, HOLD_MS, HOLD_MS + SHORT_MS + STEP_MS)
        same(listOf(SosKind.TEST), s.kinds, "a test send")
    },
    "a cancel at any moment of the hold or the countdown sends nothing, ever" to {
        var at = 0L
        while (at < HOLD_MS + SHORT_MS) {
            val s = Sends()
            val m = s.machine(SosKind.REAL, HOLD_MS, SHORT_MS)
            m.press(0L)
            runUntil(m, 0L, at)
            m.cancel(at)
            m.release(at)
            runUntil(m, at, 60_000L)
            same(0, s.kinds.size, "cancelled at $at ms: nothing sent")
            at += STEP_MS
        }
    },
    "a cancelled machine cannot be started again" to {
        val s = Sends()
        val m = s.machine(SosKind.REAL, 0L, TILE_MS)
        m.cancel(0L)
        m.startCountdown(1L)
        m.press(1L)
        runUntil(m, 1L, TILE_MS * 2)
        same(0, s.kinds.size, "nothing sent after a cancel")
        same<SosState>(SosState.Cancelled, m.state, "still cancelled")
    },
    "the answer moves sending to sent or failed, once" to {
        val s = Sends()
        val m = s.machine(SosKind.REAL, 0L, TILE_MS)
        m.startCountdown(0L)
        runUntil(m, 0L, TILE_MS)
        m.done(ok = true, reached = 3, why = "")
        same<SosState>(SosState.Sent(3), m.state, "sent to three")
        m.done(ok = false, reached = 0, why = "late")
        same<SosState>(SosState.Sent(3), m.state, "a second answer changes nothing")
        val f = s.machine(SosKind.REAL, 0L, TILE_MS)
        f.startCountdown(0L)
        runUntil(f, 0L, TILE_MS)
        f.done(ok = false, reached = 0, why = "no internet")
        same<SosState>(SosState.Failed("no internet"), f.state, "failed")
    },
    "a cancel after the send cannot take it back, and a later tick sends nothing more" to {
        val s = Sends()
        val m = s.machine(SosKind.REAL, 0L, TILE_MS)
        m.startCountdown(0L)
        runUntil(m, 0L, TILE_MS)
        m.cancel(TILE_MS + 1L)
        runUntil(m, TILE_MS, TILE_MS * 4)
        same(1, s.kinds.size, "exactly one send")
        same<SosState>(SosState.Sending, m.state, "still sending: \"I'm safe\" is the way back")
    },
    "an answer before any send is ignored" to {
        val s = Sends()
        val m = s.machine(SosKind.REAL, 0L, TILE_MS)
        m.done(ok = true, reached = 1, why = "")
        same<SosState>(SosState.Idle, m.state, "still idle")
    },
)
