// android/app/src/main/java/io/github/shark2558/jarvis/calls/CallStateReceiver.kt
// R18 D: Android's PHONE_STATE broadcast (one of the few an app may still receive in its manifest:
// Android's own list of implicit-broadcast exceptions keeps it). Not reachable from other apps: the
// system sends it. Each change goes through core's CallMachine, which reports only JARVIS's calls,
// and an incoming call only while answering missed calls is on; the reports go to the cloud on the
// door at once, and the answer may carry a command (call.answer, call.end, call.route).
//
// For answering, the ringing call is reported at its first ring and again at the ring the owner
// chose (after_rings, 5 by default), with the number only when the cloud asked for it; that second
// request waits up to ANSWER_WAIT_S for the cloud's call.answer. All of it runs inside goAsync(),
// held at most HOLD_MS (Android allows a background broadcast a minute).
package io.github.shark2558.jarvis.calls

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.telephony.TelephonyManager
import io.github.shark2558.jarvis.core.CallEvent
import io.github.shark2558.jarvis.core.CallMachine
import io.github.shark2558.jarvis.core.CallPayloads
import io.github.shark2558.jarvis.core.CallRules
import io.github.shark2558.jarvis.core.PhonePhase
import io.github.shark2558.jarvis.core.StateEvent
import io.github.shark2558.jarvis.core.StateReport
import io.github.shark2558.jarvis.link.AppState

class CallStateReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != TelephonyManager.ACTION_PHONE_STATE_CHANGED) return
        val app = context.applicationContext
        if (!AppState(app).canSend()) return
        val next = CallMachine.phaseOf(intent.getStringExtra(TelephonyManager.EXTRA_STATE)) ?: return
        @Suppress("DEPRECATION") // the one way left to an app that is neither dialer nor screener
        val incoming = if (CallsAccess.granted(app, CallsAccess.NUMBER)) intent.getStringExtra(TelephonyManager.EXTRA_INCOMING_NUMBER) else null
        val store = CallsStore(app)
        val answering = store.answering()
        val reports = synchronized(CallsStore.LOCK) {
            val step = store.machine().onPhone(next, System.currentTimeMillis(), answering.on, incoming, answering.sendNumber)
            store.saveMachine(step.machine)
            step.reports
        }
        if (next == PhonePhase.IDLE) CallActions.releaseSound(app)
        val ringing = next == PhonePhase.RINGING && reports.isNotEmpty()
        if (reports.isEmpty()) return
        val pending = goAsync()
        CallsLink.worker.execute {
            try {
                CallsLink.pullAndAct(app, events(reports))
                if (ringing) atChosenRing(app)
            } finally {
                pending.finish()
            }
        }
    }

    /** Wait for the owner's ring; if it still rings, report it and give the cloud time to answer. */
    private fun atChosenRing(context: Context) {
        val store = CallsStore(context)
        val rule = store.answering()
        if (!rule.on) return
        val start = synchronized(CallsStore.LOCK) { store.machine() }.ringStartMs
        val due = start + CallRules.msUntilRing(rule.afterRings)
        val deadline = start + HOLD_MS - ANSWER_WAIT_S * MILLIS
        while (System.currentTimeMillis() < minOf(due, deadline)) {
            Thread.sleep(POLL_MS)
            if (!synchronized(CallsStore.LOCK) { store.machine() }.ringing) return // he answered, or it stopped
        }
        val report = synchronized(CallsStore.LOCK) { store.machine() }.ringAt(System.currentTimeMillis(), rule.sendNumber) ?: return
        CallsLink.pullAndAct(context, events(listOf(report)), ANSWER_WAIT_S.toInt())
    }

    private fun events(reports: List<StateReport>): List<CallEvent> {
        val at = CallsLink.nowS()
        return reports.map { StateEvent(CallPayloads.newEventId(), it.callId, it.state, it.number, it.rings, at) }
    }

    private companion object {
        const val HOLD_MS = 50_000L
        const val ANSWER_WAIT_S = 10L
        const val POLL_MS = 500L
        const val MILLIS = 1000L
    }
}
